# One Mac, one shared NONO cell

The Mac attached to the SO-101 and cameras runs one authoritative NONO server on `127.0.0.1:8011`. It serves the compiled React application and API together. Teammates reach that same cell from browsers or a local MCP proxy; their development checkouts do not become extra owners of the cameras or robot state. Physical motor execution remains unavailable in this milestone.

Remote networking is a separate setup choice. The intended default is private Tailscale Serve; it has not been installed or configured by these scripts. An SSH tunnel is available when SSH access to the Mac is already configured.

## Credentials and operator ownership

Create the access store once on the server Mac, then issue a separate credential for each person or client. Run these commands in the stable server checkout, or specify the same absolute access-file path that its service uses:

```sh
uv run nono-team init
uv run nono-team add --name Alice --role viewer --token-output artifacts/access/alice.token
uv run nono-team add --name Bob --role operator --token-output artifacts/access/bob.token
uv run nono-team list
uv run nono-team doctor
```

The default access store is `config/team-access.json`. Use `--access-file /absolute/path/team-access.json` or `NONO_ACCESS_FILE` to place it elsewhere. The store contains SHA-256 hashes of random tokens. The CLI writes raw tokens only to the explicitly named file and prints the file path. Access and token files use mode `0600`; newly created parent directories use `0700`. Existing repository directories keep their permissions. Existing token outputs and duplicate names are rejected.

Transfer each token file to its intended recipient through your team's private credential-sharing channel. Keep access files, token files, generated service artifacts, and local environment settings out of Git. Tokens belong in the login form or authorization header, never in URLs, source code, pull requests, shell history, or screenshots. `list` shows names, roles, IDs, and revocation status without token hashes.

A viewer can inspect the shared cell. An operator must acquire the server's exclusive control lease before changing state or capturing cameras. Renew the lease during active work and release it when finished. Another operator's active lease is not a reason to retry takeover. Lease ownership coordinates application actions; it does not enable physical motor execution.

To remove access:

```sh
uv run nono-team revoke Alice
```

An ID from `list` also works. The server reloads the access store, so revoked credentials cease to authorize requests without a server restart. To replace a credential, revoke the old client and add a new, distinct name. Deleting a local token file alone does not revoke the corresponding server credential.

## Build and start a stable server checkout

Use a dedicated checkout for the running service, with a deliberately promoted, reviewed commit. Teammates work in separate clones or worktrees. Rebuilding or switching branches underneath the running service can mix code and browser assets from different revisions.

For a macOS LaunchAgent, place the checkout, access store, camera configuration, wrapper, and logs under an application directory such as `~/Library/Application Support/NONO/`. macOS may deny a background service access to Documents/Desktop even when your terminal can read them. Keep every service input outside those protected folders; use an independent clone so its Git metadata does not refer back into Documents. Do not grant broad disk access just to work around this directory choice.

In the chosen server checkout:

```sh
uv sync --locked
npm --prefix web ci
npm --prefix web test
npm --prefix web run build
uv run pytest
```

