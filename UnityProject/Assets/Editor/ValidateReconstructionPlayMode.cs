using System;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using Mujoco;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

/// <summary>Validates the actual Editor Play lifecycle, including domain reload.</summary>
[InitializeOnLoad]
public static class ValidateReconstructionPlayMode
{
    const string Prefix = "Reconstruction.PlayValidation.";
    const string ScenePath = "Assets/Scenes/ReconstructedRoom.unity";
    const string ReportPath = "Validation/unity-playmode-validation.json";
    const double RequiredSimulatedSeconds = 0.5;
    const double TimeoutSeconds = 30;
    static Report currentReport;

    [Serializable]
    public sealed class Report
    {
        public bool completed;
        public bool passed;
        public bool returnedToEditMode;
        public string status;
        public string startedUtc;
        public string completedUtc;
        public string scene = ScenePath;
        public string unityVersion;
        public string nativeVersion;
        public int instanceCount;
        public int uniqueInstanceIds;
        public int meshRendererCount;
        public int freeJointCount;
        public int nativeBodies;
        public int nativeGeoms;
        public int qpos;
        public int degreesOfFreedom;
        public int observedEditorUpdates;
        public double firstNativeTime = -1;
        public double lastNativeTime;
        public double observedSimulatedSeconds;
        public double elapsedWallSeconds;
        public bool finiteState;
        public bool segmentationTogglePassed;
        public bool originalMaterialsRestored;
        public string error;
    }

    [Serializable]
    sealed class SavedScene { public string path; public bool isLoaded; public bool isActive; }
    [Serializable]
    sealed class SavedSetup { public SavedScene[] scenes; }

    static ValidateReconstructionPlayMode()
    {
        EditorApplication.playModeStateChanged += OnPlayModeChanged;
        EditorApplication.update += Update;
        Application.logMessageReceived += OnLog;
    }

    [MenuItem("Reconstruction/Validate Play Mode")]
    public static void Run()
    {
        if (EditorApplication.isPlayingOrWillChangePlaymode || SessionState.GetBool(Prefix + "active", false))
            throw new InvalidOperationException("Stop the current Play session before starting validation.");
        for (var i = 0; i < SceneManager.sceneCount; ++i)
        {
            var scene = SceneManager.GetSceneAt(i);
            if (scene.isDirty || string.IsNullOrEmpty(scene.path))
                throw new InvalidOperationException("Save the open scene before validation so its authored state is retained.");
        }
        if (!File.Exists(ScenePath)) throw new FileNotFoundException("The reconstructed scene is not saved.", ScenePath);

        var setup = new SavedSetup
        {
            scenes = EditorSceneManager.GetSceneManagerSetup().Select(scene => new SavedScene
                { path = scene.path, isLoaded = scene.isLoaded, isActive = scene.isActive }).ToArray()
        };
        SessionState.SetString(Prefix + "setup", JsonUtility.ToJson(setup));
        SessionState.SetBool(Prefix + "restore", false);
        SessionState.SetString(Prefix + "runtimeError", "");
        currentReport = new Report
        {
            status = "running",
            startedUtc = DateTime.UtcNow.ToString("O"),
            unityVersion = Application.unityVersion,
            finiteState = true
        };
        StoreReport();
        try
        {
            if (SceneManager.sceneCount != 1 || SceneManager.GetActiveScene().path != ScenePath)
                EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            SessionState.SetBool(Prefix + "active", true);
            EditorApplication.isPlaying = true;
            Debug.Log("Reconstruction Play validation started; the editor will stop Play and restore the saved scene automatically.");
        }
        catch (Exception exception) { Finish(false, exception.ToString()); }
    }

    [MenuItem("Reconstruction/Validate Play Mode", true)]
    static bool CanRun() => !EditorApplication.isPlayingOrWillChangePlaymode &&
                            !SessionState.GetBool(Prefix + "active", false);

    static void OnPlayModeChanged(PlayModeStateChange state)
    {
        if (state != PlayModeStateChange.EnteredEditMode) return;
        if (SessionState.GetBool(Prefix + "active", false))
            Finish(false, "Play mode exited before native simulation validation completed.");
        if (SessionState.GetBool(Prefix + "restore", false)) EditorApplication.delayCall += RestoreSceneSetup;
    }

