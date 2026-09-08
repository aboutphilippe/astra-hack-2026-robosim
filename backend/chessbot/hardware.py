"""Read-only device discovery and explicitly requested RGB-D snapshots.

No motor writes or firmware updates live in this module. Gemini is SDK-only.
AVFoundation UIDs are not SDK serial numbers; enroll the latter explicitly.
"""
import argparse
import importlib.util
import io
import json
import math
import os
import re
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from .config import ROOT, load_config


def avfoundation_devices() -> list[dict]:
    if sys.platform != "darwin":
        return []
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeVideo
    except ImportError:
        return []
    return [{"index": i, "name": str(d.localizedName()), "unique_id": str(d.uniqueID())}
            for i, d in enumerate(AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo) or [])]


def resolve_wrist(devices: list[dict], config: dict) -> dict:
    denied = ("orbbec", "gemini", "obs", "facetime", "continuity", "iphone", "ipad")
    safe = [d for d in devices if not any(s in d["name"].lower() for s in denied)]
    exact = [d for d in safe if d["unique_id"] == config["unique_id"]]
    matched = exact or [d for d in safe if config["match"].lower() in d["name"].lower()]
    if len(matched) != 1:
        raise ValueError("Expected exactly one registered icspring wrist camera; no index fallback is allowed.")
    return matched[0]


def sdk_devices() -> list[dict]:
    from pyorbbecsdk import Context, OBError
    context = Context()  # Keep the device manager alive while device handles are in use.
    devices = context.query_devices()
    result = []
    for i in range(devices.get_count()):
        record = {"name": devices.get_device_name_by_index(i),
                  "serial": devices.get_device_serial_number_by_index(i),
                  "uid": devices.get_device_uid_by_index(i), "firmware": None}
        try:
            device = devices.get_device_by_index(i)
            record["firmware"] = device.get_device_info().get_firmware_version()
            record["accessible"] = True
        except OBError as exc:
            record.update({"accessible": False, "error": str(exc)})
        result.append(record)
    return result


def discover(config: dict, enumerate_sdk: bool = False) -> dict:
    result = {"robot": {"id": config["robot"]["id"], "connected": False,
              "serial_port_present": Path(config["robot"]["follower_port"]).exists(),
              "calibration_file_present": Path(config["robot"]["calibration_path"]).expanduser().exists(),
              "motor_bus_opened": False, "hardware_execution_enabled": False},
              "sdk_installed": importlib.util.find_spec("pyorbbecsdk") is not None,
              "camera_status": "not_opened", "configured_cameras": config["cameras"]}
    if enumerate_sdk:
        result["avfoundation"] = avfoundation_devices()
        result["sdk_devices"] = sdk_devices()
    return result


RGBD_FRAME_KEYS = frozenset({"rgb", "depth_m", "intrinsics", "timestamp", "serial", "firmware",
                             "depth_units", "depth_aligned"})
RGBD_MAX_PIXELS = 4096 * 3072
RGBD_MAX_BYTES = RGBD_MAX_PIXELS * 12 + 65536


def _validate_rgbd_frame(frame: dict, config: dict | None = None) -> dict:
    """Validate metric, aligned camera data without guessing units or identities."""
    rgb, depth = frame["rgb"], frame["depth_m"]
    if not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("RGB-D rgb must be a uint8 H×W×3 array.")
    h, w = rgb.shape[:2]
    if h < 1 or w < 1 or h * w > RGBD_MAX_PIXELS:
        raise ValueError("RGB-D frame dimensions are invalid or too large.")
    if (not isinstance(depth, np.ndarray) or depth.dtype not in (np.dtype("float32"), np.dtype("float64"))
            or depth.shape != (h, w) or not np.isfinite(depth).all() or np.any(depth < 0)):
        raise ValueError("RGB-D depth_m must be finite, nonnegative float32/float64 depth matching RGB shape, in metres.")
    if frame.get("depth_aligned") is not True:
        raise ValueError("RGB-D depth must be aligned to RGB.")
    if frame.get("depth_units", "metres") != "metres":
        raise ValueError("RGB-D depth units must be explicit metres.")
    intrinsics = frame["intrinsics"]
    if not isinstance(intrinsics, dict) or set(intrinsics) != {"fx", "fy", "cx", "cy"}:
        raise ValueError("RGB-D intrinsics must contain fx, fy, cx, cy.")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in intrinsics.values()):
        raise ValueError("RGB-D intrinsics must contain finite numeric values.")
    if intrinsics["fx"] <= 0 or intrinsics["fy"] <= 0 or not 0 <= intrinsics["cx"] < w or not 0 <= intrinsics["cy"] < h:
        raise ValueError("RGB-D intrinsics require positive focal lengths and an in-image principal point.")
    stamp = frame["timestamp"]
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or stamp <= 0:
        raise ValueError("RGB-D timestamp must be a finite positive Unix timestamp.")
    for key in ("serial", "firmware"):
        if not isinstance(frame[key], str) or not frame[key] or len(frame[key]) > 128:
            raise ValueError(f"RGB-D {key} must be a nonempty string.")
    if config is not None:
        cfg = config["cameras"]["top"]
        if not cfg.get("sdk_serial") or frame["serial"] != cfg["sdk_serial"]:
            raise ValueError("RGB-D serial does not match the enrolled Gemini SDK serial.")
        if frame["firmware"] != cfg["firmware_required"]:
            raise ValueError("RGB-D firmware does not match the required enrolled firmware.")
    return {**frame, "width": w, "height": h}


