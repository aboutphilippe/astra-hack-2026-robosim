"""Board-side placement is a spatial estimate until robot registration exists."""

import json
import math
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from chessbot.config import load_config, resolve_robot_placement
from chessbot.simulation import Simulation


@pytest.fixture
def layout():
    return json.loads((Path(__file__).resolve().parents[1] / "config" / "nono.json").read_text())


def test_reported_h4_h5_side_resolves_without_claiming_measured_metrics(layout):
    before = deepcopy(layout)
    resolved = resolve_robot_placement(layout)
    assert layout == before
    assert np.allclose(resolved["robot"]["base_position_m"], [.2778, .2324, 0])
    assert resolved["robot"]["base_yaw_rad"] == pytest.approx(math.pi)
    assert resolved["robot"]["placement"]["source"] == "user_reported_h4_h5"
    assert not resolved["robot"]["placement"]["measured"]
    assert not resolved["robot"]["pose_measured"]
    assert resolved["robot"]["sample_riser_height_m"] == 0
    assert resolved["motion"]["lift_m"] == .10
    resolved["robot"]["placement"]["along_fraction"] = 1
    assert layout["robot"]["placement"]["along_fraction"] == .5


@pytest.mark.parametrize("yaw,expected_position,forward", [
    (0, [1.52, -.30, .06], [-1, 0]),
    (math.pi / 2, [.80, .02, .06], [0, -1]),
    (-math.pi / 2, [1.20, -1.02, .06], [0, 1]),
])
def test_h_edge_anchor_tracks_board_scale_translation_and_rotation(layout, yaw, expected_position, forward):
    # Start with already-resolved fields to expose stale-XYZ regressions.
    config = resolve_robot_placement(layout)
    config["board"].update(square_size_m=.05, border_m=.02, height_m=.04,
                           origin_m=[1, -.5, .1], yaw_rad=yaw)
    resolved = resolve_robot_placement(config)
    assert np.allclose(resolved["robot"]["base_position_m"], expected_position)
    angle = resolved["robot"]["base_yaw_rad"]
    assert np.allclose([math.cos(angle), math.sin(angle)], forward, atol=1e-12)
    # Simulation also resolves caller-mutated input, without requiring load_config.
    simulation = Simulation(config)
    assert np.allclose(simulation.base_position, expected_position)
    assert simulation.snapshot()["robot_pose"] == {
        "base_position_m": resolved["robot"]["base_position_m"],
        "base_yaw_rad": angle, "pose_measured": False,
        "placement": resolved["robot"]["placement"],
    }


def test_explicit_measured_registration_wins_over_stale_side_estimate(layout):
    layout["robot"].update(pose_measured=True, base_position_m=[0, 0, 0], base_yaw_rad=0)
    layout["robot"]["placement"]["base_origin_offset_m"] = None
    original = deepcopy(layout)
    resolved = resolve_robot_placement(layout)
    assert resolved == original
    assert resolved is not layout
    simulation = Simulation(layout)
    assert np.array_equal(simulation.base_position, [0, 0, 0])
    assert simulation.base_yaw == 0


def test_explicit_world_pose_without_placement_remains_supported(layout):
    del layout["robot"]["placement"]
    layout["robot"].update(base_position_m=[.3, .1, .2], base_yaw_rad=.4)
    assert resolve_robot_placement(layout) == layout


def test_positive_base_world_height_does_not_invent_a_riser(layout):
    del layout["robot"]["sample_riser_height_m"]
    layout["board"]["origin_m"][2] = .2
    simulation = Simulation(layout)
    assert simulation.base_position[2] == pytest.approx(.1746)
    assert "sample_robot_riser" not in {geom["name"] for geom in simulation.snapshot()["geoms"]}


def test_load_config_resolves_side_placement(layout, tmp_path, monkeypatch):
    path = tmp_path / "desk.json"
    path.write_text(json.dumps(layout))
    monkeypatch.setenv("NONO_CONFIG", str(path))
    assert load_config() == resolve_robot_placement(layout)


@pytest.mark.parametrize("field,value", [
    ("along_fraction", -.01), ("along_fraction", 1.01), ("along_fraction", math.nan),
    ("base_origin_offset_m", -.001), ("base_origin_offset_m", 1.01),
    ("base_origin_offset_m", math.inf), ("base_origin_offset_m", True),
    ("elevation_above_board_bottom_m", -1.01), ("elevation_above_board_bottom_m", 1.01),
    ("elevation_above_board_bottom_m", math.nan), ("measured", True),
    ("mode", "world"), ("edge", "a"),
])
def test_invalid_placement_is_rejected_before_building_scene(layout, field, value):
    layout["robot"]["placement"][field] = value
    with pytest.raises(ValueError):
        resolve_robot_placement(layout)


@pytest.mark.parametrize("field,value", [("yaw_rad", math.inf), ("yaw_rad", True),
                                         ("border_m", math.nan), ("height_m", 0)])
def test_placement_rejects_invalid_board_geometry(layout, field, value):
    layout["board"][field] = value
    with pytest.raises(ValueError):
        resolve_robot_placement(layout)
