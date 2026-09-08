"""Camera-only RGB-D worker; open USB, discard root, publish private snapshots.

On macOS, when libusb needs elevated access to detach the UVC kernel driver:
sudo /absolute/.venv/bin/python -B -m chessbot.camera_worker \
    --config /absolute/local.json --output /absolute/rgbd/top.npz

No server, socket, shell command, motor command or persistent root service is
created here. The SDK handles remain open after the process becomes the sudo
invoker. Press Ctrl-C to stop and release the camera.
"""

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

# Also avoid lazy SDK import caches during the privileged part of a console-
# script invocation. `python -B -m ...` is required to cover initial imports.
sys.dont_write_bytecode = True

from .config import load_config, validate_board
from .hardware import AlignedRGBDSession, write_rgbd_frame_file


def sudo_identity(environ: dict | None = None) -> tuple[int, int] | None:
    """Resolve the nonroot sudo invoker before opening any device."""
    if os.geteuid() != 0:
        return None
    environ = os.environ if environ is None else environ
    try:
        raw_uid, raw_gid = environ["SUDO_UID"], environ["SUDO_GID"]
        if not isinstance(raw_uid, str) or not raw_uid.isdecimal() or not isinstance(raw_gid, str) or not raw_gid.isdecimal():
            raise ValueError
        uid, gid = int(raw_uid), int(raw_gid)
        if not 0 < uid < 2**31 or not 0 < gid < 2**31:
            raise ValueError
        return uid, gid
    except (KeyError, TypeError, ValueError) as exc:
        raise PermissionError("Refusing root camera worker without nonroot SUDO_UID and SUDO_GID. "
                              "Invoke it manually with sudo from your ordinary user account.") from exc


def drop_privileges(identity: tuple[int, int] | None = None) -> None:
    """Permanently drop supplementary groups, group ID, then all user IDs."""
    if os.geteuid() != 0:
        return
    identity = sudo_identity() if identity is None else identity
    uid, gid = identity
    if not isinstance(uid, int) or not isinstance(gid, int) or uid <= 0 or gid <= 0:
        raise PermissionError("Privilege drop requires a nonroot user and group.")
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    if os.geteuid() == 0 or os.getuid() != uid or os.getgid() != gid or os.getegid() != gid:
        raise PermissionError("Camera worker failed to drop root privileges completely.")


def run_worker(config: dict, output: str | Path, *, interval_seconds: float = 0.5,
               max_frames: int | None = None, session_factory=None) -> None:
    """Warm the enrolled pipeline before privilege drop; write at most two Hz.

    A first valid frame is required before root is discarded because a deferred
    SDK stream open would otherwise fail after the handoff. There is no attempt
    to reacquire privilege or reopen a failing stream. A stopped worker leaves
    its last file in place; consumers must enforce the three-second age limit.
    """
    if not math.isfinite(interval_seconds) or interval_seconds < 0.5:
        raise ValueError("Camera worker output rate must be at most 2 Hz.")
    if max_frames is not None and (isinstance(max_frames, bool) or not isinstance(max_frames, int) or max_frames < 1):
        raise ValueError("max_frames must be a positive integer.")
    identity = sudo_identity()
    session = (AlignedRGBDSession if session_factory is None else session_factory)(config)
    try:
        frame = session.start()
        drop_privileges(identity)
        if os.geteuid() == 0:
            raise PermissionError("Refusing camera output: process still has root privileges.")
        published = 0
        next_publication = time.monotonic()
        while True:
            now = time.monotonic()
            if now >= next_publication:
                write_rgbd_frame_file(frame, output)
                published += 1
                if published == 1:
                    height, width = frame["rgb"].shape[:2]
                    print(f"Camera ready: UID {os.geteuid()}, aligned RGB-D {width}×{height}, "
                          f"private snapshot {output}", flush=True)
                if max_frames is not None and published >= max_frames:
                    return
                # Base the period on the completed publication so expensive
                # compression can never cause a burst exceeding two Hz.
                next_publication = time.monotonic() + interval_seconds
            # Drain the SDK at camera rate rather than sleeping with queued old
            # frames. Only publish the latest complete pair at the capped rate.
            frame = session.read_frame()
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Absolute enrolled configuration path; does not rely on sudo preserving env")
    parser.add_argument("--output", type=Path, required=True, help="Absolute private NPZ snapshot path")
    parser.add_argument("--fps", type=float, default=2.0, help="Snapshot publication rate, greater than zero and at most two (default: 2)")
    parser.add_argument("--once", action="store_true", help="Publish one frame after privilege drop, then stop")
    args = parser.parse_args()
    if not args.output.is_absolute() or (args.config is not None and not args.config.is_absolute()):
        parser.error("--output and --config must be absolute paths")
    if not math.isfinite(args.fps) or not 0 < args.fps <= 2:
        parser.error("--fps must be finite, greater than zero and at most two")
    try:
        # Refuse an invalid root invocation before even reading app config.
        sudo_identity()
        if args.config is None:
            config = load_config()
        else:
            config = json.loads(args.config.read_text())
            validate_board(config["board"])
        run_worker(config, args.output, interval_seconds=1.0 / args.fps, max_frames=1 if args.once else None)
    except KeyboardInterrupt:
        return
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Camera worker stopped: {exc}\n")


if __name__ == "__main__":
    main()
