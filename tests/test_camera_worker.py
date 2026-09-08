"""Verify the camera worker's privilege boundary without opening any device."""

import os
import socket
import sys
from itertools import count
from types import SimpleNamespace

import numpy as np
import pytest
from chessbot import camera_worker, hardware


@pytest.fixture
def fake_process(monkeypatch, tmp_path):
    process = {"uid": 0, "gid": 0, "groups": [0, 20], "calls": []}
    monkeypatch.setattr(os, "getuid", lambda: process["uid"])
    monkeypatch.setattr(os, "geteuid", lambda: process["uid"])
    monkeypatch.setattr(os, "getgid", lambda: process["gid"])
    monkeypatch.setattr(os, "getegid", lambda: process["gid"])
    monkeypatch.setenv("SUDO_UID", "501")
    monkeypatch.setenv("SUDO_GID", "20")

    def setgroups(groups):
        process["calls"].append(("groups", list(groups)))
        process["groups"] = list(groups)

    def setgid(gid):
        process["calls"].append(("gid", gid))
        process["gid"] = gid

    def setuid(uid):
        process["calls"].append(("uid", uid))
        process["uid"] = uid

    monkeypatch.setattr(os, "setgroups", setgroups)
    monkeypatch.setattr(os, "setgid", setgid)
    monkeypatch.setattr(os, "setuid", setuid)
    return process


@pytest.fixture
def camera_config():
    return {"cameras": {"top": {"sdk_serial": "TEST-GEMINI-336", "firmware_required": "1.8.10",
                                "width": 4, "height": 3, "fps": 30}}}


def sample_frame(index=0):
    return {"rgb": np.full((3, 4, 3), index, dtype=np.uint8),
            "depth_m": np.full((3, 4), .6, dtype=np.float32),
            "intrinsics": {"fx": 4., "fy": 4., "cx": 1.5, "cy": 1.},
            "timestamp": 1_720_000_000.0 + index, "serial": "TEST-GEMINI-336",
            "firmware": "1.8.10", "width": 4, "height": 3, "depth_aligned": True}


@pytest.mark.parametrize("environ", [
    {}, {"SUDO_UID": "501"}, {"SUDO_GID": "20"},
    {"SUDO_UID": "0", "SUDO_GID": "20"},
    {"SUDO_UID": "501", "SUDO_GID": "0"},
    {"SUDO_UID": "-1", "SUDO_GID": "20"},
    {"SUDO_UID": "501", "SUDO_GID": "-20"},
    {"SUDO_UID": "root", "SUDO_GID": "20"},
    {"SUDO_UID": "501", "SUDO_GID": "staff"},
])
def test_root_requires_a_nonroot_sudo_identity(fake_process, environ):
    with pytest.raises((ValueError, RuntimeError, PermissionError), match="(?i)sudo|identity|uid|gid|root"):
        camera_worker.sudo_identity(environ)
    assert fake_process["calls"] == []


def test_root_identity_is_validated_before_constructing_or_opening_camera(fake_process, camera_config, monkeypatch, tmp_path):
    monkeypatch.delenv("SUDO_UID")
    monkeypatch.delenv("SUDO_GID")

    def forbidden_camera(config):
        pytest.fail("The root worker must reject missing sudo identity before constructing an SDK session")

    with pytest.raises((ValueError, RuntimeError, PermissionError)):
        camera_worker.run_worker(camera_config, tmp_path / "frame.npz", max_frames=1, session_factory=forbidden_camera)
    assert not (tmp_path / "frame.npz").exists()


def test_privilege_drop_removes_root_groups_then_gid_then_uid(fake_process):
    identity = camera_worker.sudo_identity({"SUDO_UID": "501", "SUDO_GID": "20"})
    assert identity == (501, 20)
    camera_worker.drop_privileges(identity)
    assert fake_process["calls"] == [("groups", []), ("gid", 20), ("uid", 501)]
    assert (fake_process["uid"], fake_process["gid"], fake_process["groups"]) == (501, 20, [])


def test_nonroot_worker_does_not_require_sudo_or_change_process_identity(fake_process):
    fake_process.update(uid=501, gid=20, groups=[20])
    assert camera_worker.sudo_identity({}) is None
    camera_worker.drop_privileges(None)
    assert fake_process["calls"] == []


