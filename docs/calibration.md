# Camera-led calibration

Run `uv sync --extra camera`, enumerate with `uv run nono-discover --sdk`, and enroll the Gemini SDK serial in a local config. Set `NONO_CONFIG=config/local.json` for the API. Use the console calibration pane or the API docs to capture an aligned snapshot. The SDK’s colour/depth alignment is required: resizing raw depth to RGB resolution is not accepted as calibration.

If discovery sees the device but reports `uvc_open ... Return Code: -3`, the SDK could not acquire access. Check macOS Camera permission for the process host and whether another application already owns the camera. Firmware cannot be verified until device access succeeds. Discovery preserves the serial and the error instead of claiming the camera is streaming. The SDK context must outlive device handles; the adapter retains it throughout discovery and capture.

## Board lock

For initial calibration, clear hands and preferably pieces from the board. Keep the playing surface in view. Select its four outer corners in the order **a1, h1, h8, a8**; the actual pixel positions may have any rotation. Select the grid edge, not the board’s decorative rim. Submit `/api/calibration/measure` with `corners_px`.

The measurement fits a dominant plane to valid interior depth samples with RANSAC, rejects poor coverage, intersects labeled corner rays with this plane, and compares all edge lengths and angles. Square size is measured width divided by eight. No failed measurement falls back to 38.1 or 36 mm. A raised border can bias calibration if selected instead of the playing grid; inspect the saved corner positions and plane residuals.

Per-square heights use points above the board plane, with depth sample counts and a noise floor. They measure visible surfaces; they do not recover hidden geometry, grip diameters, piece mass, or grasp friction. Shiny/dark surfaces and occlusion may have missing depth, represented as null. Capture occupied-board depth again when evaluating real piece profiles.

Camera optical coordinates are +x right, +y down, +z forward. A proper board basis is derived from the labeled edges and their cross product. The surface-facing normal is recorded separately so piece heights stay positive when the image ordering reverses the normal. Never infer physical handedness from a displayed diagram.

## Robot-base registration

Choose three or more well-separated, noncollinear rigid base landmarks whose model coordinates are known. Their robot coordinates come from the robot CAD/model, not a ruler estimate of where the arm happens to be. Pair each with a pixel in the same depth snapshot. This provides a rigid camera-to-robot transform and residual report. A printed fiducial with a fixed, known base mount is a future way to automate this correspondence step.

Submit `/api/calibration/robot-rgbd` with `landmarks: [{pixel: [u,v], robot_m: [x,y,z]}, ...]`, or call the Codex tool `register_robot_base`. This composes camera-to-robot with the measured board-to-camera transform, rejects tilted/inverted geometry, and rebuilds the scene in the robot base frame. It resets the game. The discarded-piece area is still a sample layout until separately measured.

Alternatively, `/api/calibration/robot` takes measured correspondence pairs:

```json
{"anchors": [
  {"board_m": [0, 0, 0], "robot_m": [0.10, 0.10, 0.02]},
  {"board_m": [0.10, 0, 0], "robot_m": [0.20, 0.10, 0.02]},
  {"board_m": [0, 0.10, 0], "robot_m": [0.10, 0.20, 0.02]}
]}
```

These numbers are a **synthetic example**, not `nono` calibration. Board coordinates are local to the a1 playing-grid corner. Robot coordinates are in the actual calibrated robot base frame. A camera homography determines pixel-to-square mapping only; it cannot determine metric robot pose. A three-point rigid fit can have deceptively low residual, so use additional independent landmarks to verify it.

The current scene supports a horizontal board and yaw. A tilted measured board must be rejected for scene alignment until arbitrary board transforms are implemented. Saving a fit does not enable hardware execution.

## Validate the workspace

Check a1, h1, a8, h8 and middle-square overlays first. Then test IK at every pickup and lift height, and at each intended capture slot. A nominal reach specification is not the vertical-grasp workspace: the wrist and gripper consume reach when pointed down. Move the board/base and recapture if required; never change the measured square scale to make IK pass.

Finally compare measured joint positions to the simulated links, calibrate the tool center and jaw opening against the actual pieces, and check full paths for collisions. Current previews interpolate joint angles and attach piece visuals to the TCP. They do not establish contact, torque, or path safety.
