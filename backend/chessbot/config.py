"""One metric fixture shared by the scene, planner, and camera convention."""
import json
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ROOT = ROOT.parent if ROOT.name == "backend" else ROOT


def load_config() -> dict:
    path = Path(os.environ.get("NONO_CONFIG", ROOT / "config" / "nono.json"))
    config = json.loads(path.read_text())
    validate_board(config["board"])
    return config


def validate_board(board: dict) -> None:
    size = float(board["square_size_m"])
    origin = np.asarray(board["origin_m"], dtype=float)
    if not np.isfinite(size) or not 0.015 <= size <= 0.08:
        raise ValueError("Square size must be between 15 and 80 mm.")
    if origin.shape != (3,) or not np.isfinite(origin).all() or np.max(np.abs(origin)) > 2:
        raise ValueError("Board origin must contain three finite metric coordinates within 2 m.")