    static void OnLog(string message, string stackTrace, LogType type)
    {
        if (!SessionState.GetBool(Prefix + "active", false) ||
            (type != LogType.Error && type != LogType.Exception && type != LogType.Assert)) return;
        if (string.IsNullOrEmpty(SessionState.GetString(Prefix + "runtimeError", "")))
            SessionState.SetString(Prefix + "runtimeError", message + "\n" + stackTrace);
    }

    static unsafe void Update()
    {
        if (!SessionState.GetBool(Prefix + "active", false))
        {
            if (SessionState.GetBool(Prefix + "restore", false) && !EditorApplication.isPlayingOrWillChangePlaymode)
                RestoreSceneSetup();
            return;
        }
        try
        {
            LoadReport();
            currentReport.elapsedWallSeconds = (DateTime.UtcNow - DateTime.Parse(currentReport.startedUtc,
                null, System.Globalization.DateTimeStyles.RoundtripKind)).TotalSeconds;
            var runtimeError = SessionState.GetString(Prefix + "runtimeError", "");
            if (!string.IsNullOrEmpty(runtimeError)) { Finish(false, runtimeError); return; }
            if (currentReport.elapsedWallSeconds > TimeoutSeconds)
            { Finish(false, "Timed out waiting for 0.5 seconds of native MuJoCo simulation in Play mode."); return; }
            if (!EditorApplication.isPlaying || EditorApplication.isCompiling || EditorApplication.isPaused) return;

            // Observe the singleton created by the plugin's actual runtime
            // lifecycle; do not create a replacement or call CreateScene here.
            var scene = Object.FindFirstObjectByType<MjScene>();
            if (scene == null || scene.Model == null || scene.Data == null) return;
            if (currentReport.firstNativeTime < 0)
            {
                CheckMetadata();
                currentReport.nativeVersion = Marshal.PtrToStringAnsi(MujocoLib.mj_versionString());
                currentReport.nativeBodies = checked((int)scene.Model->nbody);
                currentReport.nativeGeoms = checked((int)scene.Model->ngeom);
                currentReport.qpos = checked((int)scene.Model->nq);
                currentReport.degreesOfFreedom = checked((int)scene.Model->nv);
                if (currentReport.nativeBodies != 33 || currentReport.qpos != 224 || currentReport.degreesOfFreedom != 192)
                    throw new InvalidOperationException("Native runtime does not contain the expected 32 free chess bodies.");
                currentReport.firstNativeTime = scene.Data->time;
                CheckSegmentationToggle();
            }

            RequireFinite(scene.Data->time, "simulation time");
            for (var i = 0; i < currentReport.qpos; ++i) RequireFinite(scene.Data->qpos[i], "qpos");
            for (var i = 0; i < currentReport.degreesOfFreedom; ++i)
            {
                RequireFinite(scene.Data->qvel[i], "qvel");
                RequireFinite(scene.Data->qacc[i], "qacc");
            }
            currentReport.lastNativeTime = scene.Data->time;
            currentReport.observedSimulatedSeconds = currentReport.lastNativeTime - currentReport.firstNativeTime;
            currentReport.observedEditorUpdates++;
            // SessionState survives the domain reload that entering/exiting Play
            // can cause, so no external automation or pending CLI is necessary.
            SessionState.SetString(Prefix + "report", JsonUtility.ToJson(currentReport));
            if (currentReport.observedSimulatedSeconds >= RequiredSimulatedSeconds)
            {
                CheckMetadata();
                Finish(true, "");
            }
        }
        catch (Exception exception) { Finish(false, exception.ToString()); }
    }

    static SegmentedInstance[] CheckMetadata()
    {
        var instances = Object.FindObjectsByType<SegmentedInstance>(FindObjectsInactive.Include, FindObjectsSortMode.None);
        currentReport.instanceCount = instances.Length;
        currentReport.uniqueInstanceIds = instances.Select(instance => instance.instanceId).Distinct().Count();
        currentReport.meshRendererCount = instances.SelectMany(instance => instance.GetComponentsInChildren<MeshRenderer>(true)).Distinct().Count();
        currentReport.freeJointCount = Object.FindObjectsByType<MjFreeJoint>(FindObjectsSortMode.None).Length;
        if (currentReport.instanceCount != 1025 || currentReport.uniqueInstanceIds != 1025 ||
            currentReport.meshRendererCount != 3538 || currentReport.freeJointCount != 32)
            throw new InvalidOperationException("Runtime segmentation or MuJoCo joint counts differ from the reconstructed scene.");
        return instances;
    }

