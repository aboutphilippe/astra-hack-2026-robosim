using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using Mujoco;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

/// <summary>
/// Adds native MuJoCo physics to the reconstructed room without replacing its
/// segmented visual meshes. Collider geometry is deliberately low complexity.
/// Each MuJoCo element has its own GameObject, as required by the official plugin.
/// </summary>
public static class ReconstructionPhysics
{
    const string PhysicsRootName = "MuJoCo physics";
    const float StepSeconds = 0.002f;

    public static void Configure(GameObject visualRoot)
    {
        if (visualRoot == null) throw new ArgumentNullException(nameof(visualRoot));
        if (visualRoot.transform.Find(PhysicsRootName) != null)
            throw new InvalidOperationException("Physics has already been configured for this reconstruction.");

        // MuJoCo reads these two Unity settings when it generates MJCF.
        Physics.gravity = new Vector3(0, -9.81f, 0);
        Time.fixedDeltaTime = StepSeconds;

        // The scene has one physics authority. Imported render meshes do not
        // need PhysX colliders or rigid bodies to participate in MuJoCo.
        foreach (var joint in visualRoot.GetComponentsInChildren<Joint>(true)) Object.DestroyImmediate(joint);
        foreach (var body in visualRoot.GetComponentsInChildren<Rigidbody>(true)) Object.DestroyImmediate(body);
        foreach (var body in visualRoot.GetComponentsInChildren<ArticulationBody>(true)) Object.DestroyImmediate(body);
        foreach (var collider in visualRoot.GetComponentsInChildren<Collider>(true)) Object.DestroyImmediate(collider);

        var physicsRoot = NewChild(PhysicsRootName, visualRoot.transform);
        // Physics proxies use world metres and therefore require unit scale.
        physicsRoot.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
        physicsRoot.transform.localScale = Vector3.one;
        if ((physicsRoot.transform.lossyScale - Vector3.one).sqrMagnitude > 1e-8f)
            throw new InvalidOperationException("The reconstruction root must use unit scale; meshes must already be in metres.");

        var staticRoot = NewChild("Static collision proxies", physicsRoot.transform);
        var dynamicRoot = NewChild("Dynamic chess pieces", physicsRoot.transform);
        var settings = NewChild("MuJoCo settings", physicsRoot.transform).AddComponent<MjGlobalSettings>();
        settings.GlobalOptions = MjOptionStruct.Default;
        settings.GlobalOptions.Integrator = IntegratorType.implicitfast;
        settings.GlobalOptions.Cone = FrictionConeType.elliptic;
        settings.GlobalOptions.Solver = ConstraintSolverType.Newton;
        settings.GlobalOptions.Iterations = 100;
        settings.GlobalSizes.Memory = "64M";
        settings.MouseSpringStiffness = 0.5f; // Appropriate for 35 g chess pieces.

        var instances = visualRoot.GetComponentsInChildren<SegmentedInstance>(true);
        var planks = instances.Where(i => i.semanticClass == "floor_plank").ToArray();
        if (planks.Length > 0)
        {
            // One slab gives a continuous contact surface across all 385 planks.
            // All planks retain their independent rendering/segmentation IDs.
            var floor = AggregateBounds(planks.Select(i => i.WorldBounds()));
            var floorTop = floor.max.y;
            floor.SetMinMax(new Vector3(floor.min.x, floorTop - 0.10f, floor.min.z), floor.max);
            AddBox("Floor_parquet_contact_surface", staticRoot.transform, floor);
        }

        Bounds? boardBounds = null;
        foreach (var instance in instances)
        {
            switch (instance.semanticClass)
            {
                case "floor":
                    if (planks.Length == 0 || instance.instanceId != "floor_base")
                        AddBox(instance.instanceId + "_contact", staticRoot.transform, instance.WorldBounds());
                    break;
                case "desk":
                    AddDesk(instance, staticRoot.transform);
                    break;
                case "chessboard":
                    boardBounds = instance.WorldBounds();
                    AddBox(instance.instanceId + "_contact", staticRoot.transform, boardBounds.Value);
                    break;
                case "chair":
                    AddChair(instance, staticRoot.transform);
                    break;
                case "backpack":
                case "shopping_bag":
                case "planter":
                case "wall":
                case "window_glass":
                case "door":
                    AddBox(instance.instanceId + "_contact", staticRoot.transform, instance.WorldBounds());
                    break;
            }
        }

        var chessPieces = instances.Where(i => i.semanticClass == "chess_piece").ToArray();
        if (chessPieces.Length != 32 || !boardBounds.HasValue)
            throw new InvalidOperationException($"Expected a chessboard and 32 chess pieces; found {chessPieces.Length} pieces.");

        foreach (var piece in chessPieces)
            AddChessPiece(piece, dynamicRoot.transform, boardBounds.Value.max.y);

        Debug.Log($"MuJoCo configured: {chessPieces.Length} free chess bodies and " +
                  $"{physicsRoot.GetComponentsInChildren<MjGeom>().Length} collision geoms. " +
                  "All source visual segments and their IDs are retained.");
    }

