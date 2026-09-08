using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine.SceneManagement;

public static class BuildReconstructedRoom
{
    const string Source = "Assets/Reconstruction/Source/";
    const string ScenePath = "Assets/Scenes/ReconstructedRoom.unity";

    [Serializable] public class BoundsInfo { public float[] min; public float[] max; }
    [Serializable] public class ComponentInfo
    {
        public string export_name, original_name, instance_id, semantic_class, group_name;
        public int segmentation_index;
        public BoundsInfo bounds_unity;
        public string[] materials;
    }
    [Serializable] public class InstanceInfo
    {
        public string instance_id, semantic_class, export_group;
        public int index;
        public int[] color_rgb;
        public string[] component_names;
    }
    [Serializable] public class MaterialInfo
    {
        public string name, original_name, texture_path;
        public float[] base_color_linear, emission_color_linear;
        public float roughness, metallic, transmission, emission_strength;
    }
    [Serializable] public class CameraInfo
    {
        public string name;
        public float[] position_unity, forward_unity, up_unity;
        public float lens_mm, sensor_width_mm, fov_vertical_deg;
        public bool active;
    }
    [Serializable] public class Metadata
    {
        public string coordinate_mapping;
        public int component_count, instance_count;
        public ComponentInfo[] components;
        public InstanceInfo[] instances;
        public MaterialInfo[] materials;
        public CameraInfo[] cameras;
    }
    [Serializable] public class ImportReport
    {
        public bool success;
        public string scene, unity_version, mujoco_version, coordinate_mapping;
        public int expected_instances, imported_instances, expected_components, imported_components;
        public float max_bounds_error_m;
        public string[] missing_components;
        public string physics_validation_json;
    }

    static Vector3 V(float[] values) => new Vector3(values[0], values[1], values[2]);
    static Color C(float[] values) => new Color(values[0], values[1], values[2], values.Length > 3 ? values[3] : 1);
    static string Safe(string s) => new string(s.Select(c => char.IsLetterOrDigit(c) || c == '_' || c == '-' ? c : '_').ToArray());

