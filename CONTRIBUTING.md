# Working together on NONO

Each teammate develops in their own clone or worktree. The Mac runs one shared cell from a known server checkout. A local branch does not change the running server; its revision is visible in the console and through Codex.

## Branches and pull requests

With Write access to `imandyww/astra-hack-2026-robosim`:

```bash
git clone https://github.com/imandyww/astra-hack-2026-robosim.git
cd astra-hack-2026-robosim
git switch -c codex/yourname-description
make setup
# Develop with your own Codex task; keep local camera configuration ignored.
make test
npm --prefix web test
make build
git add <specific-files>
git commit -m "Describe the change"
git push -u origin HEAD
gh pr create --base main --draft
```

With Read access, fork the repository first:

```bash
gh repo fork imandyww/astra-hack-2026-robosim --clone
cd astra-hack-2026-robosim
git remote -v
git switch -c codex/yourname-description
make setup
# Implement changes in your fork.
make test
npm --prefix web test
make build
git add <specific-files>
git commit -m "Describe the change"
git push -u origin HEAD
gh pr create --repo imandyww/astra-hack-2026-robosim --base main --head YOUR-GITHUB-USERNAME:codex/yourname-description --draft
```

Replace `YOUR-GITHUB-USERNAME` and the branch name with your own values. After `gh repo fork --clone`, `origin` should point to your fork and `upstream` to `imandyww/astra-hack-2026-robosim`; verify the displayed remotes before pushing. This path works without upstream Write permission.

The repository owner can grant collaborators Write access if a common branch workflow is preferred. GitHub repository access and shared-server access are separate: being able to open a PR does not grant camera or operator access.

## Use the shared cell from Codex

Follow [the team server guide](docs/team-server.md) for the owner-supplied private endpoint, your individually issued credential file, and MCP configuration. Your Codex runs the MCP adapter locally and makes authenticated HTTPS requests to the Mac. Tailscale access does not require shell access to the Mac; the optional SSH tunnel requires an existing SSH account.

1. Read `get_server_info`, `get_environment`, and `get_control`.
2. Claim `acquire_control` before camera capture, calibration, planning, or simulated moves.
3. Renew your lease while working, then call `release_control` when the cell is idle.
4. Record the running server revision in your PR’s validation section.

Observers can inspect state while someone else operates. An operation against the shared server runs the server's installed code, not your local branch's backend. Validate backend changes locally before requesting deployment of a reviewed commit.

## Review and deployment

Recommended `main` rules, configured by a repository administrator: require a PR and at least one review, require the `python` and `web` checks, and block force pushes. The workflow files are provided here; changing GitHub branch rules requires administrator permission.

Use GitHub-hosted CI for PRs. Do not register the physical robot Mac as a runner for untrusted pull requests. While the cell is idle, the server owner stops the service, promotes an explicitly reviewed commit into its dedicated checkout, installs locked dependencies, runs Python and frontend tests, and builds the console. Regenerate the reviewed service artifacts for that commit before restarting so the recorded deployment reference stays current. Teammates should never `git checkout` feature branches in the running server's directory.

The shared server has no arbitrary shell, file-write, deployment, or real-motor endpoint. Physical execution remains unimplemented. Keep access-token files, `config/local.json`, `config/team-access.json`, and captured artifacts out of Git.
