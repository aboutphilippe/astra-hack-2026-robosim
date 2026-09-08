# Reconstructed Room + MuJoCo

Open this folder as a project in **Unity 6000.3.10f1**. The main scene is **Assets/Scenes/ReconstructedRoom.unity**, already included in Build Settings. Press Play to run the scene.

The original person-free Blender reconstruction is imported as 3,538 individually editable mesh components, grouped into 1,025 physical instances. The imported meshes match the source bounds to within 0.002 mm. Procedural Blender materials have been converted to 112 Unity materials with 35 portable albedo textures. Unity lighting is an approximation of the Blender render.

## MuJoCo setup

The official `org.mujoco` Unity integration and matching native library are embedded locally at **Packages/org.mujoco**, pinned to **3.12.0**. The native library supports this Mac's ARM64 Editor and macOS standalone applications (also includes x86_64). This project needs no global MuJoCo installation. Native binaries for Windows or Linux are not included.

The exact upstream provenance, release checksum verification and license files are included in the package. **PATCHES.md** records one necessary project-local C# VFS structure layout fix: the upstream generated empty structure is corrected to match the native pointer-sized structure. The signed native binary is unchanged.

Physics uses native MuJoCo through the supplied Unity components:

- 32 chess pieces each have an `MjBody`, `MjFreeJoint` and weighted collision proxies.
- 104 total geoms include the floor, tables, chessboard and selected furniture/room boundaries.
- Physics runs at a 0.002 second timestep with gravity along Unity's negative Y axis.
- The reconstructed robot arm is retained as a **hidden reference**. No robot joints or actuators are added; the project is prepared for your own arm model.
- Collision geometry is intentionally simpler than the render meshes; fabrics and plant leaves are visual geometry.

The editable generated MJCF is **Assets/MuJoCo/reconstructed_physics.xml**. Unity generates its runtime MuJoCo model from the scene components; editing this exported XML does not automatically update the Unity scene. Use the plug-in's **Assets > Import MuJoCo Scene** command to import MJCF separately.

## Import your robot arm

In the hierarchy, expand **Reconstructed room > Robot integration | import your own arm > Robot Mount Point | metres, Y up > Your Robot Model**. Parent your imported model under that final object, using metre units and a local base origin at zero. The mount is positioned at Unity **(-0.74, 0.799, -0.42)** on the tabletop, with the original arm's yaw. Change the mount transform if your robot needs a different position or orientation.

For an MJCF robot, use **Assets > Import MuJoCo Scene**, then place its robot body hierarchy under the mount; retain the room's existing global MuJoCo settings. A visual FBX/mesh alone does not define robot dynamics: its bodies, joints, collision shapes and actuators need MuJoCo components or an MJCF model. The hidden reference can be viewed again by enabling its MeshRenderers.

The build command regenerates the room, so save your robot in its own prefab before rebuilding.

## Inspection controls

| Control | Action |
|---|---|
| Right mouse + WASD | Fly through the room |
| Q / E while right mouse is held | Move down / up |
| Shift | Faster movement |
| F | Return to the original camera |
| Tab | Toggle instance segmentation colors |
| Click an object | Show its class and instance ID |
| Space | Pause / resume simulation |
| R | Reload the scene and reset the simulation |

Each physical item has a `SegmentedInstance` component with its original instance ID, class, color and source object names. All mesh parts remain separate. The source segmentation manifest and mesh/material/camera sidecar are in **Assets/Reconstruction/Source**.

## Rebuild and validation

Use **Reconstruction > Build Reconstructed Room** to rebuild the scene from the FBX and sidecar. This replaces the current generated scene. Use **Reconstruction > Capture Preview** to render a portrait PNG into `Validation`.

With this project closed in the Editor, the same build is available from the CLI:

```sh
/Applications/Unity/Hub/Editor/6000.3.10f1/Unity.app/Contents/MacOS/Unity \
  -batchmode -nographics -projectPath "$PWD" \
  -executeMethod BuildReconstructedRoom.BuildFromCommandLine \
  -logFile Logs/rebuild.log
```

`Validation/unity-import-validation.json` records the complete object import and a real 1,000-step native MuJoCo simulation. **Reconstruction > Validate Play Mode** checks runtime initialization and the segmentation toggle, then returns to Edit mode; its report is `Validation/unity-playmode-validation.json`. `Validation/unity-scene-preview.png` is rendered by Unity. The Blender-to-FBX exporter is in the parent folder at `scripts/export_unity.py`.

Official references: [Unity integration](https://mujoco.readthedocs.io/en/latest/unity.html), [MuJoCo 3.12.0 release](https://github.com/google-deepmind/mujoco/releases/tag/3.12.0).