    static void AddDesk(SegmentedInstance instance, Transform parent)
    {
        var renderers = instance.GetComponentsInChildren<Renderer>();
        var tops = renderers.Where(r => Normalized(r.name).Contains("oak top")).ToArray();
        // Source component names are preserved, but allow a safe geometry-based
        // fallback if the reconstruction is re-exported with renamed meshes.
        if (tops.Length == 0)
            tops = renderers.Where(r => r.bounds.size.y < 0.10f)
                .OrderByDescending(r => r.bounds.size.x * r.bounds.size.z).Take(1).ToArray();
        if (tops.Length == 0) throw new InvalidOperationException("Desk has no tabletop mesh: " + instance.instanceId);
        foreach (var renderer in tops)
            AddBox(instance.instanceId + "_tabletop", parent, renderer.bounds);
        foreach (var renderer in renderers)
        {
            var name = Normalized(renderer.name);
            if (name.Contains("outer column") || name.Contains("floor runner"))
                AddBox(instance.instanceId + "_" + renderer.name + "_contact", parent, renderer.bounds);
        }
    }

    static void AddChair(SegmentedInstance instance, Transform parent)
    {
        foreach (var renderer in instance.GetComponentsInChildren<Renderer>())
        {
            var name = Normalized(renderer.name);
            if (name.Contains("slim upholstered seat") || name.Contains("upholstered back"))
                AddBox(instance.instanceId + "_" + renderer.name + "_contact", parent, renderer.bounds);
        }
    }

    static void AddChessPiece(SegmentedInstance instance, Transform parent, float boardTop)
    {
        var bounds = instance.WorldBounds();
        // Ensure an initial submillimetre clearance rather than embedding the
        // contact proxy in the board's lettering or bevelled top surface.
        var lift = Mathf.Max(0, boardTop + 0.0005f - bounds.min.y);
        instance.transform.position += Vector3.up * lift;
        bounds.center += Vector3.up * lift;

        var body = NewChild(instance.instanceId + "_MuJoCo_body", parent);
        body.transform.SetPositionAndRotation(bounds.center, Quaternion.identity);
        body.AddComponent<MjBody>();
        NewChild(instance.instanceId + "_free_joint", body.transform).AddComponent<MjFreeJoint>();

        // A weighted base and an enclosing upright cylinder provide a stable,
        // inexpensive proxy; the carved source mesh remains the visible object.
        var radius = Mathf.Max(0.006f, Mathf.Max(bounds.extents.x, bounds.extents.z));
        var baseHeight = Mathf.Min(0.012f, bounds.size.y * 0.3f);
        AddCylinder(instance.instanceId + "_base_contact", body.transform,
            new Vector3(bounds.center.x, bounds.min.y + baseHeight / 2, bounds.center.z),
            radius, baseHeight / 2, 0.027f);
        var upperHeight = Mathf.Max(0.002f, bounds.size.y - baseHeight);
        AddCylinder(instance.instanceId + "_upper_contact", body.transform,
            new Vector3(bounds.center.x, bounds.min.y + baseHeight + upperHeight / 2, bounds.center.z),
            radius, upperHeight / 2, 0.008f);

        instance.transform.SetParent(body.transform, true);
    }

    static MjGeom AddBox(string name, Transform parent, Bounds bounds)
    {
        var proxy = NewChild(name, parent);
        proxy.transform.SetPositionAndRotation(bounds.center, Quaternion.identity);
        var geom = proxy.AddComponent<MjGeom>();
        geom.ShapeType = MjShapeComponent.ShapeTypes.Box;
        geom.Box.Extents = Vector3.Max(bounds.extents, Vector3.one * 0.0005f);
        geom.Density = 0; // A world geom is static; no inferred furniture mass.
        SetContact(geom);
        return geom;
    }

    static MjGeom AddCylinder(string name, Transform parent, Vector3 center, float radius, float halfHeight, float mass)
    {
        var proxy = NewChild(name, parent);
        proxy.transform.SetPositionAndRotation(center, Quaternion.identity);
        var geom = proxy.AddComponent<MjGeom>();
        geom.ShapeType = MjShapeComponent.ShapeTypes.Cylinder;
        geom.Cylinder.Radius = radius;
        geom.Cylinder.HalfHeight = halfHeight;
        geom.Mass = mass;
        SetContact(geom);
        return geom;
    }

    static void SetContact(MjGeom geom)
    {
        geom.Settings = MjGeomSettings.Default;
        geom.Settings.Friction.Sliding = 0.65f;
        geom.Settings.Friction.Torsional = 0.003f;
        geom.Settings.Friction.Rolling = 0.0001f;
        geom.Settings.Solver.ConDim = 4;
        geom.Settings.Solver.Margin = 0.0001f;
        geom.Settings.Solver.SolRef.TimeConst = 0.01f;
        geom.Settings.Solver.SolRef.DampRatio = 1;
    }

