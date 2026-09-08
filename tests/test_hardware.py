"""Resolve identities from synthetic inventories without opening devices."""

import pytest
from chessbot.hardware import resolve_wrist

WRIST = {"unique_id": "wrist-uid", "match": "icspring"}


def test_wrist_exact_uid_wins_over_reordered_indices_and_same_named_devices():
    devices = [
        {"index": 0, "name": "icspring camera", "unique_id": "other-wrist"},
        {"index": 8, "name": "icspring camera", "unique_id": "wrist-uid"},
        {"index": 2, "name": "Orbbec Gemini 336", "unique_id": "top-uid"},
    ]
    assert resolve_wrist(devices, WRIST)["index"] == 8


def test_wrist_refuses_ambiguous_name_matches_instead_of_using_index():
    devices = [{"index": index, "name": "icspring camera", "unique_id": str(index)} for index in (1, 3)]
    with pytest.raises(ValueError, match="exactly one"):
        resolve_wrist(devices, WRIST)


@pytest.mark.parametrize("name", ["Orbbec Gemini 336", "Gemini 336", "OBS Virtual Camera", "FaceTime HD", "iPhone Continuity Camera"])
def test_wrist_never_opens_top_or_virtual_camera_even_if_uid_matches(name):
    devices = [{"index": 0, "name": name, "unique_id": "wrist-uid"}]
    with pytest.raises(ValueError):
        resolve_wrist(devices, WRIST)


def test_wrist_requires_an_identity_match_not_first_video_device():
    with pytest.raises(ValueError):
        resolve_wrist([{"index": 0, "name": "USB Camera", "unique_id": "unregistered"}], WRIST)
