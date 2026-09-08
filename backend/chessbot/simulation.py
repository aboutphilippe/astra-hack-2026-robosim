"""The real Menagerie SO-101 kinematic model, shared with the browser twin.

All distances are metres, joint positions radians, and quaternions wxyz.
Kinematic previews do not imply collision-free or hardware-safe motion.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco
import numpy as np

ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "so101"
JOINT_NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
DEFAULT_BOARD_ORIGIN = [-0.1524, 0.08, 0.0254]
CONTACT_PENETRATION_TOLERANCE_M = 0.0005


def _vec(value, length: int, label: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != (length,) or not np.all(np.isfinite(result)):
        raise ValueError(f"{label} must contain {length} finite numbers")
    return result


def _numbers(value) -> str:
    return " ".join(str(float(x)) for x in value)


def _skew(v: np.ndarray) -> np.ndarray:
    return np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])


class Simulation:
    """A mutable MuJoCo scene with a side-effect-free damped Jacobian IK solver.

    The SO-101 has five arm axes and one jaw axis. The grasp constraint aligns
    the gripperframe +X approach axis downward, leaving rotation around that
    axis free. Arbitrary six-dimensional end-effector poses are not supported.
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        board = self.config.get("board", {})
        robot = self.config.get("robot", {})
        self.board_origin = _vec(board.get("origin_m", DEFAULT_BOARD_ORIGIN), 3, "board origin")
        self.board_yaw = float(board.get("yaw_rad", 0))
        if not math.isfinite(self.board_yaw):
            raise ValueError("Board yaw must be finite")
        bc, bs = math.cos(self.board_yaw), math.sin(self.board_yaw)
        self.board_rotation = np.array([[bc, -bs, 0], [bs, bc, 0], [0, 0, 1]])
        self.square_size = float(board.get("square_size_m", 0.0381))
        self.border = float(board.get("border_m", 0.0254))
        self.thickness = float(board.get("height_m", board.get("thickness_m", 0.0254)))
        if not all(np.isfinite(x) and x > 0 for x in (self.square_size, self.border, self.thickness)):
            raise ValueError("Board dimensions must be positive finite metres")

        root = ET.parse(ASSET_DIR / "so101.xml").getroot()
        root.find("compiler").set("meshdir", str(ASSET_DIR / "assets"))
        world = root.find("worldbody")
        base = world.find("body[@name='base']")
        self.base_position = _vec(robot.get("base_position_m", [0, 0.50, 0.06]), 3, "robot base")
        base.set("pos", _numbers(self.base_position))
        yaw = float(robot.get("base_yaw_rad", -math.pi / 2))
        if not math.isfinite(yaw):
            raise ValueError("Robot base yaw must be finite")
        base.set("quat", _numbers([math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]))
        self.base_yaw = yaw
        for body in root.findall(".//body"):
            for index, geom in enumerate(body.findall("geom")):
                if not geom.get("name"):
                    geom.set("name", f"{body.get('name')}_geom_{index}")
        self._add_board(world)
        riser = float(robot.get("sample_riser_height_m", max(0, self.base_position[2])))
        if not math.isfinite(riser) or riser < 0:
            raise ValueError("Riser height must be finite and nonnegative")
        if riser:
            ET.SubElement(world, "geom", name="sample_robot_riser", type="box", pos=_numbers(self.base_position - [0, 0, riser / 2]), size=_numbers([0.055, 0.055, riser / 2]), rgba="0.23 0.26 0.28 1")
        ET.SubElement(world, "geom", name="table", type="box", pos="0 0.15 -0.022", size="0.7 0.65 0.02", rgba="0.16 0.18 0.19 1")
        ET.SubElement(world, "light", pos="0 0.3 1.5", dir="0 0 -1", diffuse="0.8 0.8 0.8")
        center = self.board_origin + self.board_rotation @ [4 * self.square_size, 4 * self.square_size, 0.8]
        ET.SubElement(world, "camera", name="top_camera", pos=_numbers(center), quat="1 0 0 0", fovy="55")
        self.model = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
        self.data = mujoco.MjData(self.model)
        self.site_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SITE, "gripperframe")
        self.joint_ids = np.array([mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, n) for n in JOINT_NAMES])
        self.q_indices = self.model.jnt_qposadr[self.joint_ids]
        self.dof_indices = self.model.jnt_dofadr[self.joint_ids]
        self.limits = self.model.jnt_range[self.joint_ids].copy()
        self.home_qpos = np.asarray(robot.get("home_qpos", [0, -0.5, 0.7, 0.65, 0, 0.8]), dtype=float)
        self.set_qpos(self.home_qpos)
        self._mesh_files = {Path(m.get("file")).stem: m.get("file") for m in root.findall("./asset/mesh")}

    def _add_board(self, world: ET.Element) -> None:
        width = 8 * self.square_size
        origin = self.board_origin
        quat = _numbers([math.cos(self.board_yaw / 2), 0, 0, math.sin(self.board_yaw / 2)])
        ET.SubElement(world, "geom", name="board_frame", type="box", pos=_numbers(origin + self.board_rotation @ [width / 2, width / 2, -self.thickness / 2]), quat=quat, size=_numbers([width / 2 + self.border, width / 2 + self.border, self.thickness / 2]), rgba="0.28 0.16 0.09 1")
        for rank in range(8):
            for file in range(8):
                # a1 is dark. The thin playing tiles sit flush at board top.
                color = "0.76 0.8 0.7 1" if (file + rank) % 2 else "0.22 0.32 0.29 1"
                ET.SubElement(world, "geom", name=f"square_{chr(97 + file)}{rank + 1}", type="box", pos=_numbers(origin + self.board_rotation @ [(file + 0.5) * self.square_size, (rank + 0.5) * self.square_size, -0.0005]), quat=quat, size=_numbers([self.square_size / 2, self.square_size / 2, 0.0005]), rgba=color)

    @property
    def qpos(self) -> np.ndarray:
        return self.data.qpos[self.q_indices].copy()

    def _validate_qpos(self, qpos) -> np.ndarray:
        q = _vec(qpos, 6, "qpos")
        if np.any(q < self.limits[:, 0] - 1e-8) or np.any(q > self.limits[:, 1] + 1e-8):
            raise ValueError("Joint target exceeds the SO-101 model limits")
        return np.clip(q, self.limits[:, 0], self.limits[:, 1])

    def set_qpos(self, qpos) -> None:
        """Set a kinematic preview pose without advancing dynamics or hardware."""
        q = self._validate_qpos(qpos)
        self.data.qpos[self.q_indices] = q
        self.data.qvel[:] = 0
        self.data.ctrl[:] = q
        mujoco.mj_forward(self.model, self.data)

    @staticmethod
    def _contact_check_scope() -> dict:
        return {"check_scope": "model_only", "contact_tolerance_m": CONTACT_PENETRATION_TOLERANCE_M,
                "excluded_collision_objects": ["chess_pieces", "humans", "unmodeled_obstacles"],
                "hardware_executable": False}

    def _evaluate_data(self, work) -> dict:
        contacts = self._contacts(work)
        approach = work.site_xmat[self.site_id].reshape(3, 3)[:, 0]
        return {"contacts": contacts, "collision_free": not contacts,
                "tcp": work.site_xpos[self.site_id].tolist(), "approach_axis": approach.tolist(),
                "orientation_error_rad": float(math.acos(np.clip(-approach[2], -1, 1))),
                **self._contact_check_scope()}

    def evaluate_qpos(self, qpos) -> dict:
        """Inspect an exact six-joint pose, including its requested jaw angle.

        Uses scratch MuJoCo state. Contacts include modeled arm/self/board/
        table/riser geometry only, with 0.5 mm penetration tolerance. Chess
        pieces, humans and unknown objects are absent from this contact model.
        """
        q = self._validate_qpos(qpos)
        work = mujoco.MjData(self.model)
        work.qpos[self.q_indices] = q
        mujoco.mj_forward(self.model, work)
        return self._evaluate_data(work)

    def check_path(self, qpos_list) -> dict:
        """Check supplied samples without changing the live scene.

        This checks discrete model contacts, not swept volumes or dynamic
        stability. Include the starting pose and the exact interpolation
        samples the preview will use. A contact-free result does not establish
        clearance from chess pieces or people, nor safety between samples.
        """
        samples = np.asarray(qpos_list, dtype=float)
        if samples.ndim != 2 or samples.shape[1] != 6 or not 1 <= len(samples) <= 10000:
            raise ValueError("Path must contain 1 to 10000 six-joint poses")
        samples = [self._validate_qpos(q) for q in samples]
        work = mujoco.MjData(self.model)
        contacts = []
        max_angle = 0.0
        first_collision = None
        for index, q in enumerate(samples):
            work.qpos[self.q_indices] = q
            mujoco.mj_forward(self.model, work)
            state = self._evaluate_data(work)
            max_angle = max(max_angle, state["orientation_error_rad"])
            if state["contacts"] and first_collision is None:
                first_collision = index
            contacts.extend({"sample_index": index, **contact} for contact in state["contacts"])
        return {"collision_free": not contacts, "contacts": contacts, "samples_checked": len(samples),
                "first_collision_index": first_collision, "max_orientation_error_rad": max_angle,
                "continuous_collision_checked": False, **self._contact_check_scope()}

    def step_targets(self, qpos, steps: int = 10) -> dict:
        """Advance real MuJoCo position actuators; return measured simulated pose.

        This includes gravity and contacts. It is separate from set_qpos and
        does not claim that an actuator reaches its target in the given time.
        """
        q = self._validate_qpos(qpos)
        if not isinstance(steps, int) or not 1 <= steps <= 10000:
            raise ValueError("steps must be an integer from 1 to 10000")
        self.data.ctrl[:] = q
        for _ in range(steps):
            mujoco.mj_step(self.model, self.data)
        mujoco.mj_forward(self.model, self.data)
        return self.snapshot()

    def interpolate_qpos(self, target, steps: int = 30, start=None) -> list[list[float]]:
        """Joint-limit-preserving smoothstep samples for kinematic animation.

        These samples are not a Cartesian or collision-checked trajectory.
        """
        goal = self._validate_qpos(target)
        initial = self.qpos if start is None else self._validate_qpos(start)
        if not isinstance(steps, int) or not 1 <= steps <= 10000:
            raise ValueError("steps must be an integer from 1 to 10000")
        return [(initial + (goal - initial) * (3 * t * t - 2 * t * t * t)).tolist() for t in np.linspace(0, 1, steps + 1)[1:]]

    def solve_ik(self, target, seed=None, downward: bool = True, max_iterations: int = 160, tolerance_m: float = 0.002, orientation_tolerance_rad: float = 0.12) -> dict:
        """Solve position and optionally downward approach, preserving live state.

        A success requires both position and orientation tolerances. Collision
        status is reported separately; this is not a motion safety certificate.
        """
        goal = _vec(target, 3, "IK target")
        initial = self.qpos if seed is None else self._validate_qpos(seed)
        if not 1 <= max_iterations <= 1000:
            raise ValueError("max_iterations must be between 1 and 1000")
        if not 0 < tolerance_m <= 0.02 or not 0 < orientation_tolerance_rad <= 0.5:
            raise ValueError("Invalid IK tolerances")
        work = mujoco.MjData(self.model)
        jacp = np.zeros((3, self.model.nv))
        jacr = np.zeros((3, self.model.nv))
        down = np.array([0.0, 0.0, -1.0])
        arm = self.dof_indices[:5]
        best = None
        # Deterministic restarts avoid treating a single singular seed as a
        # geometric impossibility. The caller seed is always attempted first.
        seeds = [initial.copy()]
        offset = goal - self.base_position
        c, s = math.cos(self.base_yaw), math.sin(self.base_yaw)
        local_x, local_y = c * offset[0] + s * offset[1], -s * offset[0] + c * offset[1]
        pan = np.clip(-math.atan2(local_y, local_x - 0.0388353), *self.limits[0])
        for shoulder, elbow, wrist in [(-0.5, 0.7, 0.65), (0.5, -0.7, -0.65), (-1.1, 1.3, 0.9), (0.8, 1.1, -0.8), (-1.3, 1.5, -1.3), (1.3, -1.5, 1.3), (0, -1.5, -1.3), (1.5, 1.5, 1.3)]:
            seeds.append(np.array([pan, shoulder, elbow, wrist, initial[4], initial[5]]))
        total_iterations = 0
        for start in seeds:
            q = np.clip(start, self.limits[:, 0], self.limits[:, 1])
            for _ in range(max_iterations):
                total_iterations += 1
                work.qpos[self.q_indices] = q
                mujoco.mj_kinematics(self.model, work)
                mujoco.mj_comPos(self.model, work)
                pos_error = goal - work.site_xpos[self.site_id]
                approach = work.site_xmat[self.site_id].reshape(3, 3)[:, 0]
                angle = float(math.acos(np.clip(approach @ down, -1, 1)))
                distance = float(np.linalg.norm(pos_error))
                score = distance + (0.08 * angle if downward else 0)
                if best is None or score < best[0]:
                    best = (score, q.copy(), distance, angle)
                if distance <= tolerance_m and (not downward or angle <= orientation_tolerance_rad):
                    break
                mujoco.mj_jacSite(self.model, work, jacp, jacr, self.site_id)
                if downward:
                    jac = np.vstack([jacp[:, arm], 0.08 * -_skew(approach) @ jacr[:, arm]])
                    error = np.concatenate([pos_error, 0.08 * (down - approach)])
                else:
                    jac, error = jacp[:, arm], pos_error
                damping = 0.004
                delta = jac.T @ np.linalg.solve(jac @ jac.T + damping**2 * np.eye(len(error)), error)
                delta *= min(1.0, 0.16 / max(float(np.max(np.abs(delta))), 1e-12))
                next_q = q.copy()
                next_q[:5] = np.clip(q[:5] + delta, self.limits[:5, 0], self.limits[:5, 1])
                if np.linalg.norm(next_q - q) < 1e-8:
                    break
                q = next_q
            if best[2] <= tolerance_m and (not downward or best[3] <= orientation_tolerance_rad):
                break
        _, solution, distance, angle = best
        work.qpos[self.q_indices] = solution
        mujoco.mj_forward(self.model, work)
        contacts = self._contacts(work)
        reachable = distance <= tolerance_m and (not downward or angle <= orientation_tolerance_rad)
        return {"reachable": bool(reachable), "error_m": distance, "orientation_error_rad": angle, "orientation_constrained": downward, "qpos": solution.tolist(), "tcp": work.site_xpos[self.site_id].tolist(), "target": goal.tolist(), "iterations": total_iterations, "contacts": contacts, "collision_free": not contacts, "trajectory_checked": False, "reason": "within_tolerance" if reachable else "No joint-limited solution found within position and approach tolerances"}

    def _contacts(self, data) -> list[dict]:
        result = []
        for contact in data.contact[:data.ncon]:
            first, second = int(contact.geom1), int(contact.geom2)
            # Static board layers intentionally overlap at a shared surface.
            if self.model.geom_bodyid[first] == 0 and self.model.geom_bodyid[second] == 0:
                continue
            if contact.dist < -CONTACT_PENETRATION_TOLERANCE_M:
                result.append({"geoms": [self.model.geom(first).name or f"geom_{first}", self.model.geom(second).name or f"geom_{second}"], "penetration_m": float(-contact.dist)})
        return result

    def snapshot(self) -> dict:
        geoms = []
        for index in range(self.model.ngeom):
            if self.model.geom_group[index] >= 3:
                continue
            kind = int(self.model.geom_type[index])
            rotation = self.data.geom_xmat[index].reshape(3, 3).copy()
            position = self.data.geom_xpos[index].copy()
            mesh = None
            if kind == mujoco.mjtGeom.mjGEOM_MESH:
                mesh_id = int(self.model.geom_dataid[index])
                # MuJoCo centers and principal-axis-aligns meshes at compile
                # time. Undo that transform for the browser's raw STL loader.
                mesh_rotation = np.zeros(9)
                mujoco.mju_quat2Mat(mesh_rotation, self.model.mesh_quat[mesh_id])
                rotation = rotation @ mesh_rotation.reshape(3, 3).T
                position -= rotation @ self.model.mesh_pos[mesh_id]
                name = self.model.mesh(mesh_id).name
                mesh = f"/assets/so101/assets/{self._mesh_files[name]}"
            quaternion = np.zeros(4)
            mujoco.mju_mat2Quat(quaternion, rotation.ravel())
            mat = int(self.model.geom_matid[index])
            color = self.model.mat_rgba[mat] if mat >= 0 else self.model.geom_rgba[index]
            item = {"name": self.model.geom(index).name or f"geom_{index}", "type": mujoco.mjtGeom(kind).name.removeprefix("mjGEOM_").lower(), "position": position.tolist(), "quaternion": quaternion.tolist(), "size": self.model.geom_size[index].tolist(), "color": color.tolist()}
            if mesh:
                item["mesh"] = mesh
            geoms.append(item)
        rotation = self.data.site_xmat[self.site_id].reshape(3, 3)
        return {"joints": [{"name": name, "position": float(self.qpos[i]), "min": float(self.limits[i, 0]), "max": float(self.limits[i, 1])} for i, name in enumerate(JOINT_NAMES)], "qpos": self.qpos.tolist(), "tcp": self.data.site_xpos[self.site_id].tolist(), "approach_axis": rotation[:, 0].tolist(), "geoms": geoms, "contacts": self._contacts(self.data), "simulation_time": float(self.data.time), "model": "MuJoCo Menagerie SO-101", "units": {"position": "metres", "joints": "radians", "quaternion": "wxyz"}}