    static GameObject NewChild(string name, Transform parent)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        return go;
    }

    static string Normalized(string value) => value.Replace('_', ' ').ToLowerInvariant();

    static Bounds AggregateBounds(IEnumerable<Bounds> values)
    {
        var array = values.ToArray();
        var result = array[0];
        for (var i = 1; i < array.Length; ++i) result.Encapsulate(array[i]);
        return result;
    }

    [Serializable]
    public sealed class SimulationReport
    {
        public bool passed;
        public string nativeVersion;
        public int numberBodies;
        public int dynamicBodies;
        public int numberGeoms;
        public int qpos;
        public int degreesOfFreedom;
        public int steps;
        public double timestep;
        public double simulatedSeconds;
        public int peakContacts;
        public bool finiteState;
        public float maxBodyDisplacementMetres;
        public double maxAbsoluteVelocity;
        public string mjcfAssetPath;
    }

    /// <summary>
    /// Compiles and steps the real native MuJoCo engine, then restores the
    /// authored pose so validation never changes the saved reference scene.
    /// Throws if the model cannot compile, diverges, or loses its chess pieces.
    /// </summary>
    public static unsafe string ValidateSimulation()
    {
        if (Application.isPlaying)
            throw new InvalidOperationException("Run this validation in Edit mode to preserve the active simulation.");
        var bodies = Object.FindObjectsByType<MjBody>(FindObjectsSortMode.None);
        var components = Object.FindObjectsByType<MjComponent>(FindObjectsSortMode.None);
        var savedTransforms = components.Select(c => c.transform).Distinct()
            .Select(t => (transform: t, position: t.position, rotation: t.rotation)).ToArray();
        var bodyPositions = bodies.ToDictionary(body => body, body => body.transform.position);
        var scene = MjScene.Instance;
        var report = new SimulationReport
        {
            dynamicBodies = Object.FindObjectsByType<MjFreeJoint>(FindObjectsSortMode.None).Length,
            steps = 1000,
            finiteState = true,
            mjcfAssetPath = "Assets/MuJoCo/reconstructed_physics.xml"
        };
        try
        {
            scene.DestroyScene();
            var xml = scene.CreateScene();
            report.nativeVersion = Marshal.PtrToStringAnsi(MujocoLib.mj_versionString());
            report.numberBodies = checked((int)scene.Model->nbody);
            report.numberGeoms = checked((int)scene.Model->ngeom);
            report.qpos = checked((int)scene.Model->nq);
            report.degreesOfFreedom = checked((int)scene.Model->nv);
            report.timestep = scene.Model->opt.timestep;
            Directory.CreateDirectory(Path.GetDirectoryName(report.mjcfAssetPath));
            xml.Save(report.mjcfAssetPath);

            for (var step = 0; step < report.steps; ++step)
            {
                scene.StepScene(); // Also checks MuJoCo's native warning counters.
                report.peakContacts = Mathf.Max(report.peakContacts, scene.Data->ncon);
                for (var q = 0; q < report.qpos; ++q)
                    RequireFinite(scene.Data->qpos[q], "qpos", step);
                for (var q = 0; q < report.degreesOfFreedom; ++q)
                {
                    RequireFinite(scene.Data->qvel[q], "qvel", step);
                    RequireFinite(scene.Data->qacc[q], "qacc", step);
                    report.maxAbsoluteVelocity = Math.Max(report.maxAbsoluteVelocity, Math.Abs(scene.Data->qvel[q]));
                }
                foreach (var body in bodies)
                    report.maxBodyDisplacementMetres = Mathf.Max(report.maxBodyDisplacementMetres,
                        Vector3.Distance(body.transform.position, bodyPositions[body]));
            }
            report.simulatedSeconds = scene.Data->time;
            report.passed = report.dynamicBodies == 32 && report.qpos == 224 &&
                report.degreesOfFreedom == 192 && report.peakContacts > 0 &&
                report.maxBodyDisplacementMetres < 0.03f && report.maxAbsoluteVelocity < 10 &&
                Math.Abs(report.simulatedSeconds - report.steps * report.timestep) < 1e-6;
            if (!report.passed)
                throw new InvalidOperationException("MuJoCo stability validation failed: " + JsonUtility.ToJson(report));
            return JsonUtility.ToJson(report, true);
        }
        finally
        {
            scene.DestroyScene();
            // Restore parents before children, since all saved values are world poses.
            foreach (var pose in savedTransforms.OrderBy(p => HierarchyDepth(p.transform)))
                if (pose.transform) pose.transform.SetPositionAndRotation(pose.position, pose.rotation);
            // Let MjComponent create the runtime singleton afresh on entering Play.
            Object.DestroyImmediate(scene.gameObject);
            AssetDatabase.Refresh();
        }
    }

    static void RequireFinite(double value, string field, int step)
    {
        if (double.IsNaN(value) || double.IsInfinity(value))
            throw new InvalidOperationException($"Nonfinite MuJoCo {field} at simulation step {step}.");
    }

    static int HierarchyDepth(Transform transform)
    {
        var depth = 0;
        while (transform.parent != null) { transform = transform.parent; ++depth; }
        return depth;
    }
}