    [MenuItem("Reconstruction/Build Reconstructed Room")]
    public static void Build()
    {
        var metadata = JsonUtility.FromJson<Metadata>(File.ReadAllText(Source + "scene_metadata.json"));
        if (metadata.components == null || metadata.instances == null) throw new InvalidDataException("Missing export metadata");
        Directory.CreateDirectory("Assets/Scenes"); Directory.CreateDirectory("Assets/Reconstruction/Materials");
        Directory.CreateDirectory("Validation");
        PlayerSettings.productName = "Reconstructed Room · MuJoCo";
        PlayerSettings.companyName = "Reconstruction";
        PlayerSettings.allowUnsafeCode = true;
        PlayerSettings.colorSpace = ColorSpace.Linear;
        PlayerSettings.defaultScreenWidth = 1080; PlayerSettings.defaultScreenHeight = 1440;
        PlayerSettings.resizableWindow = true;
        QualitySettings.antiAliasing = 4;
        QualitySettings.shadows = ShadowQuality.All;
        QualitySettings.shadowResolution = ShadowResolution.High;
        QualitySettings.shadowDistance = 25;
        QualitySettings.vSyncCount = 1;
        QualitySettings.pixelLightCount = 4;
        Time.fixedDeltaTime = .002f;
        Physics.gravity = new Vector3(0, -9.81f, 0);

        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        var materials = CreateMaterials(metadata.materials);
        AssetDatabase.Refresh();
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(Source + "reconstructed_scene.fbx");
        if (prefab == null) throw new FileNotFoundException("Exported FBX did not import");
        var root = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
        PrefabUtility.UnpackPrefabInstance(root, PrefabUnpackMode.Completely, InteractionMode.AutomatedAction);
        root.name = "Reconstructed room | 1,025 segmented instances";
        // FBX's forward-axis convention imports the baked scene facing -Z.
        // This proper rotation restores the sidecar's Blender(x,y,z)->Unity(x,z,y) basis.
        root.transform.rotation = Quaternion.Euler(0,180,0);
        var transforms = root.GetComponentsInChildren<Transform>(true).ToDictionary(t => t.name, t => t);
        var missing = new List<string>();
        float maxError = 0;
        int rendered = 0;
        foreach (var component in metadata.components)
        {
            if (!transforms.TryGetValue(component.export_name, out var t)) { missing.Add(component.export_name); continue; }
            var renderer = t.GetComponent<Renderer>();
            if (renderer == null) { missing.Add(component.export_name + " (renderer)"); continue; }
            rendered++;
            renderer.sharedMaterials = component.materials.Select(name => materials[name]).ToArray();
            renderer.shadowCastingMode = component.semantic_class == "floor_plank" || component.semantic_class == "window_glass" || component.semantic_class.StartsWith("exterior_")
                ? ShadowCastingMode.Off : ShadowCastingMode.On;
            renderer.receiveShadows = true;
            var expected = new Bounds((V(component.bounds_unity.min) + V(component.bounds_unity.max)) * .5f,
                V(component.bounds_unity.max) - V(component.bounds_unity.min));
            maxError = Mathf.Max(maxError, (renderer.bounds.center - expected.center).magnitude,
                (renderer.bounds.size - expected.size).magnitude);
            t.name = component.original_name;
        }
        if (missing.Count > 0) throw new InvalidDataException("Missing FBX components: " + string.Join(", ", missing.Take(20)));
        if (maxError > .03f) throw new InvalidDataException("FBX coordinate conversion mismatch: " + maxError + " m; inspect exported and imported bounds.");
        foreach (var instance in metadata.instances)
        {
            if (!transforms.TryGetValue(instance.export_group, out var t)) throw new InvalidDataException("Missing instance " + instance.export_group);
            t.name = instance.semantic_class + " | " + instance.instance_id;
            var segment = t.gameObject.AddComponent<SegmentedInstance>();
            segment.instanceId = instance.instance_id; segment.semanticClass = instance.semantic_class;
            segment.segmentationIndex = instance.index;
            segment.segmentationColor = new Color(instance.color_rgb[0]/255f, instance.color_rgb[1]/255f, instance.color_rgb[2]/255f);
            segment.sourceObjectNames = metadata.components.Where(c => c.instance_id == instance.instance_id).Select(c => c.original_name).ToArray();
        }
        SetupLighting();
        var cameraData = metadata.cameras.FirstOrDefault(c => c.active) ?? metadata.cameras[0];
        var cameraObject = new GameObject("Main Camera", typeof(Camera), typeof(AudioListener), typeof(RoomExplorer));
        cameraObject.tag = "MainCamera";
        cameraObject.transform.SetPositionAndRotation(V(cameraData.position_unity), Quaternion.LookRotation(V(cameraData.forward_unity), V(cameraData.up_unity)));
        var camera = cameraObject.GetComponent<Camera>();
        camera.fieldOfView = cameraData.fov_vertical_deg;
        camera.nearClipPlane = .03f; camera.farClipPlane = 60;
        camera.allowHDR = true; camera.allowMSAA = true;
        camera.clearFlags = CameraClearFlags.SolidColor; camera.backgroundColor = new Color(.43f, .49f, .54f);
        cameraObject.GetComponent<RoomExplorer>().segmentationShader = Shader.Find("Unlit/Color");
        ReconstructionPhysics.Configure(root);
        SetupRobotMount(root);
        string physicsReport = ReconstructionPhysics.ValidateSimulation();
        EditorSceneManager.MarkSceneDirty(scene);
        EditorSceneManager.SaveScene(scene, ScenePath);
        EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
        AssetDatabase.SaveAssets();
        var report = new ImportReport
        {
            success = true, scene = ScenePath, unity_version = Application.unityVersion, mujoco_version = "3.12.0",
            coordinate_mapping = metadata.coordinate_mapping, expected_instances = metadata.instance_count,
            imported_instances = root.GetComponentsInChildren<SegmentedInstance>().Length,
            expected_components = metadata.component_count, imported_components = rendered, max_bounds_error_m = maxError,
            missing_components = missing.ToArray(), physics_validation_json = physicsReport
        };
        File.WriteAllText("Validation/unity-import-validation.json", JsonUtility.ToJson(report, true));
        if (report.imported_instances != report.expected_instances || report.imported_components != report.expected_components)
            throw new InvalidDataException("Imported object totals differ from source");
        Debug.Log("RECONSTRUCTION_BUILD_OK " + JsonUtility.ToJson(report));
        if (SceneView.lastActiveSceneView != null) SceneView.lastActiveSceneView.AlignViewToObject(cameraObject.transform);
    }

