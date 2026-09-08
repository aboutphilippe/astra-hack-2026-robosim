# SO-101 model provenance

The unmodified `so101.xml`, the 18 binary STL files in `assets/`, `LICENSE`,
and `UPSTREAM_README.md` were downloaded from
[Google DeepMind MuJoCo Menagerie, `robotstudio_so101`](https://github.com/google-deepmind/mujoco_menagerie/tree/8161bba264d7fa7c99ca301e91e7fb44737676ad/robotstudio_so101)
at commit **8161bba264d7fa7c99ca301e91e7fb44737676ad** on 2026-09-08.
They retain the upstream Apache-2.0 license.

The upstream README documents derivation from The Robot Studio SO-101 model,
including `so101_new_calib.xml` commit
`aec17bbc256d1a7342d53aaa4950595d4c30b40d`, simplified collision shapes,
actuator settings, and the camera mount. This is an actual SO-101 articulated
model with five arm hinges and one jaw hinge, not a generic six-axis arm.

`backend/chessbot/simulation.py` loads this XML and adds a metric chessboard,
table, and reference overhead camera in memory. It assigns stable names to
otherwise unnamed geoms and sets the configured base pose. Mesh rendering
undoes MuJoCo's principal-axis/centroid preprocessing so the browser can render
the original STL files in the same world positions as MuJoCo.

The board's initial 38.1 mm squares, 25.4 mm border, and 25.4 mm height come
from the supplied hardware context. They are editable priors, not a fresh
measurement. Board origin is the a1-side lower playing-grid corner, +X is
files a→h, +Y is ranks 1→8, +Z is up. The default base sits beyond rank 8 at
`[0, 0.50, 0.06]` m, with yaw `-π/2`, on an explicit **6 cm sample riser**;
it is a sample layout, not a surveyed pose or a claim that this riser exists
on the real desk. The opening e7→e5 and first side-capture slot are reachable
in this layout with the gripper downward and a 10 cm clearance above the board.

The upstream `gripperframe` is the TCP. Its +X points out along the fingers;
the IK solver's downward grasp constraint points that axis toward world -Z.
It leaves rotation about the approach axis free. The native model's camera
mount differs from the desk-specific wrist optical calibration in the user
context and must be measured before relying on wrist-camera projection.

The supplied full-size board is **not entirely reachable with a vertical
gripper from this default base pose**. Joint limits also restrict high
clearance above nearby ranks. The API exposes position error, approach error,
and model contacts rather than claiming an executable trajectory. Piece
grasp physics, physical servo mapping, calibrated camera extrinsics, and
human-aware collision avoidance are separate work; a kinematic preview is
not a validated physical execution.

SHA-256 checksums of every downloaded file are listed in `SHA256SUMS`.
