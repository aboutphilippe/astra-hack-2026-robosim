"""Single authoritative local cell shared by React and Codex MCP clients."""
from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Literal
from uuid import uuid4

import chess
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .calibration import BoardCalibration
from .chess_logic import ChessGame
from .config import ROOT, load_config, validate_board
from .hardware import capture_top, capture_wrist, discover
from .simulation import Simulation


class MoveRequest(BaseModel):
    uci: str = Field(pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")


class RobotRequest(BaseModel):
    execute: bool = True
    uci: str | None = None


class CornersRequest(BaseModel):
    corners_px: list[list[float]] = Field(min_length=4, max_length=4)


class BoardRequest(BaseModel):
    square_size_m: float = Field(ge=0.015, le=0.08)
    origin_m: list[float] = Field(min_length=3, max_length=3)


class CameraRequest(BaseModel):
    camera: Literal["top", "wrist"] = "top"


class ObservationRequest(BaseModel):
    occupancy: dict[str, str | None]
    confidence: float = Field(ge=0, le=1)
    hand_clear: bool = False
    base_fen: str
    frame_id: str
    commit: bool = False


class IKRequest(BaseModel):
    target: list[float] = Field(min_length=3, max_length=3)
    downward: bool = True


class AnchorsRequest(BaseModel):
    anchors: list[dict] = Field(min_length=3)


class LandmarksRequest(BaseModel):
    landmarks: list[dict] = Field(min_length=3)


class Cell:
    def __init__(self, config: dict | None = None):
        self.config = deepcopy(config or load_config())
        self.game = ChessGame(self.config)
        self.simulation = Simulation(self.config)
        self.calibration = BoardCalibration(self.config)
        self.status = "ready"
        self.plan = None
        self.last_move = None
        self.events = []
        self.task = None
        self.generation = 0
        self.piece_overrides = {}
        self.latest_frame = None
        self.last_observation = None
        self.measurement = None
        self.robot_registration = None
        self.piece_heights = {}
        self.log("Simulation ready. Human plays White; NONO plays Black.")

    def log(self, message: str):
        self.events.append({"time": time.time(), "message": message})
        self.events = self.events[-60:]

    def require_idle(self):
        if self.status in ("planning", "moving", "capturing"):
            raise ValueError("Wait for the current operation or reset the simulation.")

    def state(self):
        state = self.game.state()
        pieces = []
        for square, piece in state.pop("pieces").items():
            pieces.append({**piece, "square": square,
                           "position": self.piece_overrides.get(square, piece["position_m"]),
                           "height_m": self.piece_heights.get(square, {}).get("height_m")})
        captures = [{**piece, "position": piece["destination"]["position_m"]}
                    for piece in state.get("captured_pieces", [])]
        calib = self.calibration.status()
        # A camera-plane fit alone never claims physical robot registration.
        calib.update({"status": "measured_scale" if self.measurement else "unmeasured",
                      "board_measured": bool(self.config["board"].get("measured")),
                      "measurement": self.measurement, "robot_registration": self.robot_registration,
                      "hardware_ready": False})
        return {**state, "mode": "simulation", "status": self.status,
                "pieces": pieces, "captures": captures, "last_move": self.last_move,
                "events": self.events, "config": self.config, "calibration": calib,
                "simulation": self.simulation.snapshot(), "plan": self.plan,
                "observation": self.last_observation,
                "camera": {"status": "snapshot" if self.latest_frame else "not_opened",
                           "frame_id": self.latest_frame.get("frame_id") if self.latest_frame else None,
                           "timestamp": self.latest_frame.get("timestamp") if self.latest_frame else None},
                "limitations": ["Kinematic MuJoCo preview; grasps are animated attachments, not validated contact dynamics.",
                                "Physical motion is not implemented. Camera, board and servo calibration remain separate."]}

    def apply_human(self, uci: str):
        self.require_idle()
        if self.game.board.turn != chess.WHITE:
            raise ValueError("It is NONO’s turn (Black).")
        result = self.game.apply_move(uci)
        self.update_heights(result["plan"])
        self.last_move, self.plan = uci, None
        self.log(f"Human played {uci}.")

    def update_heights(self, plan: dict):
        heights = deepcopy(self.piece_heights)
        self.piece_heights = {}
        for square in self.game.pieces():
            if square in heights:
                self.piece_heights[square] = heights[square]
        for transfer in plan["transfers"]:
            source = transfer["source"]["square"]
            self.piece_heights.pop(source, None)
            destination = transfer["destination"].get("square")
            if destination:
                self.piece_heights.pop(destination, None)
                if source in heights:
                    self.piece_heights[destination] = heights[source]
        if plan.get("promotion"):
            self.piece_heights.pop(plan["promotion"]["square"], None)

    def build_plan(self, uci: str):
        transfer_plan = self.game.plan_move(uci)
        qpos = [joint["position"] for joint in self.simulation.snapshot()["joints"]]
        initial_qpos = qpos.copy()
        waypoints, warnings = [], []
        for transfer_index, transfer in enumerate(transfer_plan["transfers"]):
            source, destination = (np.array(transfer[key]["position_m"], dtype=float) for key in ("source", "destination"))
            measured_height = self.piece_heights.get(transfer["source"]["square"], {}).get("height_m")
            grasp_height = measured_height * 0.45 if measured_height else self.config["motion"]["grasp_height_m"]
            clearance = max(self.config["motion"]["lift_m"],
                            max((h.get("height_m", 0) or 0 for h in self.piece_heights.values()), default=0) + .025)
            above_source, above_destination = source + [0, 0, clearance], destination + [0, 0, clearance]
            pickup, drop = source + [0, 0, grasp_height], destination + [0, 0, grasp_height]
            for phase, target, jaw in (("approach", above_source, 1), ("descend", pickup, 1),
                                       ("grasp", pickup, 0), ("lift", above_source, 0),
                                       ("transfer", above_destination, 0), ("place", drop, 0),
                                       ("release", drop, 1), ("retreat", above_destination, 1)):
                solution = self.simulation.solve_ik(target.tolist(), seed=qpos, downward=True)
                qpos = list(solution["qpos"])
                jaw_joint = self.simulation.snapshot()["joints"][-1]
                qpos[-1] = jaw_joint["max"] if jaw else jaw_joint["min"]
                solution.update(self.simulation.evaluate_qpos(qpos))
                waypoints.append({**solution, "qpos": qpos, "phase": phase, "target": target.tolist(),
                                  "transfer_index": transfer_index, "grasp_height_m": grasp_height})
                if not solution["reachable"]:
                    warnings.append(f"{transfer['role']} {phase}: target outside grasp tolerance ({solution['error_m'] * 1000:.1f} mm).")
                if not solution["collision_free"]:
                    warnings.append(f"{transfer['role']} {phase}: contact detected in the robot/board model.")
        samples = [initial_qpos]
        for waypoint in waypoints:
            samples.extend(self.simulation.interpolate_qpos(waypoint["qpos"], steps=12, start=samples[-1]))
        path_check = self.simulation.check_path(samples)
        if not path_check["collision_free"]:
            warnings.append("Contact detected along the sampled robot/board path.")
        if transfer_plan["promotion"]:
            warnings.append("Promotion needs a manual piece swap; this simulation updates the chess symbol only.")
        blocked = any(not w["reachable"] or not w["collision_free"] for w in waypoints) or not path_check["collision_free"]
        return {**transfer_plan, "status": "blocked" if blocked else "ready",
                "waypoints": waypoints, "warnings": warnings,
                "model_path_check": path_check,
                "collision_checked": False, "grasp_dynamics_verified": False, "hardware_executable": False}

    async def plan_robot(self, uci: str | None, execute: bool):
        self.require_idle()
        if self.game.board.turn != chess.BLACK:
            raise ValueError("The human plays White first.")
        if self.game.board.is_game_over(claim_draw=True):
            raise ValueError("The game has ended.")
        self.status = "planning"
        generation = self.generation
        try:
            chosen = uci or await asyncio.to_thread(self.game.choose_robot_move)
            plan = await asyncio.to_thread(self.build_plan, chosen)
            if generation != self.generation:
                return
            self.plan = plan
            if plan["status"] == "blocked":
                self.status = "blocked"
                self.log(f"{chosen} cannot be reached in this layout. Review the motion plan.")
            elif execute:
                self.status = "moving"
                self.task = asyncio.create_task(self.animate(plan, generation))
            else:
                self.status = "ready"
        except Exception:
            if generation == self.generation:
                self.status = "ready"
            raise

    async def animate(self, plan: dict, generation: int):
        attached = None
        try:
            for waypoint in plan["waypoints"]:
                if generation != self.generation:
                    return
                start = np.array([joint["position"] for joint in self.simulation.snapshot()["joints"]])
                goal = np.array(waypoint["qpos"])
                transfer = plan["transfers"][waypoint["transfer_index"]]
                plan["active_phase"] = waypoint["phase"]
                for i in range(1, 13):
                    if generation != self.generation:
                        return
                    t = i / 12
                    self.simulation.set_qpos((start + (goal - start) * (3 * t * t - 2 * t * t * t)).tolist())
                    if attached:
                        tcp = np.array(self.simulation.snapshot()["tcp"])
                        self.piece_overrides[attached] = (tcp - [0, 0, waypoint["grasp_height_m"]]).tolist()
                    await asyncio.sleep(self.config["motion"]["waypoint_seconds"] / 12)
                if waypoint["phase"] == "grasp":
                    attached = transfer["source"]["square"]
                if waypoint["phase"] == "release":
                    self.piece_overrides[transfer["source"]["square"]] = transfer["destination"]["position_m"]
                    attached = None
            self.game.apply_move(plan["uci"])
            self.update_heights(plan)
            self.last_move = plan["uci"]
            self.piece_overrides.clear()
            plan["status"] = "completed"
            self.status = "ready"
            self.log(f"NONO simulated {plan['san']} ({plan['uci']}).")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- report worker failure instead of leaving the cell moving
            self.status = "blocked"
            self.log(f"Simulation stopped: {exc}")

    async def reset(self, keep_camera: bool = False):
        self.generation += 1
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.game = ChessGame(self.config)
        self.simulation = Simulation(self.config)
        self.status, self.last_move, self.plan = "ready", None, None
        self.piece_overrides.clear()
        self.last_observation = None
        if keep_camera and self.latest_frame:
            self.latest_frame.update({"frame_id": str(uuid4()), "base_fen": self.game.board.fen()})
        else:
            self.latest_frame = None
            self.piece_heights.clear()
        self.log("Game reset.")

    def save_calibration(self):
        target = ROOT / "artifacts" / "calibration"
        target.mkdir(parents=True, exist_ok=True)
        (target / "latest.json").write_text(json.dumps({"timestamp": time.time(), "config": self.config,
                    "calibration": self.calibration.status(), "measurement": self.measurement}, indent=2))


def create_app(config: dict | None = None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.cell = Cell(config)
        yield
        if app.state.cell.task:
            app.state.cell.task.cancel()

    app = FastAPI(title="NONO Chess Cell", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.exception_handler(ValueError)
    async def value_error(_, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def cell() -> Cell:
        return app.state.cell

    @app.get("/api/health")
    def health():
        return {"ok": True, "mode": "simulation", "robot_id": "nono", "hardware_execution_enabled": False}

    @app.get("/api/state")
    async def state():
        return cell().state()

    @app.get("/api/hardware")
    def hardware():
        return discover(cell().config)

    @app.post("/api/move")
    async def move(request: MoveRequest):
        cell().apply_human(request.uci)
        return cell().state()

    @app.post("/api/robot")
    async def robot(request: RobotRequest):
        await cell().plan_robot(request.uci, request.execute)
        return cell().state()

    @app.post("/api/plan")
    async def plan(request: MoveRequest):
        await cell().plan_robot(request.uci, False)
        return cell().state()

    @app.post("/api/ik")
    async def ik(request: IKRequest):
        cell().require_idle()
        return cell().simulation.solve_ik(request.target, downward=request.downward)

    @app.post("/api/reset")
    async def reset():
        if cell().status in ("planning", "capturing"):
            raise ValueError("Wait for planning or camera capture to finish before resetting.")
        await cell().reset()
        return cell().state()

    @app.post("/api/config/board")
    async def board(request: BoardRequest):
        cell().require_idle()
        new = {**cell().config["board"], **request.model_dump(), "measured": False}
        validate_board(new)
        cell().config["board"] = new
        cell().calibration = BoardCalibration(cell().config)
        cell().measurement = None
        cell().robot_registration = None
        cell().piece_heights = {}
        await cell().reset()
        return cell().state()

    @app.post("/api/calibration/camera")
    async def camera_calibration(request: CornersRequest):
        cell().require_idle()
        cell().calibration.fit_camera(request.corners_px)
        cell().save_calibration()
        return cell().state()

    @app.post("/api/calibration/measure")
    async def measure(request: CornersRequest):
        from .calibration import measure_board_rgbd, piece_heights_rgbd
        cell().require_idle()
        frame = cell().latest_frame
        if not frame:
            raise ValueError("Capture an aligned Orbbec RGB-D snapshot first.")
        measurement = measure_board_rgbd(request.corners_px, frame["depth_m"], frame["intrinsics"])
        measurement["capture_id"] = frame.get("capture_id", frame["frame_id"])
        board = {**cell().config["board"], "square_size_m": measurement["square_size_m"], "measured": True}
        validate_board(board)
        candidate_config = {**cell().config, "board": board}
        calibration = BoardCalibration(candidate_config)
        calibration.fit_camera(request.corners_px)
        heights = piece_heights_rgbd(frame["depth_m"], frame["intrinsics"], measurement)
        cell().piece_heights, cell().measurement = heights, measurement
        cell().robot_registration = None
        cell().config, cell().calibration = candidate_config, calibration
        await cell().reset(keep_camera=True)
        cell().log("Board scale measured from aligned depth. Robot-base registration remains required.")
        cell().save_calibration()
        return cell().state()

    @app.post("/api/calibration/robot")
    async def robot_calibration(request: AnchorsRequest):
        cell().require_idle()
        result = cell().calibration.fit_robot(request.anchors)
        cell().save_calibration()
        return {"registration": result, "state": cell().state()}

    @app.post("/api/calibration/robot-rgbd")
    async def robot_rgbd(request: LandmarksRequest):
        from .calibration import register_robot_rgbd
        cell().require_idle()
        frame, measurement = cell().latest_frame, cell().measurement
        if not frame or not measurement:
            raise ValueError("Measure the board from the current RGB-D frame first.")
        if measurement.get("capture_id") != frame.get("capture_id", frame["frame_id"]):
            raise ValueError("Robot landmarks and board measurement must come from the same RGB-D capture.")
        registration = register_robot_rgbd(request.landmarks, frame["depth_m"], frame["intrinsics"])
        transform = np.asarray(registration["camera_to_robot"]) @ np.asarray(measurement["board_to_camera"])
        if transform[2, 2] < np.cos(np.deg2rad(5)):
            raise ValueError("The measured board is tilted or its corner axes are inverted relative to robot +Z. "
                             "This scene currently supports a horizontal board; verify the landmark and corner labels.")
        cfg = deepcopy(cell().config)
        cfg["board"].update({"origin_m": transform[:3, 3].tolist(),
                             "yaw_rad": float(np.arctan2(transform[1, 0], transform[0, 0]))})
        cfg["robot"].update({"base_position_m": [0, 0, 0], "base_yaw_rad": 0,
                             "sample_riser_height_m": 0, "pose_measured": True})
        validate_board(cfg["board"])
        calibration = BoardCalibration(cfg)
        calibration.fit_camera(measurement["corners_px"])
        width = measurement["board_width_m"]
        local = np.array([[0, 0, 0], [width, 0, 0], [width, width, 0], [0, width, 0]])
        world = local @ transform[:3, :3].T + transform[:3, 3]
        calibration.fit_robot([{"board_m": a.tolist(), "robot_m": b.tolist()} for a, b in zip(local, world)])
        # Validate the candidate scene before replacing the current one.
        Simulation(cfg)
        cell().config, cell().calibration = cfg, calibration
        cell().robot_registration = {**registration, "board_to_robot": transform.tolist()}
        await cell().reset(keep_camera=True)
        cell().log("Robot base registered from RGB-D landmarks. Scene now uses the measured board/base transform.")
        cell().save_calibration()
        return cell().state()

    @app.post("/api/camera/capture")
    async def camera_capture(request: CameraRequest):
        cell().require_idle()
        cell().status = "capturing"
        try:
            if request.camera == "top":
                frame = await asyncio.to_thread(capture_top, cell().config)
                frame.update({"frame_id": str(uuid4()), "capture_id": str(uuid4()), "base_fen": cell().game.board.fen()})
                cell().latest_frame = frame
                result = {key: val for key, val in frame.items() if key not in ("rgb", "depth_m")}
            else:
                result = await asyncio.to_thread(capture_wrist, cell().config)
            return {**result, "image_url": f"/api/camera/{request.camera}.jpg"}
        except ImportError as exc:
            raise ValueError("Camera drivers are optional. Install with uv sync --extra camera.") from exc
        finally:
            cell().status = "ready"

    @app.get("/api/camera/{camera}.jpg")
    def image(camera: Literal["top", "wrist"]):
        path = ROOT / "artifacts" / "camera" / f"{camera}.jpg"
        if not path.exists():
            raise HTTPException(404, "No snapshot captured.")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/api/observe")
    async def observe(request: ObservationRequest):
        cell().require_idle()
        if cell().game.board.turn != chess.WHITE:
            raise ValueError("Human observations are accepted only on White’s turn.")
        frame = cell().latest_frame
        if not frame or frame["frame_id"] != request.frame_id:
            raise ValueError("Observation must reference the current captured RGB-D frame.")
        if request.base_fen != cell().game.board.fen() or frame["base_fen"] != request.base_fen:
            raise ValueError("Stale observation: the chess position has changed.")
        if not request.hand_clear:
            raise ValueError("Wait for the human hand and robot to clear the board.")
        result = cell().game.infer_move(request.occupancy, confidence=request.confidence)
        result.update({"frame_id": request.frame_id, "committed": False})
        if request.commit:
            if time.time() - frame["timestamp"] > 120:
                raise ValueError("Snapshot is over two minutes old; capture again before committing.")
            if result["status"] != "accepted":
                raise ValueError(f"Observation is {result['status']}; no move committed.")
            cell().apply_human(result["uci"])
            result["committed"] = True
        cell().last_observation = result
        return result

    app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")
    return app


app = create_app()


def main():
    import uvicorn
    uvicorn.run("chessbot.api:app", host="127.0.0.1", port=int(os.environ.get("NONO_PORT", "8000")))