    static Dictionary<string, Material> CreateMaterials(MaterialInfo[] entries)
    {
        var result = new Dictionary<string, Material>();
        for (int index=0; index<entries.Length; index++)
        {
            var data = entries[index];
            var path = $"Assets/Reconstruction/Materials/{index:D3}_{Safe(data.name)}.mat";
            var mat = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (mat == null) { mat = new Material(Shader.Find("Standard")); AssetDatabase.CreateAsset(mat, path); }
            mat.name = data.original_name;
            var color = C(data.base_color_linear).gamma;
            mat.color = color;
            mat.SetFloat("_Metallic", data.metallic);
            mat.SetFloat("_Glossiness", Mathf.Clamp01(1-data.roughness));
            if (!string.IsNullOrEmpty(data.texture_path))
            {
                var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(data.texture_path);
                if (tex == null) throw new FileNotFoundException(data.texture_path);
                mat.mainTexture = tex; mat.color = Color.white;
            }
            if (data.emission_strength > 0 && data.emission_color_linear != null)
            {
                mat.EnableKeyword("_EMISSION");
                mat.SetColor("_EmissionColor", C(data.emission_color_linear) * data.emission_strength);
                mat.globalIlluminationFlags = MaterialGlobalIlluminationFlags.RealtimeEmissive;
            }
            if (data.transmission > .5f)
            {
                color.a = .19f; mat.color = color;
                mat.SetFloat("_Mode", 3); mat.SetInt("_SrcBlend", (int)BlendMode.One);
                mat.SetInt("_DstBlend", (int)BlendMode.OneMinusSrcAlpha); mat.SetInt("_ZWrite", 0);
                mat.EnableKeyword("_ALPHAPREMULTIPLY_ON"); mat.renderQueue = (int)RenderQueue.Transparent;
            }
            EditorUtility.SetDirty(mat); result.Add(data.name,mat);
        }
        return result;
    }

    static void SetupRobotMount(GameObject visualRoot)
    {
        var reference = visualRoot.GetComponentsInChildren<SegmentedInstance>(true).Single(s => s.semanticClass == "robot_arm");
        foreach (var renderer in reference.GetComponentsInChildren<Renderer>(true)) renderer.enabled = false;
        var integration = new GameObject("Robot integration | import your own arm");
        integration.transform.SetParent(visualRoot.transform, false);
        integration.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
        reference.transform.SetParent(integration.transform, true);
        reference.gameObject.name = "Reconstructed arm reference | renderers hidden";
        var mount = new GameObject("Robot Mount Point | metres, Y up");
        mount.transform.SetParent(integration.transform, false);
        mount.transform.SetPositionAndRotation(new Vector3(-.74f, .799f, -.42f), Quaternion.Euler(0,8.594367f,0));
        var placeholder = new GameObject("Your Robot Model | parent imported model here");
        placeholder.transform.SetParent(mount.transform, false);
        Debug.Log("Robot mount ready at Unity (-0.74, 0.799, -0.42) metres; reconstructed arm hidden, no robot joints or actuators added.");
    }

    static void SetupLighting()
    {
        RenderSettings.ambientMode = AmbientMode.Trilight;
        RenderSettings.ambientSkyColor = new Color(.43f,.47f,.50f);
        RenderSettings.ambientEquatorColor = new Color(.39f,.38f,.34f);
        RenderSettings.ambientGroundColor = new Color(.23f,.20f,.16f);
        RenderSettings.ambientIntensity = 1;
        RenderSettings.reflectionIntensity = .45f;
        var sun = new GameObject("Window daylight", typeof(Light));
        sun.transform.rotation = Quaternion.Euler(45,-35,0);
        var key = sun.GetComponent<Light>();key.type = LightType.Directional;key.color = new Color(.89f,.94f,1);
        key.intensity = .85f;key.shadows = LightShadows.Soft;key.shadowStrength=.48f;key.shadowBias=.025f;key.shadowNormalBias=.015f;
        RenderSettings.sun = key;
        var fill = new GameObject("Soft room fill", typeof(Light));
        fill.transform.rotation=Quaternion.Euler(58,148,0);
        var light=fill.GetComponent<Light>();light.type=LightType.Directional;light.intensity=.45f;
        light.color=new Color(1,.87f,.72f);light.shadows=LightShadows.None;
    }

    public static void BuildFromCommandLine()
    {
        try { Build(); EditorApplication.Exit(0); }
        catch (Exception e) { Debug.LogException(e); EditorApplication.Exit(1); }
    }

    [MenuItem("Reconstruction/Capture Preview")]
    public static void CapturePreview()
    {
        EditorSceneManager.OpenScene(ScenePath);
        var camera = Camera.main;
        var target = new RenderTexture(1080,1440,24,RenderTextureFormat.ARGB32);
        target.antiAliasing = 4;
        camera.targetTexture = target; camera.Render(); RenderTexture.active=target;
        var image = new Texture2D(1080,1440,TextureFormat.RGB24,false);
        image.ReadPixels(new Rect(0,0,1080,1440),0,0);image.Apply();
        Directory.CreateDirectory("Validation");File.WriteAllBytes("Validation/unity-scene-preview.png",image.EncodeToPNG());
        camera.targetTexture=null;RenderTexture.active=null;UnityEngine.Object.DestroyImmediate(image);target.Release();UnityEngine.Object.DestroyImmediate(target);
        Debug.Log("UNITY_PREVIEW_SAVED");
    }

    public static void CaptureFromCommandLine()
    {
        try { CapturePreview(); EditorApplication.Exit(0); }
        catch (Exception e) { Debug.LogException(e); EditorApplication.Exit(1); }
    }
}
