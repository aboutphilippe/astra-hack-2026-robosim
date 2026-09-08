using UnityEditor;

public sealed class ReconstructionModelImporter : AssetPostprocessor
{
    private void OnPreprocessModel()
    {
        if (!assetPath.StartsWith("Assets/Reconstruction/Source/") || !assetPath.EndsWith(".fbx")) return;
        var importer = (ModelImporter)assetImporter;
        importer.importCameras = false;
        importer.importLights = false;
        importer.importAnimation = false;
        importer.addCollider = false;
        importer.preserveHierarchy = true;
        importer.isReadable = true;
        importer.meshCompression = ModelImporterMeshCompression.Off;
        importer.materialImportMode = ModelImporterMaterialImportMode.None;
        importer.importNormals = ModelImporterNormals.Import;
        importer.importTangents = ModelImporterTangents.CalculateMikk;
    }
}
