using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>Small inspection controls for the reconstructed scene and its instance segmentation.</summary>
public sealed class RoomExplorer : MonoBehaviour
{
    public float moveSpeed = 1.7f;
    public float lookSensitivity = 2f;
    public Shader segmentationShader;
    private Vector3 initialPosition;
    private Quaternion initialRotation;
    private bool segmented;
    private bool paused;
    private SegmentedInstance[] instances;
    private readonly Dictionary<Renderer, Material[]> originalMaterials = new Dictionary<Renderer, Material[]>();
    private readonly List<Material> maskMaterials = new List<Material>();
    private string selection = "Click an object to inspect its segmentation ID";

    private void Start()
    {
        initialPosition = transform.position;
        initialRotation = transform.rotation;
        instances = FindObjectsByType<SegmentedInstance>(FindObjectsSortMode.None);
    }

    private void Update()
    {
        if (Input.GetKeyDown(KeyCode.Tab)) SetSegmentation(!segmented);
        if (Input.GetKeyDown(KeyCode.Space)) { paused = !paused; Time.timeScale = paused ? 0 : 1; }
        if (Input.GetKeyDown(KeyCode.F)) { transform.SetPositionAndRotation(initialPosition, initialRotation); }
        if (Input.GetKeyDown(KeyCode.R)) { Time.timeScale = 1; SceneManager.LoadScene(SceneManager.GetActiveScene().buildIndex); }
        if (Input.GetMouseButton(1))
        {
            float yaw = Input.GetAxis("Mouse X") * lookSensitivity;
            float pitch = -Input.GetAxis("Mouse Y") * lookSensitivity;
            transform.Rotate(Vector3.up, yaw, Space.World);
            transform.Rotate(Vector3.right, pitch, Space.Self);
            var direction = new Vector3(Input.GetAxisRaw("Horizontal"),
                (Input.GetKey(KeyCode.E) ? 1 : 0) - (Input.GetKey(KeyCode.Q) ? 1 : 0), Input.GetAxisRaw("Vertical"));
            transform.position += transform.TransformDirection(direction) * (moveSpeed * Time.unscaledDeltaTime * (Input.GetKey(KeyCode.LeftShift) ? 3 : 1));
        }
        if (Input.GetMouseButtonDown(0) && Input.mousePosition.y < Screen.height - 96)
        {
            var ray = GetComponent<Camera>().ScreenPointToRay(Input.mousePosition);
            SegmentedInstance nearest = null; float distance = float.MaxValue;
            foreach (var instance in instances)
            {
                if (instance == null) continue;
                // Per-component bounds avoid selecting the empty center of a chair or desk.
                foreach (var renderer in instance.GetComponentsInChildren<Renderer>())
                    if (renderer.bounds.IntersectRay(ray, out float hit) && hit < distance)
                    { distance = hit; nearest = instance; }
            }
            if (nearest != null) selection = $"{nearest.semanticClass}  /  {nearest.instanceId}  /  ID {nearest.segmentationIndex}";
        }
    }

    public void SetSegmentation(bool enabled)
    {
        segmented = enabled;
        if (instances == null) instances = FindObjectsByType<SegmentedInstance>(FindObjectsSortMode.None);
        if (enabled)
        {
            foreach (var instance in instances)
            {
                var mat = new Material(segmentationShader != null ? segmentationShader : Shader.Find("Unlit/Color"));
                mat.color = instance.segmentationColor;
                maskMaterials.Add(mat);
                foreach (var renderer in instance.GetComponentsInChildren<Renderer>())
                {
                    if (!originalMaterials.ContainsKey(renderer)) originalMaterials[renderer] = renderer.sharedMaterials;
                    var replacements = new Material[renderer.sharedMaterials.Length];
                    for (var i = 0; i < replacements.Length; i++) replacements[i] = mat;
                    renderer.sharedMaterials = replacements;
                }
            }
        }
        else
        {
            foreach (var pair in originalMaterials) if (pair.Key != null) pair.Key.sharedMaterials = pair.Value;
            foreach (var mat in maskMaterials) Destroy(mat);
            originalMaterials.Clear(); maskMaterials.Clear();
        }
    }

    private void OnGUI()
    {
        GUI.Box(new Rect(14, 14, Mathf.Min(Screen.width - 28, 710), 78), GUIContent.none);
        GUI.Label(new Rect(27, 22, 685, 22), $"RECONSTRUCTED ROOM  ·  MuJoCo 3.12  ·  {(paused ? "PAUSED" : "SIMULATING")}");
        GUI.Label(new Rect(27, 44, 685, 20), "Right mouse + WASD/QE: fly  ·  F: camera  ·  Tab: segments  ·  Space: pause  ·  R: reset");
        GUI.Label(new Rect(27, 65, 685, 20), selection);
    }

    private void OnDestroy() { Time.timeScale = 1; foreach (var mat in maskMaterials) if (mat != null) Destroy(mat); }
}
