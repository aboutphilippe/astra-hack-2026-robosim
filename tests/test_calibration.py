import numpy as np
import pytest
from chessbot.calibration import BoardCalibration, measure_board_rgbd, piece_heights_rgbd, register_robot_rgbd

CORNERS = {"a1_outer": [100, 100], "h1_outer": [500, 100], "h8_outer": [500, 500], "a8_outer": [100, 500]}


def test_camera_orientation_is_explicit_and_metric():
    calibration = BoardCalibration({"board": {"square_size_m": 0.04}})
    calibration.fit_camera(CORNERS)
    assert calibration.pixel_to_square([125, 125]) == "a1"
    assert calibration.pixel_to_square([475, 125]) == "h1"
    assert calibration.pixel_to_square([125, 475]) == "a8"
    assert calibration.pixel_to_square([475, 475]) == "h8"
    assert calibration.pixel_to_board([300, 300]) == pytest.approx([0.16, 0.16])
    assert calibration.pixel_to_square([99, 125]) is None
    assert calibration.pixel_to_square([500, 125]) is None
    assert not calibration.status()["robot_calibrated"]


def test_camera_accepts_other_physical_image_orientations():
    calibration = BoardCalibration()
    calibration.fit_camera([[500, 500], [100, 500], [100, 100], [500, 100]])
    assert calibration.pixel_to_square([475, 475]) == "a1"
    assert calibration.pixel_to_square([475, 125]) == "a8"


@pytest.mark.parametrize("points", [
    [[0, 0], [0, 0], [1, 1], [0, 1]],
    [[0, 0], [1, 1], [1, 0], [0, 1]],
    [[0, 0], [1, 0], [2, 0], [3, 0]],
    [[0, 0], [3, 0], [1, 0.5], [0, 3]],
])
def test_camera_rejects_degenerate_or_crossed_corners(points):
    calibration = BoardCalibration()
    with pytest.raises(ValueError):
        calibration.fit_camera(points)
    assert not calibration.status()["camera_calibrated"]


def test_nominal_origin_does_not_calibrate_robot():
    calibration = BoardCalibration({"board": {"origin_m": [1, 2, 3]}})
    assert not calibration.status()["ready_for_robot"]
    with pytest.raises(ValueError, match="required"):
        calibration.board_to_robot([0, 0, 0])


def test_rigid_robot_fit_recovers_rotation_translation_and_reports_residuals():
    calibration = BoardCalibration()
    rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float)
    translation = np.array([0.1, 0.2, 0.03])
    board = np.array([[0, 0, 0], [0.3, 0, 0], [0, 0.3, 0], [0.3, 0.3, 0]])
    anchors = [{"board_m": p.tolist(), "robot_m": (rotation @ p + translation).tolist()} for p in board]
    result = calibration.fit_robot(anchors)
    assert result["rmse_m"] < 1e-10
    assert np.array(result["rotation"]) == pytest.approx(rotation)
    assert calibration.board_to_robot([0.04, 0.08, 0.02]) == pytest.approx([0.02, 0.24, 0.05])
    assert calibration.status()["robot_calibrated"]
    assert not calibration.status()["camera_calibrated"]


def test_robot_rejects_collinear_or_nonrigid_data_and_invalidates_previous_fit():
    calibration = BoardCalibration()
    with pytest.raises(ValueError, match="noncollinear"):
        calibration.fit_robot([{"board_m": [i, 0, 0], "robot_m": [i, 1, 0]} for i in range(3)])
    board = [[0, 0, 0], [0.3, 0, 0], [0, 0.3, 0]]
    anchors = [{"board_m": point, "robot_m": point} for point in board]
    calibration.fit_robot(anchors)
    anchors[2] = {"board_m": board[2], "robot_m": [0, 0.6, 0]}
    with pytest.raises(ValueError, match="RMSE"):
        calibration.fit_robot(anchors)
    assert not calibration.status()["robot_calibrated"]


def rgbd_scene():
    depth = np.ones((600, 600), dtype=float) * 0.8
    camera = {"fx": 800.0, "fy": 800.0, "cx": 300.0, "cy": 300.0}
    return depth, camera


