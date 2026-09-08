"""Codex tools proxy to the SAME running API that React uses; never a second game."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from mcp.server.fastmcp import FastMCP, Image

BASE_URL = os.environ.get("NONO_API_URL", "http://127.0.0.1:8000")
mcp = FastMCP("nono-chess", instructions="Inspect state and camera snapshots, reconcile only legal human moves, "
              "then preview and simulate Black moves. All execution is simulation-only. Never treat a demo pose "
              "as measured. A1 and H1 hold White's back rank. Camera pixel order must be calibrated explicitly. "
              "On a shared server, inspect control ownership and explicitly acquire the operator lease before "
              "mutations. Renew it during work and release when idle; do not take control from another teammate.")


def client_headers() -> dict[str, str]:
    """Load credentials from a local file on every request, allowing rotation without restarting Codex."""
    path = os.environ.get("NONO_API_TOKEN_FILE")
    token = Path(path).expanduser().read_text().strip() if path else os.environ.get("NONO_API_TOKEN", "").strip()
    parsed = urlsplit(BASE_URL)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("NONO_API_URL must be an HTTP(S) URL without embedded credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError("NONO_API_URL must not contain query parameters or fragments.")
    if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Remote NONO access requires HTTPS. Use Tailscale Serve or an SSH tunnel to localhost.")
    if token and (len(token) < 32 or any(char.isspace() for char in token)):
        raise ValueError("The NONO credential is malformed; use the token file supplied by the server owner.")
    return {"Authorization": f"Bearer {token}"} if token else {}


def request(method: str, path: str, data: dict | None = None):
    with httpx.Client(base_url=BASE_URL, timeout=120, headers=client_headers(), follow_redirects=False) as client:
        response = client.request(method, path, json=data)
        if response.is_error:
            raise ValueError(f"Chess cell {response.status_code}: {response.text}")
        return response.json()


def camera_image(path: str) -> Image:
    with httpx.Client(base_url=BASE_URL, timeout=30, headers=client_headers(), follow_redirects=False) as client:
        response = client.get(path)
        response.raise_for_status()
    return Image(data=response.content, format="jpeg")


@mcp.tool()
def get_server_info() -> dict:
    """Read the shared server revision, branch and capabilities. Your local branch is independent."""
    return request("GET", "/api/server-info")


@mcp.tool()
def get_control() -> dict:
    """Check who owns the shared cell and whether the current credential has the operator lease."""
    return request("GET", "/api/control")


@mcp.tool()
def acquire_control(ttl_seconds: int = 300) -> dict:
    """Explicitly claim exclusive shared-cell control for 30–900 seconds. Requires an operator credential.
    A busy/owned cell rejects takeover. Observers do not need a lease to read state.
    """
    return request("POST", "/api/control/acquire", {"ttl_seconds": ttl_seconds})


@mcp.tool()
def renew_control(ttl_seconds: int = 300) -> dict:
    """Renew your existing operator lease while using the shared cell; cannot renew another teammate's lease."""
    return request("POST", "/api/control/renew", {"ttl_seconds": ttl_seconds})


@mcp.tool()
def release_control() -> dict:
    """Release your operator lease when idle so another teammate can use the cell."""
    return request("POST", "/api/control/release", {})


@mcp.tool()
def get_environment() -> dict:
    """Read current FEN, pieces, calibration quality, joint pose and last observation."""
    state = request("GET", "/api/state")
    state["simulation"].pop("geoms", None)
    return state


@mcp.tool()
def capture_board() -> list:
    """Capture registered Gemini aligned RGB-D; return original image plus frame identity and game state.

    Use the image to infer all 64 square occupancies. '?' means obscured, never empty.
    This requests a snapshot; it does not update chess state or move the robot.
    """
    frame = request("POST", "/api/camera/capture", {"camera": "top"})
    return [frame, camera_image("/api/camera/top.jpg"), get_environment()]


@mcp.tool()
def inspect_wrist() -> list:
    """Capture the UID/name-matched wrist RGB camera for visual grasp inspection."""
    meta = request("POST", "/api/camera/capture", {"camera": "wrist"})
    return [meta, camera_image("/api/camera/wrist.jpg")]


@mcp.tool()
def measure_board(corners_px: list[list[float]]) -> dict:
    """Measure board/square dimensions from captured depth. Label outer playing-grid corners
    a1, h1, h8, a8 in the ORIGINAL camera pixels. Resets simulation using measured scale.
    Does not register the robot base. Requires clear board plane and aligned depth.
    """
    result = request("POST", "/api/calibration/measure", {"corners_px": corners_px})
    return result["calibration"]


@mcp.tool()
def register_robot_base(landmarks: list[dict]) -> dict:
    """Register >=3 noncollinear robot-base landmarks from the SAME board RGB-D frame.
    Each item: pixel=[u,v], robot_m=[x,y,z] from known rigid robot CAD geometry.
    Never guess robot_m from an image. Fits camera-to-robot; rebuilds the horizontal scene
    from the measured transform and resets the game. Rejects poor or tilted registration.
    """
    return request("POST", "/api/calibration/robot-rgbd", {"landmarks": landmarks})["calibration"]


@mcp.tool()
def reconcile_human_move(occupancy: dict[str, str | None], confidence: float, hand_clear: bool,
                         base_fen: str, frame_id: str, commit: bool = False) -> dict:
    """Match complete color occupancy to legal successors. Only a unique legal move can be
    committed. Use frame_id/base_fen from capture_board, and abstain if a hand occludes the board.
    Color-only promotion is ambiguous; request piece identity before proceeding.
    """
    return request("POST", "/api/observe", {"occupancy": occupancy, "confidence": confidence,
                   "hand_clear": hand_clear, "base_fen": base_fen, "frame_id": frame_id, "commit": commit})


@mcp.tool()
def solve_inverse_kinematics(target_m: list[float], downward: bool = True) -> dict:
    """Solve SO-101 IK in the MuJoCo world frame; return residual, joint limits and orientation checks.
    A successful endpoint does not prove collision-free transit or physical feasibility.
    """
    return request("POST", "/api/ik", {"target": target_m, "downward": downward})


@mcp.tool()
def preview_robot_move(uci: str) -> dict:
    """Preview a legal Black move, ordered victim removal, IK targets, and manual promotion needs."""
    return request("POST", "/api/plan", {"uci": uci})["plan"]


@mcp.tool()
def simulate_robot_move(uci: str | None = None) -> dict:
    """Animate a reachable legal Black move in MuJoCo. Omit UCI for the local demo chess engine.
    This cannot command real servos. Poll get_environment until status returns ready or blocked.
    """
    result = request("POST", "/api/robot", {"uci": uci, "execute": True})
    return {"status": result["status"], "plan": result["plan"]}


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