    static void CheckSegmentationToggle()
    {
        var explorer = Object.FindFirstObjectByType<RoomExplorer>();
        if (explorer == null) throw new InvalidOperationException("RoomExplorer controls are missing.");
        var instances = CheckMetadata();
        var renderers = instances.SelectMany(instance => instance.GetComponentsInChildren<MeshRenderer>(true)).Distinct().ToArray();
        var originalMaterials = renderers.ToDictionary(renderer => renderer, renderer => renderer.sharedMaterials);
        try
        {
            explorer.SetSegmentation(true);
            CheckMetadata();
            foreach (var instance in instances)
                foreach (var renderer in instance.GetComponentsInChildren<MeshRenderer>(true))
                    if (renderer.sharedMaterials.Any(material => material == null || material.color != instance.segmentationColor))
                        throw new InvalidOperationException("Segmentation colors were not applied to all mesh parts.");
        }
        finally { explorer.SetSegmentation(false); }
        currentReport.originalMaterialsRestored = originalMaterials.All(pair => pair.Key.sharedMaterials.SequenceEqual(pair.Value));
        if (!currentReport.originalMaterialsRestored)
            throw new InvalidOperationException("Disabling segmentation did not restore the original materials.");
        CheckMetadata();
        currentReport.segmentationTogglePassed = true;
    }

    static void RequireFinite(double value, string field)
    {
        if (!double.IsNaN(value) && !double.IsInfinity(value)) return;
        currentReport.finiteState = false;
        throw new InvalidOperationException("Native MuJoCo runtime contains nonfinite " + field + ".");
    }

    static void Finish(bool passed, string error)
    {
        LoadReport();
        SessionState.SetBool(Prefix + "active", false);
        SessionState.SetBool(Prefix + "restore", true);
        currentReport.completed = true;
        currentReport.passed = passed;
        currentReport.status = passed ? "passed" : "failed";
        currentReport.completedUtc = DateTime.UtcNow.ToString("O");
        currentReport.error = error;
        StoreReport();
        EditorApplication.isPlaying = false;
        if (passed) Debug.Log("RECONSTRUCTION_PLAYMODE_OK " + JsonUtility.ToJson(currentReport));
        else Debug.LogError("RECONSTRUCTION_PLAYMODE_FAILED " + error);
    }

    static void RestoreSceneSetup()
    {
        if (EditorApplication.isPlayingOrWillChangePlaymode || !SessionState.GetBool(Prefix + "restore", false)) return;
        SessionState.SetBool(Prefix + "restore", false);
        LoadReport();
        try
        {
            var setup = JsonUtility.FromJson<SavedSetup>(SessionState.GetString(Prefix + "setup", "{}"));
            var current = EditorSceneManager.GetSceneManagerSetup();
            var matches = setup.scenes != null && current.Length == setup.scenes.Length &&
                current.Select((scene, i) => scene.path == setup.scenes[i].path &&
                    scene.isActive == setup.scenes[i].isActive && scene.isLoaded == setup.scenes[i].isLoaded).All(match => match);
            if (!matches && setup.scenes != null && setup.scenes.Length > 0)
                EditorSceneManager.RestoreSceneManagerSetup(setup.scenes.Select(scene => new SceneSetup
                    { path = scene.path, isLoaded = scene.isLoaded, isActive = scene.isActive }).ToArray());
            currentReport.returnedToEditMode = true;
        }
        catch (Exception exception)
        {
            currentReport.passed = false;
            currentReport.status = "failed";
            currentReport.error += "\nRestoring saved scene setup failed: " + exception;
            Debug.LogException(exception);
        }
        StoreReport();
    }

    static void LoadReport()
    {
        if (currentReport == null)
            currentReport = JsonUtility.FromJson<Report>(SessionState.GetString(Prefix + "report", "{}"));
    }

    static void StoreReport()
    {
        var json = JsonUtility.ToJson(currentReport, true);
        SessionState.SetString(Prefix + "report", json);
        var absolutePath = Path.Combine(Directory.GetParent(Application.dataPath).FullName, ReportPath);
        Directory.CreateDirectory(Path.GetDirectoryName(absolutePath));
        File.WriteAllText(absolutePath, json);
    }
}
