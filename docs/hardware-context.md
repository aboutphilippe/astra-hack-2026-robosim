# Hardware spec — SO-101 + cameras (nono)

> **Archived user-supplied context from a previous project.** The supplied pack below is preserved as received. Its paths, relative links, implementation claims, and numerical specifications refer to that prior project; they are not implemented or verified by their inclusion here. Use this repository's [README](../README.md), [current configuration](../config/nono.json), and current measured calibration outputs as the authority for this implementation. Values explicitly marked as sample geometry remain unmeasured.

Context pack for discovering this desk’s hardware and scaffolding a
**real2sim2real** pipeline (test / calibration → twin → chess cell).

Machine roster (frozen IDs): [`fixtures/hardware/nono_cameras_v0.1.json`](../fixtures/hardware/nono_cameras_v0.1.json).

Drivers: [`src/chessbench/hardware/`](../src/chessbench/hardware/).

---

## 1. SO-101 arm (`nono`)

### What it is

Open-source **6-DOF** follower (5 arm joints + gripper) from
[TheRobotStudio / Hugging Face LeRobot](https://github.com/TheRobotStudio/SO-ARM100)
— successor to SO-100 with a revised wrist. Local robot id: **`nono`**.

| Spec | Value (this stack) |
|------|--------------------|
| DOF | 6: `shoulder_pan`, `shoulder_lift`, `elbow_flex`, `wrist_flex`, `wrist_roll`, `gripper` |
| Actuators | Feetech **STS3215** bus servos (ids 1–6) |
| Control | `lerobot[feetech]` via `src/chessbench/hardware/follower_bus.py` |
| Norm modes | joints → degrees; gripper → `RANGE_0_100` |
| Typical reach / payload | ~500 mm / ~500 g (community; pose-dependent) |
| Analytic FK lengths | L1=L2=0.12 m, L3=0.08 m (`geometry/kinematics.py`) |
| Follower serial (nono) | `/dev/tty.usbmodem5B415320131` |
| Leader serial (nono) | `/dev/tty.usbmodem5B415320801` |
| LeRobot calibration | `~/.cache/huggingface/lerobot/calibration/robots/so_follower/nono.json` |

### URDF — where it comes from

| Layer | Path / source |
|-------|----------------|
| **Runtime URDF** (twin / FK) | `assets/so-101-urdf/urdf/so101_new_calib.urdf` (mirrored under `web/so-101-urdf/`) |
| **Package README origin** | [TheRobotStudio/SO-ARM100 `Simulation/SO101`](https://github.com/TheRobotStudio/SO-ARM100/tree/main/Simulation/SO101) |
| **CAD generation** | URDF header: `Generated using onshape-to-robot` from [Onshape `7715cc28…`](https://cad.onshape.com/documents/7715cc284bb430fe6dab4ffd/w/4fd0791b683777b02f8d975a/e/826c553ede3b7592eb9ca800) |
| **MJCF / STL lineage** | [`assets/so101/PROVENANCE.md`](../assets/so101/PROVENANCE.md) ← [johnsutor/so101-nexus](https://github.com/johnsutor/so101-nexus) `SO101/` ← SO-ARM100 + MuJoCo Menagerie `robotstudio_so101` |
| **Wrist cam in URDF** | Extra fixed links from **livekit-examples/so-frame** (Hex-Nut MF mount) |

Wrist optical frame (parented to `gripper`, rolls with wrist_roll, independent of jaw):

- Mount joint: `wrist_camera_mount_joint` → mesh `SO-ARM101_camera_wrist_mount.stl`
- Optical: `frame_wrist_camera` / `frame_wrist_camera_joint`
- Origin (optical): `xyz="0.0025 0.0675 -0.0062"` `rpy="3.141593 1.136305 -1.570797"` (SAPIEN +X view; π roll for upside-down mount)

**Feetech ↔ URDF:** URDF zero ≈ mid-travel. Mapping:

- `fixtures/robot/urdf_mapping.json` (`mapping: "lelab"`, `invert_rotation: true`)
- `fixtures/robot/joint_span_nono.json` via `geometry/urdf_map.py` / `joint_span_calib.py`

---

## 2. Wrist camera (gripper RGB)

### What this desk uses

OpenCV / UVC **“icspring camera”** — no depth. Matched by name / `unique_id` so Continuity / Orbbec never steal the index.

| Spec | Value |
|------|--------|
| Role | gripper / close-up grasp check |
| Backend | OpenCV + AVFoundation (macOS) |
| Device name match | `icspring` |
| Unique ID (nono) | `0x112000029930858` |
| Config capture | **1920×1080** |
| Index | resolve by UID/name — do **not** hardcode |
| Mount | SO-101 Hex-Nut / 32×32 UVC class (URDF mount STL above) |
| Focus | **Manual** lens twist (SO-ARM100 docs) |
| Firmware | **None to manage** — generic UVC; no OTA in-repo |

Community SO-101 wrist baseline: 32×32 mm UVC, ≥720p@30; LeRobot often runs 640×480@30. This desk prefers native 1080p for wrist snaps.

**Discovery rules (encoded in `cameras.resolve_wrist_index`):**

- Prefer `unique_id` / `"icspring"`
- Reject: Orbbec, Gemini, OBS, FaceTime, Continuity, iPhone
- Grasp check: `perception/wrist_check.py`; `bench move --wrist-confirm`

---

## 3. Gemini top-view RGB-D (Orbbec Gemini 336)

### What this desk uses

Single overhead / angled **Orbbec Gemini 336** for board RGB + depth + point cloud.
On this Mac there is **no safe OpenCV RGB node** for Gemini — SDK only.

| Spec | Official | ChessBench usage |
|------|----------|------------------|
| Model | Gemini 336 (G40155-180), Gemini 330 series | “Orbbec Gemini 336 (TOP via SDK)” |
| Unique ID (nono) | — | `0x22000002bc50803` |
| Depth tech | Active stereo IR, **850 nm**, IR-pass | — |
| Baseline | 50 mm | — |
| Depth | up to **1280×800@30**, FOV **H90°×V65°**, range 0.10–20 m (opt. 0.26–3 m) | Prefer **640×480 Y16@30**; native often **848×480** ([ar_aim](ar_aim.md)) |
| RGB | up to **1920×1080@30**, FOV **H86°×V55°** | Prefer **640×480 RGB@30** via SDK |
| I/O | USB 3.0 Type-C | Prefer USB3 link (`UsbLinkSpeed=5000000000`); Camera permission; often `sudo -E` |
| Outputs | Depth, IR, RGB, point cloud, IMU | `AlignFilter` D2C + `PointCloudFilter` (RGB points) |
| SDK | Orbbec SDK v2 | **`pyorbbecsdk2>=2.1`** (`pip install -e ".[real]"`) |
| **Firmware** | Min 1.2.20; **recommended 1.8.10** ([OrbbecSDK_v2](https://github.com/orbbec/orbbecsdk_v2)) | Repo gate: **1.8.10** via `scripts/orbbec_fw_upgrade.py` / `.sh` — image `Gemini330_Release_1.8.10.bin` under `.orbbec-upgrade/` |

**Critical macOS rule:** AVFoundation often lists only **“Orbbec Gemini 336 Depth Camera”**. Never open that with OpenCV (green noise + steals SDK). Use `OrbbecRGBDSession` / Track / `bench aim --live-depth`.

**Mount:** opposite the arm, ~30–45° down ([ar_aim](ar_aim.md)). Image convention: **a1 ≈ top-left** of Gemini frame.

**Board metric prior** (hardware fixture): squares **38.1 mm**, border **25.4 mm**, frame height **25.4 mm**.

Product page: [Orbbec Gemini 336](https://www.orbbec.com/products/stereo-vision-camera/gemini-336/).

---

## 4. Discovery → foundation tests

Bootstrap checklist for hardware discovery + calib before chess ML.

### A. Enumerate

1. **Serial** — match `follower_port` / `leader_port` in `nono_cameras_v0.1.json`; open Feetech bus; read Present_Position for all 6 STS3215.
2. **Wrist** — `list_avfoundation_cameras()` → assert icspring UID; grab one 1920×1080 frame.
3. **Orbbec** — `pyorbbecsdk.Context().query_devices()` → name, SN, **firmware**; refuse (or upgrade) if FW ≠ 1.8.10.
4. **USB3** — confirm high-speed link when streaming RGBD.
5. **Never** OpenCV-open the Gemini depth node.

### B. Calibration / real2sim anchors

| Stage | Entry points |
|-------|----------------|
| Board RGB-D lock | `bench aim` / [ar_aim](ar_aim.md) → `artifacts/calib_latest` |
| Joint span ↔ URDF | `geometry/joint_span_calib.py` → `fixtures/robot/joint_span_nono.json` |
| Feetech ↔ mesh | `fixtures/robot/urdf_mapping.json`, twin via `bench twin` |
| Desk layout | `fixtures/robot/board_origin_nono.json`, `mesh_offset_nono.json`, `camera_T_robot_nono.json` |
| Teach grid / pose | [teach_squares](teach_squares.md), [pose_real_runbook](pose_real_runbook.md) |
| Wrist grasp gate | `perception/wrist_check.py`, `bench move --wrist-confirm` |
| Depth / PC quality | `OrbbecRGBDSession` + `experiments/lingbot_depth_ab/` |

### C. Sim twin assets

- **URDF + meshes:** `assets/so-101-urdf/`
- **MuJoCo / visual:** `assets/so101/` (Apache-2.0 vendored)
- **Wrist optical TF:** `frame_wrist_camera` parented to `gripper`
- **Gemini in scene:** `scene_drawing.xml` (see PROVENANCE) — align extrinsics to real `camera_T_*` fixtures

### D. Frozen IDs

Treat `fixtures/hardware/nono_cameras_v0.1.json` as the device roster. Discovery should **verify** UIDs/ports, not invent new OpenCV indices every boot.

---

## 5. Gaps / caveats

- **Wrist firmware:** N/A — verify focus + resolution only.
- **Gemini firmware:** treat **1.8.10** as a hard gate for AlignFilter / PointCloudFilter paths.
- **Square size:** hardware fixture says **38.1 mm**; `fixtures/scene/nono.json` currently has **36 mm** — resolve before metric sim.
- **Real deps:** `pip install -e ".[real]"` → opencv, `pyorbbecsdk2>=2.1`, `lerobot[feetech]>=0.6`.

---

## Related docs

- [Aim / AR calibration](ar_aim.md)
- [Pose real runbook](pose_real_runbook.md)
- [Dual-grid twin](dual_grid_twin.md)
- [Teach squares](teach_squares.md)
- [URDF package README](../assets/so-101-urdf/README.md)
- [SO-101 asset provenance](../assets/so101/PROVENANCE.md)
