"""State-transition tests with a fast kinematic stand-in; real IK has its own tests."""

import time
from copy import deepcopy

import chess
import numpy as np
import pytest
from chessbot import api, calibration
from chessbot.config import load_config
from fastapi.testclient import TestClient


class StubSimulation:
    def __init__(self, config):
        self.config = deepcopy(config)
        self.qpos = [0.0] * 6

    def snapshot(self):
        return {"joints": [{"name": str(i), "position": value, "min": -2, "max": 2}
                           for i, value in enumerate(self.qpos)], "tcp": [0.1, 0.2, 0.3]}

    def solve_ik(self, target, seed=None, downward=True):
        return {"qpos": [0.1] * 6, "reachable": True, "error_m": 0.0}

    def set_qpos(self, values):
        self.qpos = list(values)

    def evaluate_qpos(self, qpos):
        return {"collision_free": True, "contacts": [], "orientation_error_rad": 0.0}

    def interpolate_qpos(self, target, steps=30, start=None):
        initial = np.asarray(self.qpos if start is None else start)
        return [(initial + (np.asarray(target) - initial) * t).tolist()
                for t in np.linspace(0, 1, steps + 1)[1:]]

    def check_path(self, samples):
        return {"collision_free": True, "contacts": [], "samples_checked": len(samples),
                "first_collision_index": None, "continuous_collision_checked": False}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "Simulation", StubSimulation)
    monkeypatch.setattr(api.Cell, "save_calibration", lambda self: None)
    app = api.create_app(load_config())
    with TestClient(app) as value:
        yield value


def observe_payload(cell, uci, *, commit=False):
    frame = {"frame_id": "test-frame", "base_fen": cell.game.board.fen(), "timestamp": time.time()}
    cell.latest_frame = frame
    board = cell.game.board.copy()
    board.push_uci(uci)
    occupancy = {}
    for square in chess.SQUARE_NAMES:
        piece = board.piece_at(chess.parse_square(square))
        occupancy[square] = ("white" if piece.color else "black") if piece else None
    return {"occupancy": occupancy, "confidence": 0.99, "hand_clear": True,
            "base_fen": frame["base_fen"], "frame_id": frame["frame_id"], "commit": commit}


def test_human_route_preserves_rules_and_enforces_white_turn(client):
    initial = client.get("/api/state").json()
    assert client.post("/api/move", json={"uci": "e2e5"}).status_code == 422
    assert client.get("/api/state").json()["fen"] == initial["fen"]
    after = client.post("/api/move", json={"uci": "e2e4"})
    assert after.status_code == 200
    assert after.json()["turn"] == "black"
    assert client.post("/api/move", json={"uci": "e7e5"}).status_code == 422


def test_robot_capture_preview_orders_transfers_and_preserves_allocation(client):
    cell = client.app.state.cell
    for move in ["e2e4", "d7d5", "e4d5"]:
        cell.game.apply_move(move)
    before = cell.game.state()
    response = client.post("/api/plan", json={"uci": "d8d5"})
    assert response.status_code == 200
    state = response.json()
    assert state["fen"] == before["fen"]
    assert state["capture_slots_used"] == 1
    capture, movement = state["plan"]["transfers"]
    assert capture["role"] == "capture"
    assert capture["destination"]["capture_slot"] == 1
    assert movement["source"]["square"] == "d8"
    assert state["captures"][0]["position"] == before["captured_pieces"][0]["destination"]["position_m"]


def test_observation_requires_current_frame_clear_hand_and_legal_single_move(client):
    cell = client.app.state.cell
    payload = observe_payload(cell, "e2e4", commit=True)
    assert client.post("/api/observe", json={**payload, "frame_id": "other"}).status_code == 422
    assert client.post("/api/observe", json={**payload, "hand_clear": False}).status_code == 422
    accepted = client.post("/api/observe", json=payload)
    assert accepted.status_code == 200
    assert accepted.json()["committed"]
    assert accepted.json()["uci"] == "e2e4"
    assert client.post("/api/observe", json=payload).status_code == 422
    assert len(cell.game.board.move_stack) == 1


