using UnityEngine;

/// <summary>A physical item from the reference reconstruction, including its editable mesh parts.</summary>
[DisallowMultipleComponent]
public sealed class SegmentedInstance : MonoBehaviour
{
    public string instanceId;
    public string semanticClass;
    public int segmentationIndex;
    public Color segmentationColor = Color.white;
    public string[] sourceObjectNames;

    public Bounds WorldBounds()
    {
        var renderers = GetComponentsInChildren<Renderer>();
        if (renderers.Length == 0) return new Bounds(transform.position, Vector3.zero);
        var bounds = renderers[0].bounds;
        for (var i = 1; i < renderers.Length; i++) bounds.Encapsulate(renderers[i].bounds);
        return bounds;
    }
}
