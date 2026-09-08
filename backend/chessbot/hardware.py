"""Read-only device discovery and explicitly requested RGB-D snapshots.

No motor writes or firmware updates live in this module. Gemini is SDK-only.
AVFoundation UIDs are not SDK serial numbers; enroll the latter explicitly.
"""
import argparse
import importlib.util
import io
import json
import sys
import time
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


def capture_top(config: dict) -> dict:
    from pyorbbecsdk import OBError
    try:
        return _capture_top(config)
    except OBError as exc:
        raise ValueError(f"Orbbec SDK capture failed: {exc}. Check camera permission and other camera processes.") from exc


def _capture_top(config: dict) -> dict:
    """Aligned depth in metres and matching native RGB intrinsics; no image resizing."""
    from pyorbbecsdk import AlignFilter, Config, Context, OBFormat, OBSensorType, OBStreamType, Pipeline

    cfg = config["cameras"]["top"]
    if not cfg.get("sdk_serial"):
        raise ValueError("Run uv run nono-discover --sdk and set cameras.top.sdk_serial in config/local.json. "
                         "The frozen AVFoundation UID is not an Orbbec SDK serial number.")
    context = Context()
    devices = context.query_devices()
    device = devices.get_device_by_serial_number(cfg["sdk_serial"])
    info = device.get_device_info()
    if "336" not in info.get_name():
        raise ValueError("Registered device is not a Gemini 336.")
    firmware = info.get_firmware_version().lstrip("v")
    if firmware != cfg["firmware_required"]:
        raise ValueError(f"Desk fixture requires firmware {cfg['firmware_required']}; found {firmware}.")
    pipeline, stream = Pipeline(device), Config()
    color_profiles = pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
    depth_profiles = pipeline.get_stream_profile_list(OBSensorType.DEPTH_SENSOR)
    try:
        color_profile = color_profiles.get_video_stream_profile(cfg["width"], cfg["height"], OBFormat.RGB, 30)
    except RuntimeError:
        color_profile = color_profiles.get_default_video_stream_profile()
    depth_profile = depth_profiles.get_default_video_stream_profile()
    stream.enable_stream(color_profile)
    stream.enable_stream(depth_profile)
    align = AlignFilter(align_to_stream=OBStreamType.COLOR_STREAM)
    pipeline.enable_frame_sync()
    pipeline.start(stream)
    try:
        for _ in range(15):
            frames = pipeline.wait_for_frames(1000)
            if frames is None:
                continue
            aligned = align.process(frames)
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
                rgb = np.asarray(Image.open(io.BytesIO(buf.tobytes())).convert("RGB"))
            else:
                raise ValueError(f"Unsupported RGB format {fmt}; select RGB or MJPG.")
            depth_m = np.frombuffer(depth.get_data(), dtype=np.uint16).reshape(h, w).astype(float)
            depth_m *= float(depth.get_depth_scale()) / 1000.0
            intrinsic = color_profile.as_video_stream_profile().get_intrinsic()
            frame = {"rgb": rgb, "depth_m": depth_m,
                     "intrinsics": {key: float(getattr(intrinsic, key)) for key in ("fx", "fy", "cx", "cy")},
                     "timestamp": time.time(), "serial": info.get_serial_number(), "firmware": firmware,
                     "width": w, "height": h, "depth_aligned": True}
            target = ROOT / "artifacts" / "camera"
            target.mkdir(parents=True, exist_ok=True)
            Image.fromarray(rgb).save(target / "top.jpg", quality=95)
            np.savez_compressed(target / "top_rgbd.npz", depth_m=depth_m, rgb=rgb,
                                intrinsics=json.dumps(frame["intrinsics"]))
            return frame
        raise ValueError("No synchronized RGB-D frame arrived from the Gemini.")
    finally:
        pipeline.stop()


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
