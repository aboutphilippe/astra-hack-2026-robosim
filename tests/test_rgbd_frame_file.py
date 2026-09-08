"""Exercise the camera bridge using small synthetic snapshots; never open USB."""

import builtins
import json
import os
import stat
from copy import deepcopy

import numpy as np
import pytest
from chessbot import hardware

NOW = 1_720_000_000.0
SERIAL = "TEST-GEMINI-336"
FIRMWARE = "1.8.10"


@pytest.fixture(autouse=True)
def forbid_native_sdk_imports(monkeypatch):
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("pyorbbecsdk"):
            pytest.fail("Frame-file tests must never import or open the native SDK")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


@pytest.fixture
def camera_config():
    return {"cameras": {"top": {"sdk_serial": SERIAL, "firmware_required": FIRMWARE,
                                "width": 4, "height": 3, "fps": 30}}}


@pytest.fixture
def snapshot():
    return {"rgb": np.arange(36, dtype=np.uint8).reshape(3, 4, 3),
            "depth_m": np.full((3, 4), 0.6, dtype=np.float32),
            "intrinsics": {"fx": 4.0, "fy": 4.1, "cx": 1.5, "cy": 1.0},
            "timestamp": NOW, "serial": SERIAL, "firmware": FIRMWARE,
            "width": 4, "height": 3, "depth_aligned": True}


def archive_fields(frame):
    return {"rgb": frame["rgb"], "depth_m": frame["depth_m"],
            "intrinsics": np.array(json.dumps(frame["intrinsics"])),
            "timestamp": np.array(frame["timestamp"]), "serial": np.array(frame["serial"]),
            "firmware": np.array(frame["firmware"]), "depth_units": np.array("metres"),
            "depth_aligned": np.array(frame["depth_aligned"])}


def save_archive(path, frame, **overrides):
    fields = archive_fields(frame)
    fields.update(overrides)
    np.savez_compressed(path, **fields)
    return path


def test_valid_aligned_snapshot_preserves_metric_arrays_and_identity(tmp_path, camera_config, snapshot):
    path = save_archive(tmp_path / "frame.npz", snapshot)
    result = hardware.read_rgbd_frame_file(path, camera_config, now=NOW)
    np.testing.assert_array_equal(result["rgb"], snapshot["rgb"])
    np.testing.assert_array_equal(result["depth_m"], snapshot["depth_m"])
    assert result["intrinsics"] == snapshot["intrinsics"]
    assert result["serial"] == SERIAL and result["firmware"] == FIRMWARE
    assert result["timestamp"] == NOW
    assert (result["width"], result["height"]) == (4, 3)
    assert result["depth_aligned"] is True


@pytest.mark.parametrize("age", [3.01, 30, -0.51, -30])
def test_stale_and_future_frames_are_rejected(tmp_path, camera_config, snapshot, age):
    path = save_archive(tmp_path / "frame.npz", snapshot, timestamp=np.array(NOW - age))
    with pytest.raises(ValueError, match="(?i)stale|old|future|timestamp|age"):
        hardware.read_rgbd_frame_file(path, camera_config, now=NOW, max_age_s=3)


@pytest.mark.parametrize("age", [3.0, 0, -0.5])
def test_documented_timestamp_boundaries_are_accepted(tmp_path, camera_config, snapshot, age):
    path = save_archive(tmp_path / "frame.npz", snapshot, timestamp=np.array(NOW - age))
    assert hardware.read_rgbd_frame_file(path, camera_config, now=NOW, max_age_s=3)["timestamp"] == NOW - age


@pytest.mark.parametrize("field,value", [("serial", "OTHER-CAMERA"), ("firmware", "1.8.9")])
def test_file_identity_must_match_enrolled_camera(tmp_path, camera_config, snapshot, field, value):
    path = save_archive(tmp_path / "frame.npz", snapshot, **{field: np.array(value)})
    with pytest.raises(ValueError, match="(?i)serial|firmware|registered|enroll"):
        hardware.read_rgbd_frame_file(path, camera_config, now=NOW)