def test_rgbd_measures_board_and_ignores_piece_top_outliers():
    depth, camera = rgbd_scene()
    depth[115:140, 115:140] = 0.75  # A 5 cm object in a1.
    measured = measure_board_rgbd(CORNERS, depth, camera)
    assert measured["square_size_m"] == pytest.approx(0.05, abs=1e-5)
    assert measured["board_width_m"] == pytest.approx(0.4, abs=1e-5)
    assert measured["quality"]["plane_rmse_m"] < 1e-5
    assert measured["board_up_sign"] == -1  # Pixel axes run right/down.
    assert measured["plane"]["normal_camera"] == pytest.approx([0, 0, -1])
    assert np.linalg.det(np.array(measured["board_to_camera"])[:3, :3]) == pytest.approx(1)
    heights = piece_heights_rgbd(depth, camera, measured)
    assert heights["a1"]["height_m"] == pytest.approx(0.05, abs=1e-5)
    assert heights["h8"]["height_m"] == 0
    depth[450:501, 450:501] = 0
    missing = piece_heights_rgbd(depth, camera, measured)
    assert missing["h8"]["height_m"] is None


def test_rgbd_requires_measured_depth_and_square_geometry():
    depth, camera = rgbd_scene()
    with pytest.raises(ValueError, match="usable"):
        measure_board_rgbd(CORNERS, depth * 0, camera)
    with pytest.raises(ValueError, match="not square"):
        measure_board_rgbd([[100, 100], [500, 100], [500, 300], [100, 300]], depth, camera)
    depth[:] = 0
    depth[200:250, 200:250] = 0.8
    with pytest.raises(ValueError, match="span"):
        measure_board_rgbd(CORNERS, depth, camera, min_depth_samples=20)


def test_rgbd_size_changes_with_depth_without_nominal_dimensions():
    depth, camera = rgbd_scene()
    measured = measure_board_rgbd(CORNERS, depth * 1.5, camera)
    assert measured["square_size_m"] == pytest.approx(0.075, abs=1e-5)


def robot_landmarks(camera):
    rotation = np.diag([1.0, -1.0, -1.0])
    translation = np.array([0.3, 0.4, 0.8])
    landmarks = []
    for pixel in [[150, 150], [450, 150], [150, 450], [450, 450]]:
        camera_point = np.array([(pixel[0] - camera["cx"]) / camera["fx"],
                                 (pixel[1] - camera["cy"]) / camera["fy"], 1]) * 0.8
        landmarks.append({"pixel": pixel, "robot_m": (rotation @ camera_point + translation).tolist()})
    return landmarks, rotation, translation


def test_rgbd_robot_registration_recovers_camera_pose_from_known_landmarks():
    depth, camera = rgbd_scene()
    landmarks, rotation, translation = robot_landmarks(camera)
    result = register_robot_rgbd(landmarks, depth, camera)
    assert np.array(result["rotation"]) == pytest.approx(rotation)
    assert result["translation_m"] == pytest.approx(translation)
    assert result["rmse_m"] < 1e-10
    measured = measure_board_rgbd(CORNERS, depth, camera)
    board_to_robot = np.array(result["camera_to_robot"]) @ np.array(measured["board_to_camera"])
    assert board_to_robot[:3, 3] == pytest.approx([0.1, 0.6, 0.0])


def test_rgbd_robot_registration_rejects_missing_depth_discontinuity_and_bad_correspondence():
    depth, camera = rgbd_scene()
    landmarks, _, _ = robot_landmarks(camera)
    missing = depth.copy()
    missing[148:153, 148:153] = 0
    with pytest.raises(ValueError, match="insufficient measured depth"):
        register_robot_rgbd(landmarks, missing, camera)
    discontinuous = depth.copy()
    discontinuous[148:150, 148:153] = 0.6
    with pytest.raises(ValueError, match="discontinuity"):
        register_robot_rgbd(landmarks, discontinuous, camera)
    landmarks[0]["robot_m"][0] += 0.1
    with pytest.raises(ValueError, match="RMSE"):
        register_robot_rgbd(landmarks, depth, camera)
