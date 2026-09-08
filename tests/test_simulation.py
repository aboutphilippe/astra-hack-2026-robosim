import json
import math
from pathlib import Path

import mujoco
import numpy as np
import pytest
from chessbot.simulation import JOINT_NAMES, Simulation


def reachable_regression_fixture():
    """Explicit synthetic raised rig for IK regressions, not the observed desk layout."""
    config = json.loads((Path(__file__).resolve().parents[1] / "config" / "nono.json").read_text())
    config["robot"].pop("placement", None)
    config["robot"].update({"base_position_m": [0, 0.50, 0.06], "base_yaw_rad": -math.pi / 2,
                             "sample_riser_height_m": 0.06, "pose_measured": False})
    return config


@pytest.fixture(scope="module")
def simulation():
    return Simulation(reachable_regression_fixture())


def test_real_model_and_board_dimensions(simulation):
    assert simulation.model.nq == 6
    assert simulation.model.nmesh == 18
    assert list(JOINT_NAMES) == [joint["name"] for joint in simulation.snapshot()["joints"]]
    squares = [g for g in simulation.snapshot()["geoms"] if g["name"].startswith("square_")]
    assert len(squares) == 64
    a1 = next(g for g in squares if g["name"] == "square_a1")
    h8 = next(g for g in squares if g["name"] == "square_h8")
    assert np.allclose(a1["size"][:2], [0.0381 / 2] * 2)
    assert np.allclose(np.array(h8["position"]) - a1["position"], [7 * 0.0381, 7 * 0.0381, 0])
    assert a1["position"][2] + a1["size"][2] == pytest.approx(0.0254)


def test_browser_raw_mesh_transform_matches_source_xml(simulation):
    # The first mesh's upstream position is (-.006365,-.000099,-.0024).
    # This explicit regression fixture uses yaw -pi/2: (x,y,z) -> (y,-x,z).
    geom = next(g for g in simulation.snapshot()["geoms"] if g["name"] == "base_geom_0")
    assert np.allclose(geom["position"], [-0.000099, 0.506365, 0.0576], atol=1e-7)
    assert geom["mesh"].endswith("/base_motor_holder_so101_v1.stl")


def test_reachable_ik_obeys_limits_and_preserves_scene(simulation):
    before = simulation.qpos
    target = [0.01905, 0.25145, 0.0434]
    result = simulation.solve_ik(target)
    assert result["reachable"]
    assert result["error_m"] <= 0.002
    assert result["orientation_error_rad"] <= 0.12
    assert np.array_equal(simulation.qpos, before)
    assert np.all(np.asarray(result["qpos"]) >= simulation.limits[:, 0])
    assert np.all(np.asarray(result["qpos"]) <= simulation.limits[:, 1])
    work = mujoco.MjData(simulation.model)
    work.qpos[:] = result["qpos"]
    mujoco.mj_forward(simulation.model, work)
    assert np.linalg.norm(work.site_xpos[simulation.site_id] - target) <= 0.002


def test_unreachable_is_explicit_and_deterministic(simulation):
    first = simulation.solve_ik([1.5, 1.5, 1.5])
    second = simulation.solve_ik([1.5, 1.5, 1.5])
    assert not first["reachable"]
    assert first["error_m"] > 1
    assert first["qpos"] == second["qpos"]
    assert not first["trajectory_checked"]


def test_position_only_does_not_claim_grasp_orientation(simulation):
    target = simulation.snapshot()["tcp"]
    unconstrained = simulation.solve_ik(target, downward=False)
    assert unconstrained["reachable"]
    assert not unconstrained["orientation_constrained"]
    assert unconstrained["orientation_error_rad"] > 0.12


def test_joint_validation_and_interpolation(simulation):
    with pytest.raises(ValueError, match="limits"):
        simulation.set_qpos([10, 0, 0, 0, 0, 0])
    with pytest.raises(ValueError, match="finite"):
        simulation.solve_ik([math.nan, 0, 0])
    target = simulation.home_qpos.copy()
    target[0] = 0.25
    samples = simulation.interpolate_qpos(target, steps=8)
    assert len(samples) == 8
    assert np.allclose(samples[-1], target)
    assert np.array_equal(simulation.qpos, simulation.home_qpos)


def test_measured_board_config_rebuilds_metric_geometry():
    sim = Simulation({"board": {"square_size_m": 0.04, "origin_m": [-0.16, 0.09, 0.03], "height_m": 0.03, "yaw_rad": math.pi / 2}})
    frame = next(g for g in sim.snapshot()["geoms"] if g["name"] == "board_frame")
    a1 = next(g for g in sim.snapshot()["geoms"] if g["name"] == "square_a1")
    assert sim.square_size == 0.04
    assert frame["size"][2] == 0.015
    assert np.allclose(a1["position"], [-0.18, 0.11, 0.0295])


def test_sample_opening_and_first_capture_waypoints_are_reachable():
    config = reachable_regression_fixture()
    sim = Simulation(config)
    board = config["board"]
    origin = np.array(board["origin_m"])
    size = board["square_size_m"]
    e7 = origin + [4.5 * size, 6.5 * size, 0.018]
    e5 = origin + [4.5 * size, 4.5 * size, 0.018]
    capture = np.array(config["captures"]["origin_m"]) + [0, 0, 0.018]
    seed = sim.qpos
    for square in [e7, e5, capture]:
        for height in [origin[2] + 0.10, square[2], origin[2] + 0.10]:
            target = [square[0], square[1], height]
            result = sim.solve_ik(target, seed=seed)
            assert result["reachable"], (target, result)
            assert result["collision_free"], (target, result["contacts"])
            seed = result["qpos"]


def test_evaluate_exact_jaw_pose_preserves_live_state(simulation):
    before = {key: getattr(simulation.data, key).copy() for key in ("qpos", "qvel", "ctrl", "site_xpos", "geom_xpos")}
    result = simulation.solve_ik([0.01905, 0.25145, 0.0434])
    q = result["qpos"]
    q[-1] = float(simulation.limits[-1, 0])
    evaluated = simulation.evaluate_qpos(q)
    expected = mujoco.MjData(simulation.model)
    expected.qpos[:] = q
    mujoco.mj_forward(simulation.model, expected)
    assert evaluated["contacts"] == simulation._contacts(expected)
    assert np.allclose(evaluated["tcp"], expected.site_xpos[simulation.site_id])
    assert evaluated["check_scope"] == "model_only"
    assert "chess_pieces" in evaluated["excluded_collision_objects"]
    assert not evaluated["hardware_executable"]
    for key, value in before.items():
        assert np.array_equal(getattr(simulation.data, key), value), key


def test_sampled_path_detects_self_collision_without_advancing_scene(simulation):
    before = simulation.qpos
    # A near-base grasp folds the fixed jaw into the shoulder model.
    folded = [-0.15632465, -1.01917424, 1.03409743, 1.55586298, 0.44588632, 0.8]
    assert simulation.evaluate_qpos(folded)["contacts"]
    result = simulation.check_path([before, folded, before])
    assert not result["collision_free"]
    assert result["first_collision_index"] == 1
    assert result["samples_checked"] == 3
    assert all(contact["sample_index"] == 1 for contact in result["contacts"])
    assert not result["continuous_collision_checked"]
    assert np.array_equal(simulation.qpos, before)
    with pytest.raises(ValueError, match="six-joint"):
        simulation.check_path([])
    with pytest.raises(ValueError, match="limits"):
        simulation.check_path([[10, 0, 0, 0, 0, 0]])
