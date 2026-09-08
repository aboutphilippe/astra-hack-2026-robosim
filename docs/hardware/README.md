# Shared hardware and runtime reference

Canonical reference for all agents working on this project's SO-101 chess setup.
Read this before selecting simulation assets or running hardware code.

**Status:** initial specification only; robot-host verification is pending.
**Updated:** 2026-09-08 by coordinating agent.
**Source:** user-supplied SO-101 + cameras (`nono`) context pack. The referenced
ChessBench paths below have not been verified in this repository.
**Open request:** [001: Robot host and stack handoff](../../coordination/tasks/001-robot-host-handoff.md).

## Supplied specifications — unverified on robot host

| Item | Supplied value | Outstanding verification |
| --- | --- | --- |
| Robot | SO-101 follower, ID `nono`; leader available | Connected devices and working stack |
| Joints | `shoulder_pan`, `shoulder_lift`, `elbow_flex`, `wrist_flex`, `wrist_roll`, `gripper` | Joint IDs, limits, calibration and zero conventions |
| Actuators | Feetech STS3215, IDs 1–6 | Identity and health from existing evidence |
| Command units | Arm degrees; gripper 0–100 | Actual driver interface and mapping |
| Wrist camera | `icspring` UVC RGB, 1920×1080, manual focus | Identity, intrinsics, mount transform, working capture |
| External camera | Orbbec Gemini 336 RGB-D, SDK-only on supplied Mac setup | SDK, firmware, profiles, extrinsics, current stream ownership |
| Gemini firmware | Supplied stack requires 1.8.10 | Installed version; this is not authorization to upgrade |
| Board square | Hardware notes 38.1 mm; scene notes 36 mm | Physical measurement required; unresolved |
| Board frame | Border and frame height each 25.4 mm | Physical measurement and board-to-robot pose |
| Piece dimensions | Not supplied | Heights, grasp widths, bases, masses where useful |
| Runtime URDF | `assets/so-101-urdf/urdf/so101_new_calib.urdf` in referenced stack | Actual repository path and asset revision |
| MuJoCo assets | `assets/so101/` in referenced stack | Actual repository path, provenance and model fidelity |
| Calibration | LeRobot `robots/so_follower/nono.json`; joint spans and URDF mapping in referenced stack | Current files, dates, units, relevant transforms |

Do not hardcode camera indices. The supplied setup identifies the wrist by name/UID
and warns that opening the Gemini depth node with OpenCV interferes with SDK use.
Treat discovery as separate from permission to open devices.

## Robot host, code, and runtime

Pending robot-host response: OS/architecture, project directory, repository/branch/SHA,
uncommitted stack work, Python environment, dependencies, and working launch commands.
The robot is connected to a teammate's computer, as confirmed by the project operator.
The preliminary coordinator-side MuJoCo scaffold is paused and is not the selected stack.

## Calibration and coordinate conventions

Pending: measured square size, board origin and axes, camera intrinsics and extrinsics,
transform directions, joint-zero and sign mappings, gripper geometry, and calibration
file provenance. Do not interpret provisional simulator coordinates as measured values.

## Demonstrated capabilities

No robot-host evidence has been received yet. Record each verified capability with
its observation date, host label, command or procedure, and log/artifact reference:
joint reads, teleoperation, camera capture, positioning, grasping, and piece transfers.
Successful simulation does not establish physical success.

## Remote access

Pending operator-approved connection method. Store only information suitable for
this public repository; private host details and public-key enrollment can be exchanged
by the operators. Never commit credentials or private keys. Access configuration does
not itself authorize physical motion.

## How to update

Update this reference in the same PR as the corresponding handoff response. For each
new fact, mark **verified**, **documented but unverified**, or **missing**; give its
source and observation date/host. Link the response and relevant configuration or
artifact. Resolve discrepancies explicitly. Keep this document usable independently
of chat history; use response files for detailed command output and historical evidence.