def test_drop_failure_cannot_leave_a_worker_running_as_root(fake_process, monkeypatch):
    monkeypatch.setattr(os, "setuid", lambda uid: None)
    with pytest.raises((ValueError, RuntimeError, PermissionError), match="(?i)root|privilege|uid"):
        camera_worker.drop_privileges((501, 20))


def test_usb_open_precedes_drop_but_every_publication_and_read_follow_it(fake_process, camera_config, monkeypatch, tmp_path):
    events = []

    class Session:
        def __init__(self, config):
            assert config is camera_config
            self.index = 0
            events.append(("construct", os.geteuid()))

        def start(self):
            events.append(("open", os.geteuid()))
            return sample_frame()

        def read_frame(self):
            self.index += 1
            events.append(("read", os.geteuid()))
            assert os.geteuid() == 501
            return sample_frame(self.index)

        def close(self):
            events.append(("close", os.geteuid()))

    def publish(frame, output):
        assert os.geteuid() == 501 and os.getegid() == 20
        assert fake_process["groups"] == []
        assert output == tmp_path / "frame.npz"
        events.append(("publish", int(frame["rgb"][0, 0, 0])))

    def forbidden_socket(*args, **kwargs):
        pytest.fail("The frame-file worker must not open a network listener")

    monkeypatch.setattr(camera_worker, "write_rgbd_frame_file", publish)
    clock = count()
    monkeypatch.setattr(camera_worker.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(socket, "socket", forbidden_socket)
    camera_worker.run_worker(camera_config, tmp_path / "frame.npz", interval_seconds=.5,
                             max_frames=3, session_factory=Session)
    assert events == [("construct", 0), ("open", 0), ("publish", 0),
                      ("read", 501), ("publish", 1), ("read", 501), ("publish", 2), ("close", 501)]


@pytest.mark.parametrize("failure", ["start", "drop", "publish", "read"])
def test_camera_handle_is_closed_after_any_failure(fake_process, camera_config, monkeypatch, tmp_path, failure):
    closed = []
    published = []

    class Session:
        def __init__(self, config):
            pass

        def start(self):
            if failure == "start":
                raise RuntimeError("synthetic start failure")
            return sample_frame()

        def read_frame(self):
            if failure == "read":
                raise RuntimeError("synthetic read failure")
            return sample_frame(1)

        def close(self):
            closed.append(True)

    def drop(identity):
        if failure == "drop":
            raise PermissionError("synthetic drop failure")
        fake_process.update(uid=501, gid=20, groups=[])

    def publish(frame, output):
        assert os.geteuid() != 0
        if failure == "publish":
            raise OSError("synthetic publish failure")
        published.append(frame)

    monkeypatch.setattr(camera_worker, "drop_privileges", drop)
    monkeypatch.setattr(camera_worker, "write_rgbd_frame_file", publish)
    monkeypatch.setattr(camera_worker.time, "sleep", lambda duration: None)
    with pytest.raises((RuntimeError, PermissionError, OSError), match=f"synthetic {failure} failure"):
        camera_worker.run_worker(camera_config, tmp_path / "frame.npz", max_frames=2, session_factory=Session)
    assert closed == [True]
    if failure in ("start", "drop"):
        assert published == []


@pytest.fixture
def fake_sdk(monkeypatch):
    """A complete in-memory SDK boundary, without importing a native camera driver."""
    control = {"events": [], "fail_start": False, "bad_intrinsics": False,
               "serial": "TEST-GEMINI-336", "firmware": "1.8.10", "name": "Orbbec Gemini 336"}

    class Device:
        def get_device_info(self):
            return SimpleNamespace(get_name=lambda: control["name"],
                                   get_serial_number=lambda: control["serial"],
                                   get_firmware_version=lambda: control["firmware"])

    class Context:
        def __init__(self, config_path=None):
            control["events"].append("context")
            control["config_path"] = config_path

        @staticmethod
        def set_logger_to_file(level, path):
            control["events"].append("file_logging_disabled")
            assert level == "NONE"

        @staticmethod
        def set_logger_to_console(level):
            assert level == "WARNING"

        def enable_net_device_enumeration(self, enabled):
            control["events"].append("network_disabled")
            assert enabled is False

        def query_devices(self):
            return SimpleNamespace(get_device_by_serial_number=lambda serial: Device())

    class Profile:
        def as_video_stream_profile(self):
            return self

        def get_intrinsic(self):
            return SimpleNamespace(fx=float("nan") if control["bad_intrinsics"] else 4.,
                                   fy=4., cx=1.5, cy=1., width=4, height=3)

    class ColorFrame:
        def get_width(self):
            return 4

        def get_height(self):
            return 3

        def get_data(self):
            return np.arange(36, dtype=np.uint8).tobytes()

        def get_format(self):
            return "RGB"

    class DepthFrame(ColorFrame):
        def get_data(self):
            return np.full((3, 4), 600, dtype=np.uint16).tobytes()

        def get_depth_scale(self):
            return 1.

    class Frames:
        def as_frame_set(self):
            return self

        def get_color_frame(self):
            return ColorFrame()

        def get_depth_frame(self):
            return DepthFrame()

    class Pipeline:
        def __init__(self, device):
            control["events"].append("construct_pipeline")

        def get_stream_profile_list(self, sensor):
            return SimpleNamespace(get_video_stream_profile=lambda *args: Profile(),
                                   get_default_video_stream_profile=lambda: Profile())

        def enable_frame_sync(self):
            control["events"].append("frame_sync")

        def start(self, stream):
            control["events"].append("start")
            if control["fail_start"]:
                raise RuntimeError("synthetic partial pipeline start")

        def wait_for_frames(self, timeout):
            control["events"].append("read")
            return Frames()

        def stop(self):
            control["events"].append("stop")

    sdk = SimpleNamespace(
        Context=Context, Pipeline=Pipeline, OBError=RuntimeError,
        Config=lambda: SimpleNamespace(enable_stream=lambda profile: None),
        AlignFilter=lambda **kwargs: SimpleNamespace(process=lambda frames: frames),
        OBFormat=SimpleNamespace(RGB="RGB", MJPG="MJPG"),
        OBLogLevel=SimpleNamespace(NONE="NONE", WARNING="WARNING"),
        OBSensorType=SimpleNamespace(COLOR_SENSOR="color", DEPTH_SENSOR="depth"),
        OBStreamType=SimpleNamespace(COLOR_STREAM="color"),
    )
    monkeypatch.setitem(sys.modules, "pyorbbecsdk", sdk)
    return control


def test_failed_native_pipeline_start_closes_partial_session(camera_config, fake_sdk):
    fake_sdk["fail_start"] = True
    session = hardware.AlignedRGBDSession(camera_config)
    with pytest.raises((ValueError, RuntimeError), match="synthetic partial pipeline start"):
        session.start()
    assert fake_sdk["events"].count("start") == 1
    assert fake_sdk["events"].count("stop") == 1
    session.close()
    assert fake_sdk["events"].count("stop") == 1


def test_invalid_warm_frame_closes_native_session_before_returning(camera_config, fake_sdk):
    fake_sdk["bad_intrinsics"] = True
    session = hardware.AlignedRGBDSession(camera_config)
    with pytest.raises(ValueError, match="(?i)intrinsic|finite|focal"):
        session.start()
    assert fake_sdk["events"].count("start") == 1
    assert fake_sdk["events"].count("stop") == 1
    session.close()
    assert fake_sdk["events"].count("stop") == 1


def test_persistent_session_reuses_one_open_pipeline_for_multiple_snapshots(camera_config, fake_sdk):
    session = hardware.AlignedRGBDSession(camera_config)
    first = session.start()
    second = session.read_frame()
    session.close()
    assert fake_sdk["events"].count("construct_pipeline") == 1
    assert fake_sdk["events"].count("start") == 1
    assert fake_sdk["events"].count("stop") == 1
    assert fake_sdk["events"].count("read") >= 2
    np.testing.assert_array_equal(first["rgb"], second["rgb"])
    np.testing.assert_allclose(first["depth_m"], .6)
    assert first["serial"] == "TEST-GEMINI-336" and first["firmware"] == "1.8.10"


@pytest.mark.parametrize("field,value", [("serial", "UNREGISTERED"), ("firmware", "1.8.9"),
                                          ("name", "Other RGB-D Camera")])
def test_native_camera_identity_rejected_before_start(camera_config, fake_sdk, field, value):
    fake_sdk[field] = value
    session = hardware.AlignedRGBDSession(camera_config)
    with pytest.raises(ValueError, match="(?i)serial|firmware|336|registered|enroll"):
        session.start()
    assert "start" not in fake_sdk["events"]
