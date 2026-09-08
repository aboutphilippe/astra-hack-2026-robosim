"""One metric fixture shared by the scene, planner, and camera convention."""
import json
import math
import os
from copy import deepcopy
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ROOT = ROOT.parent if ROOT.name == "backend" else ROOT


def load_config() -> dict:
    path = Path(os.environ.get("NONO_CONFIG", ROOT / "config" / "nono.json"))
    config = json.loads(path.read_text())
    validate_board(config["board"])
    return resolve_robot_placement(config)


def resolve_robot_placement(config: dict) -> dict:
    """Resolve a reported board side into an explicitly estimated robot pose.

    The SO-101 model reaches forward along its base +X axis. A robot outside
    the h-file edge therefore faces board-local -X. The offset is measured
    from the board's outer border to the model's *base-frame origin*, not to
    its nearest plastic surface. Neither offset nor elevation is calibrated
    by knowing which side the robot occupies.

    Full measured robot registration takes precedence. Resolving copies the
    entire configuration so callers can validate a candidate without changing
    the active scene, and repeats safely after board scale/pose changes.
    """
    result = deepcopy(config)
    robot = result.get("robot", {})
    placement = robot.get("placement")
    if robot.get("pose_measured") is True or placement is None:
        return result
    if not isinstance(placement, dict) or placement.get("mode") != "board_edge" or placement.get("edge") != "h":
        raise ValueError("Robot placement must use mode 'board_edge' and edge 'h'.")
    if placement.get("measured", False) is not False:
        raise ValueError("Board-edge placement remains unmeasured until robot-base registration.")

    def bounded(value, label, lower, upper):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
            raise ValueError(f"{label} must be a finite number from {lower} to {upper}.")  # noqa: TRY004 -- API config errors use ValueError.
        value = float(value)
        if not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError(f"{label} must be a finite number from {lower} to {upper}.")
        return value

    fraction = bounded(placement.get("along_fraction", 0.5), "Placement along_fraction", 0, 1)
    offset = bounded(placement.get("base_origin_offset_m", 0.10), "Placement base-origin offset", 0, 1)
    elevation = bounded(placement.get("elevation_above_board_bottom_m", 0), "Placement elevation", -1, 1)
    board = result.get("board", {})
    validate_board(board)
    size = float(board["square_size_m"])
    border = bounded(board.get("border_m", 0.0254), "Board border", 0, 0.25)
    height = bounded(board.get("height_m", board.get("thickness_m", 0.0254)), "Board height", 0.0001, 0.5)
    yaw = board.get("yaw_rad", 0)
    if isinstance(yaw, (bool, np.bool_)) or not isinstance(yaw, (int, float, np.integer, np.floating)) or not math.isfinite(yaw):
        raise ValueError("Board yaw must be finite radians.")
    c, s = math.cos(yaw), math.sin(yaw)
    rotation = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    local = np.array([8 * size + border + offset, 8 * size * fraction, -height + elevation])
    robot["base_position_m"] = (np.asarray(board["origin_m"], dtype=float) + rotation @ local).tolist()
    facing = float(yaw) + math.pi
    robot["base_yaw_rad"] = math.atan2(math.sin(facing), math.cos(facing))
    robot["pose_measured"] = False
    result["robot"] = robot
    return result


def validate_board(board: dict) -> None:
    size = float(board["square_size_m"])
    origin = np.asarray(board["origin_m"], dtype=float)
    if not np.isfinite(size) or not 0.015 <= size <= 0.08:
        raise ValueError("Square size must be between 15 and 80 mm.")
    if origin.shape != (3,) or not np.isfinite(origin).all() or np.max(np.abs(origin)) > 2:
        raise ValueError("Board origin must contain three finite metric coordinates within 2 m.")
