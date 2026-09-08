"""Measured camera homography and rigid board-to-robot calibration.

Board-local origin is the outer a1 playing-grid corner, +x toward h1,
+y toward a8 and +z above the board. Camera corners are explicitly ordered
a1_outer, h1_outer, h8_outer, a8_outer; a1 may appear at camera top-left.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np

CORNER_NAMES = ("a1_outer", "h1_outer", "h8_outer", "a8_outer")


def _points(value: Any, dimensions: int, name: str) -> np.ndarray:
    try:
        points = np.asarray(value, dtype=float)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} must contain numeric points") from exc
    if points.ndim != 2 or points.shape[1] != dimensions or not np.isfinite(points).all():
        raise ValueError(f"{name} must contain finite {dimensions}D points")
    return points


def _rgbd_inputs(depth_m: np.ndarray, intrinsics: dict) -> tuple[np.ndarray, dict[str, float]]:
    depth = np.asarray(depth_m, dtype=float)
    if depth.ndim != 2 or min(depth.shape) < 2:
        raise ValueError("Aligned depth must be a two-dimensional image in metres")
    try:
        camera = {name: float(intrinsics[name]) for name in ("fx", "fy", "cx", "cy")}
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Camera intrinsics require fx, fy, cx, cy for the aligned depth image") from exc
    if not all(np.isfinite(list(camera.values()))) or camera["fx"] <= 0 or camera["fy"] <= 0:
        raise ValueError("Camera focal lengths must be positive and all intrinsics finite")
    return depth, camera


def _rays(pixels: np.ndarray, camera: dict) -> np.ndarray:
    return np.column_stack(((pixels[:, 0] - camera["cx"]) / camera["fx"], (pixels[:, 1] - camera["cy"]) / camera["fy"], np.ones(len(pixels))))


def measure_board_rgbd(
    corners_px: list | dict, depth_m: np.ndarray, intrinsics: dict, *,
    plane_tolerance_m: float = 0.003, max_edge_error_ratio: float = 0.05,
    min_depth_samples: int = 48,
) -> dict:
    """Measure the playing grid from RGB-aligned metric depth and camera intrinsics.

    A deterministic RANSAC fit estimates the dominant board surface from depth
    inside the selected grid, rejecting chess-piece tops. Corner rays intersect
    this plane, so corner/rim depth readings do not define the board height.
    The input image must already be aligned to the image used to select corners.
    This function does not substitute nominal sizes for missing measurements.
    """
    depth, camera = _rgbd_inputs(depth_m, intrinsics)
    if not np.isfinite(plane_tolerance_m) or plane_tolerance_m <= 0:
        raise ValueError("Plane tolerance must be positive and finite")
    if not 0 < max_edge_error_ratio < 1 or min_depth_samples < 3:
        raise ValueError("Geometry tolerance must be between zero and one; at least three depth samples are required")
    # Reuse corner correspondence and convexity validation; the temporary unit
    # homography is used only to sample inside the quadrilateral, never as a size.
    selector = BoardCalibration({"board": {"square_size_m": 1.0}})
    selector.fit_camera(corners_px)
    points = np.array([selector._camera_result["corners_px"][name] for name in CORNER_NAMES])
    height, width = depth.shape
    if np.any(points < 0) or np.any(points[:, 0] >= width) or np.any(points[:, 1] >= height):
        raise ValueError("All board corners must lie inside the aligned depth image")
    xs = np.unique(np.linspace(np.ceil(points[:, 0].min()), np.floor(points[:, 0].max()), 52).astype(int))
    ys = np.unique(np.linspace(np.ceil(points[:, 1].min()), np.floor(points[:, 1].max()), 52).astype(int))
    grid_x, grid_y = np.meshgrid(xs, ys)
    pixels = np.column_stack((grid_x.ravel(), grid_y.ravel()))
    local_h = np.column_stack((pixels, np.ones(len(pixels)))) @ selector.camera_to_board.T
    local = local_h[:, :2] / local_h[:, 2, None]
    inside = np.all((local > 0.16) & (local < 7.84), axis=1)
    pixels = pixels[inside]
    depths = depth[pixels[:, 1], pixels[:, 0]]
    valid = np.isfinite(depths) & (depths > 0)
    sample_pixels, depths = pixels[valid], depths[valid]
    if len(depths) < min_depth_samples:
        raise ValueError(f"Only {len(depths)} usable board depth samples; need at least {min_depth_samples}")
    cloud = _rays(sample_pixels, camera) * depths[:, None]
    rng = np.random.default_rng(0)
    best_inliers = None
    best_count = 0
    for _ in range(180):
        a, b, c = cloud[rng.choice(len(cloud), 3, replace=False)]
        normal = np.cross(b - a, c - a)
        length = np.linalg.norm(normal)
        if length < 1e-10:
            continue
        normal /= length
        distances = np.abs((cloud - a) @ normal)
        inliers = distances <= plane_tolerance_m
        if int(inliers.sum()) > best_count:
            best_count, best_inliers = int(inliers.sum()), inliers
    if best_inliers is None or best_count < max(min_depth_samples, 0.45 * len(cloud)):
        raise ValueError("No dominant board plane was measured; clear occlusions or recapture aligned depth")
    plane_cloud = cloud[best_inliers]
    center = plane_cloud.mean(axis=0)
    _, singular, vt = np.linalg.svd(plane_cloud - center, full_matrices=False)
    if singular[1] < 1e-6:
        raise ValueError("Measured board depth points are collinear")
    normal = vt[-1]
    if np.dot(normal, center) > 0:
        normal = -normal  # Physical exposed surface faces the overhead camera.
    offset = -float(normal @ center)
    corner_rays = _rays(points, camera)
    denominator = corner_rays @ normal
    if np.any(np.abs(denominator) < 1e-8):
        raise ValueError("Board corners are too close to the camera horizon")
    corner_depths = -offset / denominator
    if np.any(corner_depths <= 0):
        raise ValueError("Board plane projects behind the camera")
    corners_camera = corner_rays * corner_depths[:, None]
    edges = np.roll(corners_camera, -1, axis=0) - corners_camera
    edge_lengths = np.linalg.norm(edges, axis=1)
    mean_edge = float(edge_lengths.mean())
    edge_error = float(np.max(np.abs(edge_lengths - mean_edge)) / mean_edge)
    directions = edges / edge_lengths[:, None]
    right_angle_error = float(max(abs(directions[i] @ directions[(i + 1) % 4]) for i in range(4)))
    if edge_error > max_edge_error_ratio or right_angle_error > max_edge_error_ratio:
        raise ValueError(f"Measured grid is not square (edge error {edge_error:.1%}, angle cosine error {right_angle_error:.3f}); verify corner labels and depth alignment")
    # Require surface support across both board axes, avoiding a fit to only a
    # small surviving patch when the rest of the depth image is missing.
    inlier_local = local[inside][valid][best_inliers]
    coverage = np.ptp(inlier_local, axis=0) / 8
    if np.any(coverage < 0.6):
        raise ValueError("Measured plane does not span enough of the board in both axes")
    x_axis = corners_camera[1] - corners_camera[0]
    x_axis /= np.linalg.norm(x_axis)
    y_axis = corners_camera[3] - corners_camera[0]
    y_axis -= np.dot(y_axis, x_axis) * x_axis
    y_axis /= np.linalg.norm(y_axis)
    z_axis = np.cross(x_axis, y_axis)
    transform = np.eye(4)
    transform[:3, :3] = np.column_stack((x_axis, y_axis, z_axis))
    transform[:3, 3] = corners_camera[0]
    rmse = float(np.sqrt(np.mean(((plane_cloud @ normal) + offset) ** 2)))
    up_sign = 1 if normal @ z_axis > 0 else -1
    return {
        "source": "measured_aligned_rgbd",
        "square_size_m": mean_edge / 8,
        "board_width_m": mean_edge,
        "corners_px": {name: point.tolist() for name, point in zip(CORNER_NAMES, points)},
        "corners_camera_m": {name: point.tolist() for name, point in zip(CORNER_NAMES, corners_camera)},
        "board_to_camera": transform.tolist(),
        "board_up_sign": up_sign,
        "plane": {"normal_camera": normal.tolist(), "offset_m": offset},
        "quality": {"valid_samples": len(cloud), "inlier_samples": best_count, "inlier_fraction": best_count / len(cloud), "plane_rmse_m": rmse, "edge_lengths_m": edge_lengths.tolist(), "edge_error_ratio": edge_error, "right_angle_cosine_error": right_angle_error, "coverage_xy": coverage.tolist()},
        "coordinate_note": "Board x follows a1 to h1 and y follows a1 to a8. The transform is right-handed; board_up_sign gives the local z direction toward the camera/exposed board surface.",
        "limitations": ["Depth must be registered to the color image with matching intrinsics and converted to metres by the camera driver.", "The selected corners must be the playing-grid corners, excluding the rim.", "A dominant flat surface and adequate depth coverage are required; measure robot-base landmarks separately."],
    }


def piece_heights_rgbd(
    depth_m: np.ndarray, intrinsics: dict, measurement: dict, *,
    percentile: float = 95.0, min_samples_per_square: int = 12,
    noise_floor_m: float = 0.004,
) -> dict[str, dict]:
    """Per-square surface heights above a measured board plane, in metres.

    Heights are geometric observations, not piece identities or occupancy
    confidence. Missing depth returns null; it never means an empty square.
    """
    depth, camera = _rgbd_inputs(depth_m, intrinsics)
    if not 50 <= percentile <= 100 or min_samples_per_square < 1 or noise_floor_m < 0:
        raise ValueError("Invalid height percentile, sample count, or depth noise floor")
    if measurement.get("source") != "measured_aligned_rgbd":
        raise ValueError("Piece height extraction requires a measured RGB-D board plane")
    calibration = BoardCalibration({"board": {"square_size_m": measurement["square_size_m"]}})
    calibration.fit_camera(measurement["corners_px"])
    normal = np.asarray(measurement["plane"]["normal_camera"], dtype=float)
    offset = float(measurement["plane"]["offset_m"])
    image_height, image_width = depth.shape
    ys, xs = np.mgrid[0:image_height:2, 0:image_width:2]
    pixels = np.column_stack((xs.ravel(), ys.ravel()))
    values = depth[pixels[:, 1], pixels[:, 0]]
    valid = np.isfinite(values) & (values > 0)
    pixels, values = pixels[valid], values[valid]
    # Project the depth sample to the physical board plane before assigning its
    # square: image homography alone misassigns tall pieces under perspective.
    cloud = _rays(pixels, camera) * values[:, None]
    heights = cloud @ normal + offset
    transform = np.asarray(measurement["board_to_camera"], dtype=float)
    local = (cloud - transform[:3, 3]) @ transform[:3, :3]
    square_size = float(measurement["square_size_m"])
    xy = local[:, :2] / square_size
    result = {}
    for rank in range(8):
        for file in range(8):
            # Ignore square boundaries and very negative depth outliers.
            selected = heights[(xy[:, 0] >= file + 0.08) & (xy[:, 0] <= file + 0.92) & (xy[:, 1] >= rank + 0.08) & (xy[:, 1] <= rank + 0.92) & (heights >= -noise_floor_m * 2)]
            count = len(selected)
            height = max(0.0, float(np.percentile(selected, percentile))) if count >= min_samples_per_square else None
            if height is not None and height <= noise_floor_m:
                height = 0.0
            result[f"{'abcdefgh'[file]}{rank + 1}"] = {"height_m": height, "valid_samples": count, "status": "measured" if height is not None else "missing_depth"}
    return result


def register_robot_rgbd(
    landmarks: list[dict], depth_m: np.ndarray, intrinsics: dict, *,
    sample_radius_px: int = 2, max_rmse_m: float = 0.005,
    max_depth_spread_m: float = 0.008,
) -> dict:
    """Register the camera to robot base using known, rigid base landmarks.

    Each landmark supplies {'pixel': [u,v], 'robot_m': [x,y,z]} and optionally
    'name'. robot_m must come from identified CAD points or direct measurement
    in the robot base frame, never a guessed image location. Depth is sampled
    locally and deprojected with the aligned image's intrinsic matrix.
    Articulating arm landmarks are unsuitable unless their current robot-frame
    coordinates are independently known. No physical device is opened here.
    """
    depth, camera = _rgbd_inputs(depth_m, intrinsics)
    if not isinstance(landmarks, list) or len(landmarks) < 3:
        raise ValueError("At least three known noncollinear robot-base landmarks are required")
    if isinstance(sample_radius_px, bool) or not isinstance(sample_radius_px, int) or not 0 <= sample_radius_px <= 10:
        raise ValueError("Depth sample radius must be an integer from zero to ten pixels")
    if not np.isfinite(max_depth_spread_m) or max_depth_spread_m <= 0:
        raise ValueError("Maximum local depth spread must be positive and finite")
    samples, pairs = [], []
    image_height, image_width = depth.shape
    for index, landmark in enumerate(landmarks):
        try:
            pixel = _points([landmark["pixel"]], 2, "Landmark pixel")[0]
            robot = _points([landmark["robot_m"]], 3, "Known robot-base point")[0]
        except (KeyError, TypeError) as exc:
            raise ValueError("Each robot landmark requires pixel and known robot_m coordinates") from exc
        x, y = np.rint(pixel).astype(int)
        if not (0 <= pixel[0] < image_width and 0 <= pixel[1] < image_height and 0 <= x < image_width and 0 <= y < image_height):
            raise ValueError(f"Robot landmark {index} lies outside the aligned image")
        patch = depth[max(0, y - sample_radius_px):min(image_height, y + sample_radius_px + 1),
                      max(0, x - sample_radius_px):min(image_width, x + sample_radius_px + 1)]
        valid = patch[np.isfinite(patch) & (patch > 0)]
        if len(valid) < max(1, int(np.ceil(patch.size * 0.6))):
            raise ValueError(f"Robot landmark {index} has insufficient measured depth")
        spread = float(np.percentile(valid, 90) - np.percentile(valid, 10))
        if spread > max_depth_spread_m:
            raise ValueError(f"Robot landmark {index} crosses a depth discontinuity; select a clear rigid surface point")
        median_depth = float(np.median(valid))
        camera_point = _rays(np.asarray([pixel]), camera)[0] * median_depth
        pairs.append({"board_m": camera_point.tolist(), "robot_m": robot.tolist()})
        samples.append({"name": str(landmark.get("name", f"landmark_{index}")),
                        "pixel": pixel.tolist(), "camera_m": camera_point.tolist(),
                        "robot_m": robot.tolist(), "depth_m": median_depth,
                        "valid_depth_samples": len(valid), "depth_spread_m": spread})
    # Reuse the same proper rigid-fit mathematics and validation as board
    # anchors. Here its source coordinates are camera coordinates explicitly.
    fit = BoardCalibration({"calibration": {"robot_max_rmse_m": max_rmse_m}}).fit_robot(pairs)
    return {
        "source": "measured_robot_base_landmarks_rgbd",
        "camera_to_robot": fit["matrix"],
        "rotation": fit["rotation"], "translation_m": fit["translation_m"],
        "rmse_m": fit["rmse_m"], "max_error_m": fit["max_error_m"],
        "residuals_m": fit["residuals_m"], "anchor_count": fit["anchor_count"],
        "landmarks": samples,
        "camera_frame": "+x image right, +y image down, +z optical depth forward",
        "robot_frame": "Known robot-base landmark frame supplied by the caller",
        "limitations": ["Robot landmark identities and robot_m coordinates require known geometry or direct measurement.",
                       "A low fit residual does not verify landmark identity, camera-to-depth alignment, servo zero offsets, or robot motion safety."],
    }


class BoardCalibration:
    def __init__(self, config: dict | None = None):
        self.config = deepcopy(config or {})
        self.square_size_m = float(self.config.get("board", {}).get("square_size_m", 0.0381))
        if not np.isfinite(self.square_size_m) or self.square_size_m <= 0:
            raise ValueError("Board square size must be positive and finite")
        self.camera_to_board: np.ndarray | None = None
        self.board_to_robot_matrix: np.ndarray | None = None
        self._camera_result: dict | None = None
        self._robot_result: dict | None = None

    def status(self) -> dict:
        return {
            "camera_calibrated": self.camera_to_board is not None,
            "robot_calibrated": self.board_to_robot_matrix is not None,
            "ready_for_robot": self.camera_to_board is not None and self.board_to_robot_matrix is not None,
            "board_frame": "a1 outer grid corner; +x toward h1; +y toward a8; +z above board",
            "corner_order": list(CORNER_NAMES),
            "camera": deepcopy(self._camera_result),
            "robot": deepcopy(self._robot_result),
        }

    def fit_camera(self, corners_px: list | dict) -> dict:
        """Fit four manually identified outer grid corners, excluding the border.

        The points must follow the named perimeter order and form a convex
        quadrilateral. A failed replacement invalidates the previous fit.
        """
        self.camera_to_board = None
        self._camera_result = None
        if isinstance(corners_px, dict):
            if set(corners_px) != set(CORNER_NAMES):
                raise ValueError(f"Identify exactly these outer grid corners: {', '.join(CORNER_NAMES)}")
            corners_px = [corners_px[name] for name in CORNER_NAMES]
        points = _points(corners_px, 2, "Camera corners")
        if points.shape != (4, 2):
            raise ValueError("Exactly four outer grid corners are required")
        span = float(np.max(np.ptp(points, axis=0)))
        if span <= 1e-6:
            raise ValueError("Camera corners must be distinct")
        if any(np.linalg.norm(points[i] - points[j]) <= span * 1e-7 for i in range(4) for j in range(i)):
            raise ValueError("Camera corners must be distinct")
        edges = np.roll(points, -1, axis=0) - points
        crosses = [edges[i, 0] * edges[(i + 1) % 4, 1] - edges[i, 1] * edges[(i + 1) % 4, 0] for i in range(4)]
        epsilon = span * span * 1e-7
        if not (all(c > epsilon for c in crosses) or all(c < -epsilon for c in crosses)):
            raise ValueError("Camera corners must form a convex, non-crossing quadrilateral in the named order")

        # Normalize pixel coordinates before solving to avoid large-pixel conditioning.
        center = points.mean(axis=0)
        normalized = (points - center) / span
        board_width = 8 * self.square_size_m
        targets = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float)
        matrix, right = [], []
        for (x, y), (u, v) in zip(normalized, targets):
            matrix.extend([[x, y, 1, 0, 0, 0, -u*x, -u*y], [0, 0, 0, x, y, 1, -v*x, -v*y]])
            right.extend([u, v])
        a = np.asarray(matrix)
        if np.linalg.cond(a) > 1e10:
            raise ValueError("Camera corners are too poorly conditioned for calibration")
        homography_normalized = np.append(np.linalg.solve(a, right), 1).reshape(3, 3)
        normalize = np.array([[1/span, 0, -center[0]/span], [0, 1/span, -center[1]/span], [0, 0, 1]])
        homography = np.diag([board_width, board_width, 1]) @ homography_normalized @ normalize
        homography /= homography[2, 2] if abs(homography[2, 2]) > 1e-12 else np.linalg.norm(homography)
        self.camera_to_board = homography
        self._camera_result = {
            "homography_pixel_to_board_m": homography.tolist(),
            "corners_px": {name: point.tolist() for name, point in zip(CORNER_NAMES, points)},
            "square_size_m": self.square_size_m,
            "source": "measured_outer_grid_corners",
        }
        return deepcopy(self._camera_result)

    def pixel_to_board(self, pixel: list[float] | tuple[float, float]) -> list[float]:
        if self.camera_to_board is None:
            raise ValueError("Camera calibration is required")
        point = _points([pixel], 2, "Pixel")[0]
        projected = self.camera_to_board @ np.array([point[0], point[1], 1.0])
        if abs(projected[2]) < 1e-12:
            raise ValueError("Pixel projects to infinity")
        return (projected[:2] / projected[2]).tolist()

    def pixel_to_square(self, pixel: list[float] | tuple[float, float]) -> str | None:
        x, y = np.asarray(self.pixel_to_board(pixel)) / self.square_size_m
        epsilon = 1e-9
        if x < -epsilon or y < -epsilon or x >= 8 - epsilon or y >= 8 - epsilon:
            return None
        file, rank = int(np.floor(max(0.0, x) + epsilon)), int(np.floor(max(0.0, y) + epsilon))
        return f"{'abcdefgh'[file]}{rank + 1}"

    def fit_robot(self, anchors: list[dict]) -> dict:
        """Fit a proper rigid transform from >=3 measured noncollinear pairs.

        Each anchor is {'board_m': [x,y,z], 'robot_m': [x,y,z]}. Board-local
        points are measured from the outer a1 corner at the board top plane.
        Nominal config origins are never accepted as proof of calibration.
        """
        self.board_to_robot_matrix = None
        self._robot_result = None
        if not isinstance(anchors, list) or len(anchors) < 3:
            raise ValueError("At least three measured noncollinear anchor pairs are required")
        try:
            board = _points([anchor["board_m"] for anchor in anchors], 3, "Board anchors")
            robot = _points([anchor["robot_m"] for anchor in anchors], 3, "Robot anchors")
        except (KeyError, TypeError) as exc:
            raise ValueError("Each anchor requires board_m and robot_m coordinate triples") from exc
        board_center, robot_center = board.mean(axis=0), robot.mean(axis=0)
        board_zero, robot_zero = board - board_center, robot - robot_center
        if np.linalg.matrix_rank(board_zero, tol=1e-6) < 2 or np.linalg.matrix_rank(robot_zero, tol=1e-6) < 2:
            raise ValueError("Calibration anchors must be noncollinear and separated by more than one micrometre")
        u, _, vt = np.linalg.svd(board_zero.T @ robot_zero)
        rotation = vt.T @ u.T
        if np.linalg.det(rotation) < 0:
            vt[-1] *= -1
            rotation = vt.T @ u.T
        translation = robot_center - rotation @ board_center
        predicted = board @ rotation.T + translation
        residuals = np.linalg.norm(predicted - robot, axis=1)
        rmse = float(np.sqrt(np.mean(residuals ** 2)))
        threshold = float(self.config.get("calibration", {}).get("robot_max_rmse_m", 0.005))
        if not np.isfinite(threshold) or threshold <= 0:
            raise ValueError("Robot calibration RMSE threshold must be positive and finite")
        if rmse > threshold:
            raise ValueError(f"Robot calibration RMSE {rmse:.6f} m exceeds {threshold:.6f} m; remeasure anchors")
        transform = np.eye(4)
        transform[:3, :3], transform[:3, 3] = rotation, translation
        self.board_to_robot_matrix = transform
        self._robot_result = {
            "rotation": rotation.tolist(),
            "translation_m": translation.tolist(),
            "matrix": transform.tolist(),
            "rmse_m": rmse,
            "max_error_m": float(residuals.max()),
            "residuals_m": residuals.tolist(),
            "anchor_count": len(anchors),
            "source": "measured_anchor_pairs",
        }
        return deepcopy(self._robot_result)

    def board_to_robot(self, point: list[float] | tuple[float, float, float]) -> list[float]:
        if self.board_to_robot_matrix is None:
            raise ValueError("Measured board-to-robot calibration is required")
        value = _points([point], 3, "Board point")[0]
        return (self.board_to_robot_matrix @ np.append(value, 1))[:3].tolist()