def test_unenrolled_camera_cannot_accept_an_arbitrary_frame_file(tmp_path, camera_config, snapshot):
    camera_config["cameras"]["top"]["sdk_serial"] = None
    path = save_archive(tmp_path / "frame.npz", snapshot)
    with pytest.raises(ValueError, match="(?i)serial|registered|enroll"):
        hardware.read_rgbd_frame_file(path, camera_config, now=NOW)


@pytest.mark.parametrize("field", ["rgb", "depth_m", "intrinsics", "timestamp", "serial",
                                    "firmware", "depth_units", "depth_aligned"])
def test_incomplete_archives_fail_closed(tmp_path, camera_config, snapshot, field):
    fields = archive_fields(snapshot)
    del fields[field]
    path = tmp_path / "incomplete.npz"
    np.savez_compressed(path, **fields)
    with pytest.raises(ValueError):
        hardware.read_rgbd_frame_file(path, camera_config, now=NOW)


@pytest.mark.parametrize("overrides", [
    {"rgb": np.ones((3, 4, 3), dtype=np.float32)},
    {"rgb": np.ones((3, 4, 4), dtype=np.uint8)},
    {"rgb": np.ones((3, 4), dtype=np.uint8)},
    {"rgb": np.empty((0, 4, 3), dtype=np.uint8)},
    {"depth_m": np.ones((2, 4), dtype=np.float32)},
    {"depth_m": np.ones((3, 4, 1), dtype=np.float32)},
    {"depth_m": np.ones((3, 4), dtype=np.uint16)},
    {"depth_m": np.full((3, 4), -0.1, dtype=np.float32)},
    {"depth_m": np.full((3, 4), np.nan, dtype=np.float32)},
    {"depth_m": np.full((3, 4), np.inf, dtype=np.float64)},
    {"depth_units": np.array("millimetres")},
    {"depth_aligned": np.array(False)},
    {"depth_aligned": np.array("true")},
    {"timestamp": np.array(np.nan)},
    {"timestamp": np.array(np.inf)},
    {"timestamp": np.array([NOW])},
    {"serial": np.array([SERIAL])},
    {"firmware": np.array([FIRMWARE])},
    {"intrinsics": np.array([json.dumps({"fx": 4, "fy": 4, "cx": 1, "cy": 1})])},
    {"rgb": np.full((3, 4, 3), "unsafe object array", dtype=object)},
])
def test_malformed_array_shapes_types_and_metadata_are_rejected(tmp_path, camera_config, snapshot, overrides):
    path = save_archive(tmp_path / "bad.npz", snapshot, **overrides)
    with pytest.raises(ValueError):
        hardware.read_rgbd_frame_file(path, camera_config, now=NOW)


@pytest.mark.parametrize("intrinsics", [
    {"fx": 0, "fy": 4, "cx": 1.5, "cy": 1},
    {"fx": 4, "fy": -4, "cx": 1.5, "cy": 1},
    {"fx": np.nan, "fy": 4, "cx": 1.5, "cy": 1},
    {"fx": 4, "fy": np.inf, "cx": 1.5, "cy": 1},
    {"fx": 4, "fy": 4, "cx": -0.01, "cy": 1},
    {"fx": 4, "fy": 4, "cx": 4, "cy": 1},
    {"fx": 4, "fy": 4, "cx": 1.5, "cy": 3},
    {"fx": 4, "fy": 4, "cx": 1.5},
    [4, 4, 1.5, 1],
    None,
])
def test_invalid_intrinsics_cannot_establish_a_metric_camera(tmp_path, camera_config, snapshot, intrinsics):
    path = save_archive(tmp_path / "bad.npz", snapshot, intrinsics=np.array(json.dumps(intrinsics)))
    with pytest.raises(ValueError):
        hardware.read_rgbd_frame_file(path, camera_config, now=NOW)


