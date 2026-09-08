# 001: Robot host and stack handoff

- Status: READY
- Target: colleague's Codex on the computer connected to SO-101 `nono`
- Requester: coordinating Codex on Mohit's computer
- Response: `coordination/responses/001-robot-host-handoff.md`
- Shared reference to update: `docs/hardware/README.md`
- Claim branch: `work/001-robot-host-handoff`

## Objective

Provide the verified hardware/runtime context needed to build chess manipulation
simulation consistent with the team's intended stack. Implementation is paused
while the robot-host teammate publishes that stack.

Follow the claim and response protocol in AGENTS.md. If you are reading this on
a different host, do not claim the task on behalf of the robot host.

## Allowed scope

Read repository state, installed package metadata, device listings, existing
calibration/configuration files, existing logs, and existing remote-access settings.
Run passive version or enumeration commands only when they do not open devices or
interfere with active sessions. Update the shared hardware reference, commit the
handoff response, and open one PR containing both.
Redact secrets; report only relevant calibration fields and access metadata.

Do not move the arm, enable torque, run calibration, open serial buses/cameras,
install packages, change firmware, enable services, or change network permissions.
Do not stop existing robot/camera processes. Mark live checks requiring these
actions as unverified and identify the command for later operator execution.

## Requested information

1. **Code:** repository URL, branch, full latest SHA, pending changes, intended stack
   publication status, and relevant source paths. Do not publish unrelated changes.
2. **Runtime:** OS/architecture, project directory, Python executable/environment,
   simulator, control library, camera SDK versions, and known working launch commands.
3. **Robot:** follower/leader device paths, robot ID, calibration file locations,
   joint names and units, limits, and servo-to-URDF/MJCF mapping. Distinguish path
   presence from identity verified in existing logs or prior successful operation.
4. **Cameras:** device identity, capture commands, resolutions, SDK/firmware evidence,
   intrinsics/extrinsics and their frame conventions. Indicate if streams are in use.
5. **Scene:** measured board square size (supplied notes conflict: 38.1 versus 36 mm),
   board-to-base transform, board height, piece dimensions, gripper modifications,
   camera mounts, and URDF/MJCF/mesh paths and provenance. If not measured, say so.
6. **Proven behavior:** evidence for joint reads, teleoperation, camera capture,
   calibrated positioning, grasping, and piece transfer. Include timestamps and
   logs/artifact paths where available; do not rerun physical checks for this task.
7. **Remote access:** existing SSH username/address or Tailscale hostname, whether
   the operator authorizes our machine to connect, and how public-key enrollment
   would be arranged if needed. Never send passwords or private keys. If host/access
   metadata should remain private, mark it available through the operators rather
   than committing it to this public repository.

The supplied specs describe SO-101 with five arm joints plus gripper, an `icspring`
RGB wrist camera, and Orbbec Gemini 336 RGB-D via its SDK. Treat these as claims to
check, not proof of current hardware state. In particular, do not open the Gemini
AVFoundation depth node through OpenCV.

## Completion criteria

Every requested item has a verified answer, a documented-but-unverified answer,
or an explicit missing/blocked explanation. The response records the request SHA,
host label, observation time, checks performed, and any changes. Push the response
branch and open a PR with the title `Handoff: robot host and intended stack`.
Update `docs/hardware/README.md` with the reusable facts from all seven requested
categories, preserving verification status, host, observation date, commands, and
links to evidence. Other agents must be able to use that reference without reading
this conversation. Keep sensitive access details out of the public reference.
No physical test or stack implementation is required to complete this handoff.
