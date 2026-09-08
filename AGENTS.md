# Working on NONO

This repository is a local React + Python robotics workbench. Read README.md for the implemented milestone and calibration limits.

* Python code lives in backend/chessbot; the API is the single owner of game state. MCP must proxy it rather than create an independent game.
* Keep metric units explicit: metres/radians in simulation, pixels in images, metres in aligned depth. Physical LeRobot degrees and gripper 0–100 are separate and not currently mapped.
* White starts a1–h1/a2–h2. Name camera corners explicitly rather than assuming image rotation. Preserve the original camera image.
* Sample fixtures are not physical measurements. Camera-derived geometry must retain residuals, provenance, and missing-data status. Never silently fall back to a nominal scale after measurement failure.
* Preserve legal-move validation and ordered capture transfers, including en passant and castling. A plan preview must not consume capture slots or mutate the game.
* Current execution is simulation-only. Keep endpoint IK, collision checks, contact verification, and physical motion capability distinct in results and UI.
* Gemini is Orbbec SDK-only; never OpenCV-open its depth node. Wrist selection uses UID/name and rejects phone/virtual/depth cameras.
* Run `uv run pytest` for backend changes and `npm run build` in web for frontend changes. Keep upstream mesh license and pinned provenance when changing robot assets.
* Teammates work in their own clones/branches; do not switch branches in a running server checkout. Read CONTRIBUTING.md and docs/team-server.md for deployment and shared access.
* Shared runtime access uses per-client credentials and an exclusive operator lease. Inspect ownership, acquire before mutations, renew while working, and release when idle. Observers can read without a lease.
* Never commit team-access files or tokens. The server has no remote shell/deployment endpoint; tests on your local branch and tests against the running server revision are different evidence.
