using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>Builds, renders and validates the complete project from Unity's CLI.</summary>
[InitializeOnLoad]
public static class FinalizeReconstruction
{
    const string BatchKey = "Reconstruction.FinalizeBatch";
    static FinalizeReconstruction() { EditorApplication.update += CheckCompletion; }
    public static void RunBatch()
    {
        try
        {
            BuildReconstructedRoom.Build();
            BuildReconstructedRoom.CapturePreview();
            EditorSceneManager.SaveOpenScenes();
            ValidateReconstructionPlayMode.Run();
            SessionState.SetBool(BatchKey,true);
        }
        catch (Exception e)
        {
            Directory.CreateDirectory("Validation");
            File.WriteAllText("Validation/finalize-error.txt",e.ToString());
            Debug.LogException(e);
            EditorApplication.Exit(1);
        }
    }
    static void CheckCompletion()
    {
        if (!SessionState.GetBool(BatchKey,false) || EditorApplication.isPlayingOrWillChangePlaymode) return;
        const string reportPath = "Validation/unity-playmode-validation.json";
        if (!File.Exists(reportPath)) return;
        var report=JsonUtility.FromJson<ValidateReconstructionPlayMode.Report>(File.ReadAllText(reportPath));
        if (!report.completed || !report.returnedToEditMode) return;
        SessionState.SetBool(BatchKey,false);
        EditorApplication.Exit(report.passed ? 0 : 1);
    }
}