def read_rgbd_frame_file(path: str | Path, config: dict, *, now: float | None = None,
                         max_age_s: float = 3.0) -> dict:
    """Read one complete worker snapshot. Malformed/stale data never opens the SDK."""
    now = time.time() if now is None else now
    if not math.isfinite(now) or not math.isfinite(max_age_s) or not 0 < max_age_s <= 3:
        raise ValueError("RGB-D freshness window must be finite and at most three seconds.")
    try:
        # One open handle keeps the same atomic generation throughout validation.
        with Path(path).open("rb") as source:
            if os.fstat(source.fileno()).st_size > RGBD_MAX_BYTES:
                raise ValueError("RGB-D snapshot file is too large.")
            with zipfile.ZipFile(source) as archive:
                records = archive.infolist()
                if (len(records) != len(RGBD_FRAME_KEYS)
                        or {entry.filename for entry in records} != {key + ".npy" for key in RGBD_FRAME_KEYS}
                        or sum(entry.file_size for entry in records) > RGBD_MAX_BYTES):
                    raise ValueError("RGB-D snapshot archive has an invalid schema or exceeds the size limit.")
            source.seek(0)
            with np.load(source, allow_pickle=False) as arrays:
                frame = {"rgb": arrays["rgb"].copy(), "depth_m": arrays["depth_m"].copy()}
                for key in ("intrinsics", "serial", "firmware", "depth_units"):
                    value = arrays[key]
                    if value.shape != () or value.dtype.kind != "U":
                        raise ValueError(f"RGB-D {key} must be a scalar Unicode string.")
                    frame[key] = value.item()
                timestamp, aligned = arrays["timestamp"], arrays["depth_aligned"]
                if timestamp.shape != () or timestamp.dtype.kind != "f":
                    raise ValueError("RGB-D timestamp must be a scalar float.")
                if aligned.shape != () or aligned.dtype.kind != "b":
                    raise ValueError("RGB-D depth_aligned must be a scalar boolean.")
                frame["timestamp"], frame["depth_aligned"] = timestamp.item(), aligned.item()
        frame["intrinsics"] = json.loads(frame["intrinsics"])
        frame = _validate_rgbd_frame(frame, config)
        age = now - frame["timestamp"]
        if age > max_age_s:
            raise ValueError(f"RGB-D snapshot is stale ({age:.2f}s); camera worker must be running.")
        if age < -0.5:
            raise ValueError("RGB-D snapshot timestamp is in the future.")
        return frame
    except (OSError, ValueError, TypeError, KeyError, EOFError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Invalid RGB-D frame file: {exc}") from exc


def write_rgbd_frame_file(frame: dict, path: str | Path) -> None:
    """Publish a complete private snapshot atomically, only after dropping root."""
    if os.geteuid() == 0:
        raise PermissionError("Refusing to create RGB-D output while running as root.")
    frame = _validate_rgbd_frame(frame)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as target:
            np.savez_compressed(target, rgb=frame["rgb"], depth_m=frame["depth_m"],
                                intrinsics=json.dumps(frame["intrinsics"], allow_nan=False),
                                timestamp=float(frame["timestamp"]), serial=frame["serial"],
                                firmware=frame["firmware"], depth_units="metres", depth_aligned=True)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sdk_capture_error(exc: Exception) -> ValueError:
    message = str(exc)
    if sys.platform == "darwin" and ("UVC_ERROR_ACCESS" in message or re.search(r"(?:uvc_open|ret|error).*?-3\b", message)):
        return ValueError("Orbbec USB driver access denied (uvc_open -3). macOS may require root to detach "
                          "the camera's USB driver even after Camera permission is granted. Run the camera-only "
                          "nono-camera-worker helper manually with sudo; it drops privileges before writing frames. "
                          "Set NONO_RGBD_FRAME_FILE on the server to its output. The API never runs sudo. "
                          f"SDK detail: {message}")
    return ValueError(f"Orbbec SDK capture failed: {message}. Check device access, camera permission, and other camera processes.")


class AlignedRGBDSession:
    """Keep Context, device, pipeline and alignment alive for a persistent SDK stream.

    start() returns the first valid synchronized frame. A camera-only helper can
    then discard elevated privileges while continuing to use these open handles.
    This class never writes files and never uses OpenCV or a network camera.
    """

    def __init__(self, config: dict):
        self.config = config
        self.context = self.devices = self.device = self.pipeline = self.align = None
        self.color_profile = self.info = None
        self.firmware = None
        self.started = False
        self._start_attempted = False

    def start(self) -> dict:
        if self.pipeline is not None:
            raise ValueError("RGB-D session has already been started.")
        from pyorbbecsdk import (
            AlignFilter,
            Config,
            Context,
            OBError,
            OBFormat,
            OBLogLevel,
            OBSensorType,
            OBStreamType,
            Pipeline,
        )
        cfg = self.config["cameras"]["top"]
        if not cfg.get("sdk_serial"):
            raise ValueError("Enroll cameras.top.sdk_serial first; an AVFoundation UID is not an Orbbec SDK serial.")
        # Configure logging before Context initializes SDK/device services. NONE
        # disables disk logging, including in the helper's short privileged phase.
        Context.set_logger_to_file(OBLogLevel.NONE, "")
        Context.set_logger_to_console(OBLogLevel.WARNING)
        try:
            # Read-only packaged config prevents default network enumeration
            # and file logging from starting inside the Context constructor.
            sdk_config = Path(__file__).with_name("camera_sdk.xml")
            if not sdk_config.is_file():
                raise ValueError("Packaged camera_sdk.xml is missing; refusing SDK defaults with network/file logging.")
            self.context = Context(str(sdk_config))
            self.context.enable_net_device_enumeration(False)
            self.devices = self.context.query_devices()
            self.device = self.devices.get_device_by_serial_number(cfg["sdk_serial"])
            self.info = self.device.get_device_info()
            if "336" not in self.info.get_name() or self.info.get_serial_number() != cfg["sdk_serial"]:
                raise ValueError("Registered device is not the enrolled Gemini 336.")
            self.firmware = self.info.get_firmware_version().lstrip("v")
            if self.firmware != cfg["firmware_required"]:
                raise ValueError(f"Desk fixture requires firmware {cfg['firmware_required']}; found {self.firmware}.")
            self.pipeline, stream = Pipeline(self.device), Config()
            color_profiles = self.pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
            depth_profiles = self.pipeline.get_stream_profile_list(OBSensorType.DEPTH_SENSOR)
            try:
                self.color_profile = color_profiles.get_video_stream_profile(
                    cfg["width"], cfg["height"], OBFormat.RGB, cfg.get("fps", 30))
            except (RuntimeError, OBError):
                self.color_profile = color_profiles.get_default_video_stream_profile()
            stream.enable_stream(self.color_profile)
            stream.enable_stream(depth_profiles.get_default_video_stream_profile())
            self.align = AlignFilter(align_to_stream=OBStreamType.COLOR_STREAM)
            self.pipeline.enable_frame_sync()
            self._start_attempted = True
            self.pipeline.start(stream)
            self.started = True
            return self.read_frame()
        except OBError as exc:
            try:
                self.close()
            except (RuntimeError, OBError) as stop_exc:
                exc.add_note(f"Stopping the partially opened stream also failed: {stop_exc}")
            raise sdk_capture_error(exc) from exc
        except BaseException as exc:
            try:
                self.close()
            except (RuntimeError, OBError) as stop_exc:
                exc.add_note(f"Stopping the partially opened stream also failed: {stop_exc}")
            raise

    def read_frame(self) -> dict:
        from pyorbbecsdk import OBError, OBFormat
        if not self.started:
            raise ValueError("RGB-D session has not started.")
        try:
            for _ in range(15):
                frames = self.pipeline.wait_for_frames(1000)
                if frames is None:
                    continue
                aligned = self.align.process(frames)
                frames = aligned.as_frame_set() if aligned is not None else None
                if frames is None:
                    continue
                color, depth = frames.get_color_frame(), frames.get_depth_frame()
                if color is None or depth is None:
                    continue
                w, h = color.get_width(), color.get_height()
                if (depth.get_width(), depth.get_height()) != (w, h):
                    raise ValueError("SDK depth alignment failed: refusing resized depth for metric calibration.")
                buf = np.frombuffer(color.get_data(), dtype=np.uint8)
                fmt = color.get_format()
                if fmt == OBFormat.RGB:
                    rgb = buf.reshape(h, w, 3).copy()
                elif fmt == OBFormat.MJPG:
                    rgb = np.asarray(Image.open(io.BytesIO(buf.tobytes())).convert("RGB")).copy()
                else:
                    raise ValueError(f"Unsupported RGB format {fmt}; select RGB or MJPG.")
                depth_m = np.frombuffer(depth.get_data(), dtype=np.uint16).reshape(h, w).astype(np.float32)
                scale = float(depth.get_depth_scale())
                if not math.isfinite(scale) or scale <= 0:
                    raise ValueError("SDK depth scale must be finite and positive.")
                depth_m *= scale / 1000.0
                intrinsic = self.color_profile.as_video_stream_profile().get_intrinsic()
                frame = {"rgb": rgb, "depth_m": depth_m,
                         "intrinsics": {key: float(getattr(intrinsic, key)) for key in ("fx", "fy", "cx", "cy")},
                         "timestamp": time.time(), "serial": self.info.get_serial_number(), "firmware": self.firmware,
                         "width": w, "height": h, "depth_aligned": True, "depth_units": "metres"}
                return _validate_rgbd_frame(frame, self.config)
            raise ValueError("No synchronized RGB-D frame arrived from the Gemini.")
        except OBError as exc:
            raise sdk_capture_error(exc) from exc

    def close(self) -> None:
        try:
            if self.pipeline is not None and self._start_attempted:
                self.pipeline.stop()
        finally:
            self.started = False
            self._start_attempted = False
            self.align = self.pipeline = self.device = self.devices = self.context = None
            self.color_profile = self.info = None


def _capture_top(config: dict) -> dict:
    session = AlignedRGBDSession(config)
    try:
        return session.start()
    finally:
        session.close()


def capture_top(config: dict) -> dict:
    frame_file = os.environ.get("NONO_RGBD_FRAME_FILE")
    frame = read_rgbd_frame_file(frame_file, config) if frame_file is not None else _capture_top(config)
    target = ROOT / "artifacts" / "camera"
    write_rgbd_frame_file(frame, target / "top_rgbd.npz")
    # These artifacts are served only by the existing authenticated camera API.
    fd, temporary = tempfile.mkstemp(prefix=".top.", suffix=".jpg", dir=target)
    try:
        with os.fdopen(fd, "wb") as output:
            Image.fromarray(frame["rgb"]).save(output, format="JPEG", quality=95)
        os.replace(temporary, target / "top.jpg")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return frame


def capture_wrist(config: dict) -> dict:
    import cv2
    cfg = config["cameras"]["wrist"]
    device = resolve_wrist(avfoundation_devices(), cfg)
    camera = cv2.VideoCapture(device["index"], cv2.CAP_AVFOUNDATION)
    try:
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, cfg["width"])
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg["height"])
        frame = None
        for _ in range(8):
            ok, data = camera.read()
            if ok:
                frame = data
        if frame is None:
            raise ValueError("Wrist camera returned no frame.")
        target = ROOT / "artifacts" / "camera"
        target.mkdir(parents=True, exist_ok=True)
        Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).save(target / "wrist.jpg")
        return {"device": device, "width": frame.shape[1], "height": frame.shape[0], "timestamp": time.time()}
    finally:
        camera.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", action="store_true", help="Enumerate cameras through SDK; never move motors")
    args = parser.parse_args()
    print(json.dumps(discover(load_config(), args.sdk), indent=2))