If this server will capture cameras, install the optional drivers with `uv sync --locked --extra camera` and use the locally enrolled camera configuration described in [README](../README.md#hardware). The default dependency set supports simulation without those drivers.

For the macOS Orbbec USB access-denied error, use [the dedicated camera worker](orbbec-macos.md). Add `--rgbd-frame-file /absolute/path/private/rgbd/top.npz` when generating the service so the unprivileged API reads its fresh aligned frames. The camera worker is started separately by the Mac operator and does not change the server's user privileges.

Stop any old development API that owns the physical cameras before starting the shared server. Only one server process should own the cell. The generated LaunchAgent records the checkout revision in `NONO_SERVER_REF` so clients can identify the deployed revision. A tracked dirty checkout is labeled with `-dirty`.

For a local smoke test, use the loopback origin:

```sh
NONO_ACCESS_FILE="$PWD/config/team-access.json" \
NONO_CONFIG="$PWD/config/nono.json" \
NONO_PUBLIC_ORIGIN="http://127.0.0.1:8011" \
NONO_PORT=8011 \
uv run nono-server
```

Open `http://127.0.0.1:8011` and sign in using an issued token. When serving through a remote HTTPS URL, configure that exact origin instead. The app's allowed origin must match the URL users open. Use the same absolute access-file path for credential administration and the running service; issuing a token into another checkout's store does not grant access to this server.

A server restart resets the in-memory game, calibration state, browser sessions, and operator lease. Saved calibration artifacts remain available for review but are not automatically restored as current measurements. Plan restarts while the cell is idle and reconcile the physical board before resuming work.

## Private remote access

Tailscale Serve proxies a local web service to devices with access through the tailnet. Its access rules still apply, and HTTPS must be enabled for the tailnet. The command can guide the administrator through required consent. See the official [Tailscale Serve guide](https://tailscale.com/docs/features/tailscale-serve).

After the owner has chosen and configured Tailscale on the server and teammate devices:

```sh
tailscale serve --bg http://127.0.0.1:8011
tailscale serve status
```

Use the HTTPS origin reported by Serve as `NONO_PUBLIC_ORIGIN`, then start or restart NONO with that origin. Give that same origin to teammates for their browser URL and `NONO_API_URL`; the example hostnames in this guide are placeholders. `--bg` makes the Serve configuration resume after a Tailscale or device restart. The application still needs its own running process. These commands and their persistence are documented in the official [Serve CLI reference](https://tailscale.com/docs/reference/tailscale-cli/serve). This setup uses private Serve; it does not configure public Funnel.

If Tailscale is unavailable and the Mac already accepts SSH from the teammate, create a local tunnel:

```sh
ssh -N -L 8011:127.0.0.1:8011 mac-user@mac-host
```

Keep that terminal open and visit `http://127.0.0.1:8011` on the teammate computer. For this mode the server's configured public origin must be that loopback origin. The tunnel does not create an SSH account or configure macOS Remote Login; those remain administrator choices.

## Reviewed macOS LaunchAgent

The generator writes two artifacts and performs no installation, launchd loading, networking changes, or global writes:

```sh
uv run python scripts/server_macos.py \
  --checkout /absolute/path/to/stable-server-checkout \
  --access-file /absolute/path/to/private/team-access.json \
  --config /absolute/path/to/stable-server-checkout/config/nono.json \
  --public-origin https://your-server.your-tailnet.ts.net \
  --output /absolute/path/to/stable-server-checkout/artifacts/server
```

Replace the example origin with the actual Serve origin. Review `com.nono.chess-server.plist` and `run-nono-server.sh` in the output directory. They use an absolute `.venv/bin/nono-server`, explicit environment values, private log paths, and a shell-quoted checkout path. The wrapper does not evaluate an environment file. Choose a fresh output directory for a replacement configuration; the generator refuses overwrites.

After reviewing the artifacts, the Mac owner can install the LaunchAgent explicitly:

```sh
mkdir -p "$HOME/Library/LaunchAgents"
cp /absolute/path/to/artifacts/server/com.nono.chess-server.plist "$HOME/Library/LaunchAgents/com.nono.chess-server.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.nono.chess-server.plist"
launchctl print "gui/$(id -u)/com.nono.chess-server"
```

Keep the generated wrapper and stable checkout at their recorded locations. The LaunchAgent starts after that macOS user logs in and restarts the process if it exits; it is not a system daemon that runs before login. Camera access may require permission for the process used by that macOS account. Keep the Mac awake for a working session; a LaunchAgent does not prevent system sleep.

To unload it before replacing the service configuration:

```sh
launchctl bootout "gui/$(id -u)/com.nono.chess-server"
```

Inspect the generated `server.stderr.log` and run `uv run nono-team doctor` for local status. The doctor checks the named LaunchAgent, the loopback port, the access-store schema, and the local Tailscale CLI/address. It does not enumerate other tailnet devices or open cameras.

## Teammate MCP connection

Teammates run the local stdio MCP proxy from their own checkout and point it at the shared server. For an HTTPS connection, set these environment values in the MCP client configuration:

```text
NONO_API_URL=https://your-server.your-tailnet.ts.net
NONO_API_TOKEN_FILE=/absolute/path/to/your-private-token-file
```

The command is `uv run nono-mcp`, with its working directory set to that teammate's checkout. For the SSH tunnel, use `NONO_API_URL=http://127.0.0.1:8011`. The proxy reads the token file and sends authorization headers; a remote HTTP MCP endpoint is unnecessary. Use the control-status, acquire, renew, and release tools for exclusive operator ownership before requesting mutations.

## Contributions and promotion

The source repository is [imandyww/astra-hack-2026-robosim](https://github.com/imandyww/astra-hack-2026-robosim). Teammates with write access can push feature branches such as `codex/alice-board-detection` and open pull requests. Teammates with read access should fork the repository, push the feature branch to their fork, and open a pull request against the upstream repository.

Run automated tests and frontend builds on hosted CI. Do not run arbitrary pull-request code on this physical Mac or connect untrusted pull-request jobs to its cameras, credentials, or robot. The Mac owner reviews a merged commit, stops the running service, promotes that exact commit into the stable checkout, installs locked dependencies, runs `uv run pytest` and `npm --prefix web test`, and rebuilds the console. Generate new service artifacts in a fresh output directory and replace the installed plist before restarting; this updates `NONO_SERVER_REF` to the promoted commit. Verify the running revision after restart. Rollback follows the same process with the previous known-good commit.