def test_zero_depth_is_retained_as_missing_measurement_not_filled(tmp_path, camera_config, snapshot):
    snapshot["depth_m"][1, 2] = 0
    path = save_archive(tmp_path / "frame.npz", snapshot)
    assert hardware.read_rgbd_frame_file(path, camera_config, now=NOW)["depth_m"][1, 2] == 0


def test_atomic_writer_replaces_only_a_complete_snapshot(tmp_path, camera_config, snapshot, monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    path = save_archive(tmp_path / "frame.npz", snapshot)
    old_bytes = path.read_bytes()
    updated = deepcopy(snapshot)
    updated["rgb"][:] = 123
    real_replace = os.replace
    replacements = []

    def inspect_then_replace(source, destination):
        assert path.read_bytes() == old_bytes
        complete = hardware.read_rgbd_frame_file(source, camera_config, now=NOW)
        assert np.all(complete["rgb"] == 123)
        assert os.stat(source).st_dev == path.stat().st_dev
        replacements.append((source, destination))
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", inspect_then_replace)
    hardware.write_rgbd_frame_file(updated, path)
    assert len(replacements) == 1
    assert np.all(hardware.read_rgbd_frame_file(path, camera_config, now=NOW)["rgb"] == 123)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert {item.name for item in tmp_path.iterdir()} == {"frame.npz"}


def test_failed_atomic_replace_preserves_previous_frame_and_cleans_temporary_file(tmp_path, snapshot, monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    path = save_archive(tmp_path / "frame.npz", snapshot)
    old_bytes = path.read_bytes()

    def fail_replace(*args):
        raise OSError("simulated full destination filesystem")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated full"):
        hardware.write_rgbd_frame_file(snapshot, path)
    assert path.read_bytes() == old_bytes
    assert {item.name for item in tmp_path.iterdir()} == {"frame.npz"}


def test_writer_refuses_root_before_creating_output_directories(tmp_path, snapshot, monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    path = tmp_path / "must-not-create" / "frame.npz"
    with pytest.raises((ValueError, RuntimeError, PermissionError), match="(?i)root|privilege"):
        hardware.write_rgbd_frame_file(snapshot, path)
    assert not path.parent.exists()


@pytest.mark.parametrize("failure", ["missing", "corrupt", "stale", "wrong-serial"])
def test_configured_bridge_failure_never_falls_back_to_opening_the_sdk(tmp_path, camera_config, snapshot, monkeypatch, failure):
    path = tmp_path / "frame.npz"
    if failure == "corrupt":
        path.write_bytes(b"not an npz camera frame")
    elif failure != "missing":
        changes = {"timestamp": np.array(NOW - 20)} if failure == "stale" else {"serial": np.array("OTHER")}
        save_archive(path, snapshot, **changes)
    monkeypatch.setenv("NONO_RGBD_FRAME_FILE", str(path))
    monkeypatch.setattr(hardware.time, "time", lambda: NOW)
    monkeypatch.setattr(hardware, "ROOT", tmp_path)

    def forbidden_sdk(*args, **kwargs):
        pytest.fail("A configured frame-file failure must never open the Orbbec SDK")

    monkeypatch.setattr(hardware, "AlignedRGBDSession", forbidden_sdk)
    with pytest.raises((ValueError, OSError)):
        hardware.capture_top(camera_config)


def test_configured_bridge_reads_valid_file_without_importing_or_opening_sdk(tmp_path, camera_config, snapshot, monkeypatch):
    path = save_archive(tmp_path / "frame.npz", snapshot)
    monkeypatch.setenv("NONO_RGBD_FRAME_FILE", str(path))
    monkeypatch.setattr(hardware.time, "time", lambda: NOW)
    monkeypatch.setattr(hardware, "ROOT", tmp_path)

    def forbidden_sdk(*args, **kwargs):
        pytest.fail("The frame-file bridge must not construct an SDK session")

    monkeypatch.setattr(hardware, "AlignedRGBDSession", forbidden_sdk)
    frame = hardware.capture_top(camera_config)
    assert frame["serial"] == SERIAL
    np.testing.assert_array_equal(frame["rgb"], snapshot["rgb"])
