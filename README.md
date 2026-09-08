# NONO Chess Lab

A local real-to-simulation workbench for an SO-101 playing Black against a human playing White. React renders the **actual MuJoCo SO-101 geometry and joint transforms**. Python owns chess rules, metric calibration, inverse kinematics, and animation. Codex Astra can use an MCP tool interface to inspect the same environment and propose moves.

**Current milestone: working simulation and camera-calibration foundation.** This repository does not yet operate the physical servos or certify collision-free grasps. The live camera adapter requires the optional drivers and enrollment of the actual Orbbec SDK serial number. Physical calibration has not been performed by creating this repository.

## Run locally

Requirements: Python 3.11–3.13, [uv](https://docs.astral.sh/uv/), Node 20+, npm.

```bash
make setup
make dev
```

Open [the chess console](http://127.0.0.1:5173). API documentation is at [localhost:8000/docs](http://127.0.0.1:8000/docs). To run servers separately: `make api` and `make web` in separate terminals. `make test` runs the Python tests; `npm --prefix web test` runs the frontend tests; `make build` checks TypeScript and builds the browser app.

If port 8000 is occupied, run `NONO_PORT=8010 NONO_API_URL=http://127.0.0.1:8010 make dev`. Set the same `NONO_API_URL` for the MCP process.

Click a White piece and a legal destination, then simulate NONO’s turn. The demo uses a small deterministic chess search. Captures first move the victim into the next free side slot. En passant removes the pawn from its actual square; castling includes the rook; promotion is explicitly flagged for a physical piece swap.

The demo’s 38.1 mm squares, board pose, piece profiles, and **60 mm robot riser are unmeasured sample geometry**. They enable a reproducible opening preview. Some distant squares and later capture slots are outside the arm’s vertical grasp workspace. An unreachable plan stays blocked, with residuals visible. Do not copy this pose to real motors.

## Measure instead of guessing

The target source of truth is the Orbbec’s aligned RGB-D observation, not a product listing or hardcoded dimensions:

1. Capture the original Gemini RGB image, depth in metres, and matching intrinsics.
2. Label four **playing-grid** corners: a1, h1, h8, a8. Exclude the decorative border. Four clicks replace entering square dimensions. An unobstructed board makes the plane estimate more reliable.
3. Fit the board plane robustly, intersect the four pixel rays with it, and derive the eight-square width. Reject missing depth, poor plane coverage, and inconsistent square geometry. Measure each square’s piece height above this plane.
4. Register at least three noncollinear, known landmarks on the rigid robot base against depth. This supplies the camera-to-robot transform. Depth alone cannot name an arbitrary point as the robot origin. Known base landmarks or a fixed marker provide that reference.
5. Validate the overlay, all 64 grasp targets, the discard area, and gripper geometry before adding physical motion.

See [the calibration runbook](docs/calibration.md). Measurement results are saved to ignored `artifacts/calibration/latest.json`; raw aligned snapshots are saved to `artifacts/camera/`. They are never silently restored as current calibration after restart.

White’s back rank is **a1–h1**, pawns **a2–h2**. The console’s a1-top-left occupancy diagram is schematic. The actual camera image is never mirrored to force this convention: labels determine the mapping. The robot frame is metric and right-handed; camera pixels are not robot coordinates.

## Hardware

`config/nono.json` records this desk’s device roster:

| Device | Driver / identity |
| --- | --- |
| SO-101 follower `nono` | `/dev/tty.usbmodem5B415320131`; five arm joints plus a gripper |
| Gemini 336 | Orbbec SDK only; AVFoundation UID `0x22000002bc50803` |
| Wrist RGB | `icspring`, UID `0x112000029930858`; resolve UID/name each time |

```bash
uv sync --extra camera
uv run nono-discover --sdk
cp config/nono.json config/local.json
# Fill cameras.top.sdk_serial with the enumerated SDK serial.
NONO_CONFIG=config/local.json uv run nono-api
```

An AVFoundation UID is **not** an Orbbec SDK serial. Explicit enrollment prevents an arbitrary SDK device from being selected. The desk fixture’s firmware gate is 1.8.10; the code reports a mismatch and never flashes firmware. Gemini depth is never opened through OpenCV. No camera or motor bus opens when the ordinary simulation starts. `uv run nono-discover` only checks configured paths and installed driver availability; `--sdk` explicitly enumerates cameras.

The supplied [hardware context pack](docs/hardware-context.md) is preserved as source material. Its relative links refer to the previous ChessBench project, not files implemented here. In particular, its 36 mm / 38.1 mm conflict is resolved by measurement, not by claiming either prior is calibrated.

## Codex Astra

Start the API, then register this repository’s stdio MCP adapter:

```bash
codex mcp add nono-chess -- uv --directory /absolute/path/to/astra-hack-2026-robosim run nono-mcp
```

Select **GPT-6 Astra / Ultra** in your Codex task where available. The repository does not change global model settings. The `Ultra` selection is a Codex setting; do not assume it is an API `reasoning.effort` value. This integration uses your Codex session and does not make independent OpenAI API calls or require another API key.

Use [the operator prompt](prompts/chess-operator.md). Tools capture RGB images, expose calibration/FEN/joints, conservatively reconcile a human move, solve IK, preview captures, and animate a robot move. MCP proxies the running API so it shares the browser’s game. The model interprets images and chooses moves; deterministic chess rules and numerical IK check its proposals. The local demo engine remains available without a model session.

The MCP connection is implemented using the [official Codex MCP configuration](https://developers.openai.com/codex/mcp/). The [Astra model reference](https://developers.openai.com/api/docs/models/gpt-6-astra) documents API reasoning settings separately from desktop choices.

## Shared Mac server and teammates

The Mac can host a separate **authenticated shared runtime** using `uv run nono-server` on loopback port 8011. It serves the compiled React console and the API together. Teammates connect through private HTTPS with their own revocable viewer/operator credentials. A time-limited operator lease prevents simultaneous camera/calibration/game mutations; anyone with viewer access can inspect state.

Use [the team server guide](docs/team-server.md) to provision one credential per person or client, generate the macOS service configuration, and set up private Tailscale access. The server owner supplies the actual private URL and each recipient's token file; the repository includes no configured remote endpoint. Teammates run `nono-mcp` in their own clones, configured with `NONO_API_URL` and a private `NONO_API_TOKEN_FILE`. [Example Codex configuration](docs/codex-client.example.toml) is included. Browser and MCP access through Tailscale requires no remote shell; the optional SSH tunnel requires an existing SSH account.

[CONTRIBUTING.md](CONTRIBUTING.md) explains branches, fork-based PRs, and promoting reviewed commits into a dedicated server checkout. The shared server reports its running revision; checking out a branch on a teammate's laptop does not deploy it to the robot Mac. GitHub CI runs on hosted runners, and runtime deployment remains a separate owner action.

## Repository map

```text
backend/chessbot/
  api.py             Shared game state, HTTP API, motion choreography
  simulation.py      Native MuJoCo model, FK, Jacobian IK, geometry snapshots
  chess_logic.py     Rules, legal observation matching, ordered piece transfers
  calibration.py     Homography, RGB-D plane/scale/heights, rigid registration
  hardware.py        Read-only discovery and optional camera capture
  mcp_server.py      Codex tools that proxy the same HTTP cell
web/                 React + Three.js console
assets/so101/        Pinned upstream model, meshes, license, provenance
config/nono.json     Device identities and explicitly unmeasured demo fixture
tests/               Rules, calibration, IK, and API regression checks
```

MuJoCo uses the [Menagerie SO-101 model](https://github.com/google-deepmind/mujoco_menagerie/tree/main/robotstudio_so101), with its license and pinned provenance included. Its local FK/Jacobian solver follows the [native MuJoCo Python API](https://mujoco.readthedocs.io/en/stable/python.html).

## Remaining work for autonomous physical play

* Measure this desk’s camera intrinsics/alignment quality, board pose, robot-base landmarks, piece dimensions, and discard area; validate overlays against real images.
* Map LeRobot’s calibrated joint degrees and gripper 0–100 to this exact MJCF’s radians. The six channels comprise five arm DOF and a jaw, not six freely orientable arm axes.
* Add full robot/board/piece/hand collision checks along trajectories, calibrated grasp offsets and jaw widths, contact/grasp verification, and recovery for slipped or dropped pieces. Current carried pieces are visual attachments, not contact-physics grasps.
* Add a physical executor with measured joint state, motion limits, stop behavior, and post-move camera verification. No existing route sends servo commands.
* Collect real camera examples and evaluate model observation accuracy. A complete occupancy map is required; occlusions, ambiguity, low confidence, stale snapshots, and illegal positions do not commit a human move.

An exact twin is a measured and validated outcome. The current repository supplies the tools and runnable scene for working toward it, while keeping unmeasured assumptions visible.