def test_human_observation_preview_rejects_black_turn(client):
    cell = client.app.state.cell
    cell.apply_human("e2e4")
    payload = observe_payload(cell, "e7e5")
    response = client.post("/api/observe", json=payload)
    assert response.status_code == 422
    assert len(cell.game.board.move_stack) == 1


def test_reset_cancels_animation_and_invalidates_old_camera_frame(client):
    cell = client.app.state.cell
    cell.apply_human("e2e4")
    cell.latest_frame = {"frame_id": "old-game", "base_fen": chess.STARTING_FEN, "timestamp": time.time()}
    response = client.post("/api/robot", json={"uci": "e7e5", "execute": True})
    assert response.status_code == 200
    assert response.json()["status"] == "moving"
    reset = client.post("/api/reset")
    assert reset.status_code == 200
    assert reset.json()["fen"] == chess.STARTING_FEN
    assert reset.json()["status"] == "ready"
    assert reset.json()["last_move"] is None
    assert cell.latest_frame is None
    assert cell.task.done()
    assert cell.piece_overrides == {}


def test_invalid_board_config_preserves_current_game_and_geometry(client):
    cell = client.app.state.cell
    cell.apply_human("e2e4")
    before = deepcopy(cell.config)
    fen = cell.game.board.fen()
    response = client.post("/api/config/board", json={"square_size_m": 0.04, "origin_m": [10, 0, 0]})
    assert response.status_code == 422
    assert cell.config == before
    assert cell.game.board.fen() == fen


def test_invalid_measured_scale_preserves_prior_calibration_and_measurement(client, monkeypatch):
    cell = client.app.state.cell
    corners = [[100, 100], [500, 100], [500, 500], [100, 500]]
    cell.calibration.fit_camera(corners)
    cell.measurement = {"source": "previous_measurement"}
    cell.piece_heights = {"a1": {"height_m": 0.03}}
    cell.latest_frame = {"frame_id": "measured-frame", "capture_id": "measured-capture",
                         "depth_m": np.ones((600, 600)), "intrinsics": {"fx": 800, "fy": 800, "cx": 300, "cy": 300}}
    before_config, before_calibration = deepcopy(cell.config), cell.calibration.status()
    monkeypatch.setattr(calibration, "measure_board_rgbd", lambda *args: {"square_size_m": 0.2})
    monkeypatch.setattr(calibration, "piece_heights_rgbd", lambda *args: {})
    response = client.post("/api/calibration/measure", json={"corners_px": corners})
    assert response.status_code == 422
    assert cell.config == before_config
    assert cell.calibration.status() == before_calibration
    assert cell.measurement == {"source": "previous_measurement"}
    assert cell.piece_heights == {"a1": {"height_m": 0.03}}


def test_measured_heights_follow_human_robot_and_capture_moves_then_clear_on_reset(client):
    cell = client.app.state.cell
    cell.config["motion"]["waypoint_seconds"] = 0
    cell.piece_heights = {"e2": {"height_m": 0.035}, "d7": {"height_m": 0.045}, "b1": {"height_m": 0.06}}
    assert client.post("/api/move", json={"uci": "e2e4"}).status_code == 200
    assert cell.piece_heights == {"e4": {"height_m": 0.035}, "d7": {"height_m": 0.045}, "b1": {"height_m": 0.06}}
    assert client.post("/api/robot", json={"uci": "d7d5", "execute": True}).status_code == 200

    async def wait_for_robot():
        await cell.task

    client.portal.call(wait_for_robot)
    assert cell.game.board.turn == chess.WHITE
    assert cell.piece_heights["d5"]["height_m"] == 0.045
    assert "d7" not in cell.piece_heights
    assert client.post("/api/move", json={"uci": "e4d5"}).status_code == 200
    assert cell.piece_heights == {"d5": {"height_m": 0.035}, "b1": {"height_m": 0.06}}
    assert client.post("/api/reset").status_code == 200
    assert cell.piece_heights == {}


