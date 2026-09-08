# Orbbec USB access on macOS

`uvc_open failed ... Return Code: -3` is libuvc access denied. It is different from `-6`, resource busy. On this Mac, `LIBUSB_DEBUG=4` showed the actual failure while detaching Apple's driver from the Gemini USB interface:

```text
USB device capture requires either an entitlement (com.apple.vm.device-access) or root privilege
```

Camera privacy permission was granted, but raw USB access still failed. No competing application was reported by AVFoundation. Closing browsers or reopening the camera cannot fix this specific kernel-driver permission requirement.

The official [libusb macOS FAQ](https://github.com/libusb/libusb/wiki/FAQ#how-can-i-run-libusb-applications-under-macos-if-there-is-already-a-kernel-extension-installed-for-the-device-and-claim-exclusive-access) explains the entitlement/root requirement. [Orbbec's macOS troubleshooting](https://orbbec.github.io/pyorbbecsdk/source/3_QuickStarts/QuickStart.html#permission-denied-macos) documents a privileged SDK invocation. NONO confines privileged startup to a separate camera worker.

## Camera worker

The worker opens only the enrolled Gemini SDK device, starts synchronized color/depth streams, and obtains a valid aligned frame. It then permanently drops supplementary groups, group ID, and user ID to the user who invoked `sudo`. Only after dropping privileges does it publish private RGB-D snapshots. It has no network listener, shell endpoint, robot access, or automatic privilege escalation.

The ordinary API reads the worker's atomic snapshot file. It verifies camera identity, firmware, alignment, metric depth, dimensions, intrinsics, and freshness. Missing, malformed, stale, or future-dated data is rejected. No nominal dimensions or alternate camera are substituted.

In a local Terminal, using the installed server's absolute paths:

```sh
sudo '/absolute/path/server/.venv/bin/python' -B -m chessbot.camera_worker \
  --config '/absolute/path/private/local.json' \
  --output '/absolute/path/private/rgbd/top.npz'
```

Enter the administrator password only in that local Terminal. `-B` prevents Python from creating root-owned bytecode files during startup. Keep it open for the camera session. `Ctrl-C` stops the worker and releases the camera. Add `--once` to validate a single capture. A disconnect or SDK failure stops the worker; restart it locally when the device is ready. The worker does not install a root daemon or change sudo rules.

Configure the normal server with the same snapshot path:

```sh
NONO_RGBD_FRAME_FILE='/absolute/path/private/rgbd/top.npz' uv run nono-server
```

For the macOS service generator, pass `--rgbd-frame-file /absolute/path/private/rgbd/top.npz`. Regenerate and reload the service configuration as described in [the team guide](team-server.md). This selects the worker explicitly; an inaccessible SDK device never silently switches capture sources.

Use **Capture Gemini** in the console or `capture_board` through MCP. Successful output includes the original RGB image and aligned depth in metres. It supplies measurements for calibration; it does not calibrate the board or robot automatically.

## Boundaries

Do not launch the shared web/API server as root. Do not disable System Integrity Protection, remove Apple's camera drivers, or open Gemini's depth camera through OpenCV. The SDK captures the composite USB device, so other applications should release the Orbbec while this worker owns it.

The pinned firmware gate remains in effect. An unexpected firmware version is reported for review; the worker never flashes firmware. Real hardware behavior after dropping privileges must be verified with a live capture on the host, in addition to the automated tests.