def test_castling_moves_both_height_records_and_promotion_invalidates_pawn_height(client):
    cell = client.app.state.cell
    cell.game.reset("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    cell.piece_heights = {"e1": {"height_m": 0.08}, "h1": {"height_m": 0.05}}
    assert client.post("/api/move", json={"uci": "e1g1"}).status_code == 200
    assert cell.piece_heights == {"g1": {"height_m": 0.08}, "f1": {"height_m": 0.05}}
    cell.game.reset("7k/P7/8/8/8/8/8/7K w - - 0 1")
    cell.piece_heights = {"a7": {"height_m": 0.03}}
    assert client.post("/api/move", json={"uci": "a7a8q"}).status_code == 200
    assert cell.piece_heights == {}


def test_robot_registration_rejects_board_measurement_from_another_capture(client, monkeypatch):
    cell = client.app.state.cell
    cell.measurement = {"capture_id": "old-capture"}
    cell.latest_frame = {"frame_id": "new-frame", "capture_id": "new-capture"}
    before_config = deepcopy(cell.config)

    def unexpected_registration(*args):
        pytest.fail("Stale capture must be rejected before fitting a registration")

    monkeypatch.setattr(calibration, "register_robot_rgbd", unexpected_registration)
    response = client.post("/api/calibration/robot-rgbd", json={"landmarks": [
        {"pixel": [10, 10], "robot_m": [0, 0, 0]},
        {"pixel": [20, 10], "robot_m": [0.1, 0, 0]},
        {"pixel": [10, 20], "robot_m": [0, 0.1, 0]},
    ]})
    assert response.status_code == 422
    assert "same RGB-D capture" in response.json()["detail"]
    assert cell.config == before_config
    assert cell.robot_registration is None


def test_rgbd_measurement_and_robot_registration_build_measured_scene_in_one_capture(client):
    cell = client.app.state.cell
    camera = {"fx": 800, "fy": 800, "cx": 300, "cy": 300}
    cell.latest_frame = {"frame_id": "before-measure", "capture_id": "same-physical-capture",
                         "timestamp": time.time(), "base_fen": cell.game.board.fen(),
                         "depth_m": np.full((600, 600), 0.8), "intrinsics": camera}
    # This physical image orientation gives a right-handed board +Z upward.
    corners = [[100, 500], [500, 500], [500, 100], [100, 100]]
    measured = client.post("/api/calibration/measure", json={"corners_px": corners})
    assert measured.status_code == 200
    assert cell.config["board"]["square_size_m"] == pytest.approx(0.05)
    assert cell.latest_frame["frame_id"] != "before-measure"
    assert cell.latest_frame["capture_id"] == "same-physical-capture"
    assert cell.measurement["capture_id"] == "same-physical-capture"
    rotation, translation = np.diag([1.0, -1.0, -1.0]), np.array([0.3, 0.4, 0.8])
    landmarks = []
    for pixel in [[150, 150], [450, 150], [150, 450]]:
        camera_point = np.array([(pixel[0] - 300) / 800, (pixel[1] - 300) / 800, 1]) * 0.8
        landmarks.append({"pixel": pixel, "robot_m": (rotation @ camera_point + translation).tolist()})
    registered = client.post("/api/calibration/robot-rgbd", json={"landmarks": landmarks})
    assert registered.status_code == 200
    assert cell.config["board"]["origin_m"] == pytest.approx([0.1, 0.2, 0])
    assert cell.config["board"]["yaw_rad"] == pytest.approx(0)
    assert cell.config["robot"]["pose_measured"]
    assert registered.json()["calibration"]["robot_calibrated"]
    assert not registered.json()["calibration"]["hardware_ready"]
