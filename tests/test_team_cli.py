import importlib.util
import json
import os
import plistlib
import shlex
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from chessbot import team_cli


@pytest.fixture
def access(tmp_path):
    path = tmp_path / "config" / "team-access.json"
    team_cli.initialize(path)
    return path


def test_init_creates_private_files_without_changing_existing_repo_directory(tmp_path):
    folder = tmp_path / "config"
    folder.mkdir(mode=0o755)
    path = folder / "team-access.json"
    team_cli.initialize(path)
    assert json.loads(path.read_text()) == {"version": 1, "clients": []}
    assert path.stat().st_mode & 0o777 == 0o600
    assert folder.stat().st_mode & 0o777 == 0o755
    with pytest.raises(FileExistsError):
        team_cli.initialize(path)


def test_add_prints_only_metadata_and_hashes_token_in_access_file(access, tmp_path, capsys):
    output = tmp_path / "private" / "alice.token"
    result = team_cli.main(["add", "--access-file", str(access), "--name", "Alice", "--role", "operator", "--token-output", str(output)])
    assert result == 0
    token = output.read_text().strip()
    printed = capsys.readouterr()
    clients = team_cli.load_access(access)["clients"]
    assert token.startswith("nono_") and len(token) > 40
    assert clients[0]["token_sha256"] == team_cli.hashlib.sha256(token.encode()).hexdigest()
    assert token not in printed.out + printed.err + access.read_text()
    assert clients[0]["token_sha256"] not in printed.out
    assert json.loads(printed.out)["token_file"] == str(output)
    assert output.stat().st_mode & 0o777 == 0o600
    assert output.parent.stat().st_mode & 0o777 == 0o700


def test_duplicate_name_and_existing_token_output_never_replace_credentials(access, tmp_path):
    output = tmp_path / "alice.token"
    team_cli.add_client(access, "Alice", "viewer", output)
    before = access.read_bytes(), output.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        team_cli.add_client(access, "alice", "operator", tmp_path / "second.token")
    with pytest.raises(FileExistsError):
        team_cli.add_client(access, "Bob", "viewer", output)
    assert (access.read_bytes(), output.read_bytes()) == before
    assert not (tmp_path / "second.token").exists()


def test_revoke_by_name_or_id_is_persistent_and_list_omits_hashes(access, tmp_path):
    from chessbot.team_access import load_access_file

    added = team_cli.add_client(access, "Alice", "operator", tmp_path / "alice.token")
    assert not load_access_file(access)[added["id"]].revoked
    assert team_cli.revoke_client(access, "alice")["revoked"]
    assert team_cli.revoke_client(access, added["id"])["revoked"]
    assert team_cli.list_clients(access) == [{"id": added["id"], "name": "Alice", "role": "operator", "revoked": True}]
    assert team_cli.load_access(access)["clients"][0]["revoked"]
    assert load_access_file(access)[added["id"]].revoked
    assert access.stat().st_mode & 0o777 == 0o600


def test_concurrent_adds_do_not_lose_clients(access, tmp_path):
    with ThreadPoolExecutor(max_workers=4) as executor:
        jobs = [executor.submit(team_cli.add_client, access, f"Person {i}", "viewer", tmp_path / f"person-{i}.token")
                for i in range(4)]
        results = [job.result() for job in jobs]
    assert len(team_cli.list_clients(access)) == len(results) == 4


def test_corrupt_access_and_symlink_token_outputs_are_rejected(access, tmp_path):
    original = tmp_path / "original"
    original.write_text("preserve")
    output = tmp_path / "symlink.token"
    output.symlink_to(original)
    with pytest.raises(ValueError, match="symbolic-link"):
        team_cli.add_client(access, "Alice", "viewer", output)
    assert original.read_text() == "preserve"
    access.write_text('{"version": 2, "clients": []}')
    with pytest.raises(ValueError, match="schema"):
        team_cli.add_client(access, "Bob", "viewer", tmp_path / "bob.token")
    assert not (tmp_path / "bob.token").exists()


def test_doctor_reads_only_specific_local_resources(access, monkeypatch):
    commands = []
    monkeypatch.setattr(team_cli.sys, "platform", "darwin")
    monkeypatch.setattr(team_cli.shutil, "which", lambda name: f"/mock/{name}")

    def probe(command):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="state = running" if command[0].endswith("launchctl") else "100.64.0.10\n")

    def no_server(*args, **kwargs):
        raise OSError("no server")

    monkeypatch.setattr(team_cli, "_probe", probe)
    monkeypatch.setattr(team_cli.socket, "create_connection", no_server)
    result = team_cli.doctor(access)
    assert not result["local_server_listening"]
    assert result["launchd"]["running"]
    assert result["tailscale"]["local_ipv4"] == "100.64.0.10"
    assert commands == [["/mock/launchctl", "print", f"gui/{os.getuid()}/com.nono.chess-server"], ["/mock/tailscale", "ip", "-4"]]


@pytest.fixture
def service_generator():
    path = Path(__file__).resolve().parents[1] / "scripts" / "server_macos.py"
    spec = importlib.util.spec_from_file_location("server_macos", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_checkout(tmp_path):
    checkout = tmp_path / "checkout with $(literal)"
    executable = checkout / ".venv" / "bin" / "nono-server"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n")
    config = checkout / "config.json"
    config.write_text("{}")
    access = checkout / "team-access.json"
    access.write_text('{"version":1,"clients":[]}')
    return checkout, config, access


def test_launchagent_generation_is_private_reviewable_and_shell_quoted(tmp_path, service_generator):
    checkout, config, access = make_checkout(tmp_path)
    result = service_generator.generate(checkout, tmp_path / "generated", access, config,
                                        "https://robot.example.ts.net", server_ref="abc123")
    assert not result["installed"]
    plist_path, wrapper = Path(result["plist"]), Path(result["wrapper"])
    payload = plistlib.loads(plist_path.read_bytes())
    assert payload["ProgramArguments"] == [str(wrapper)]
    assert payload["EnvironmentVariables"] == {
        "NONO_ACCESS_FILE": str(access), "NONO_CONFIG": str(config),
        "NONO_PUBLIC_ORIGIN": "https://robot.example.ts.net", "NONO_PORT": "8011", "NONO_SERVER_REF": "abc123",
    }
    assert shlex.split(wrapper.read_text().splitlines()[-1]) == ["exec", str(checkout / ".venv/bin/nono-server")]
    assert plist_path.stat().st_mode & 0o777 == 0o600
    assert wrapper.stat().st_mode & 0o777 == 0o700
    assert wrapper.parent.stat().st_mode & 0o777 == 0o700
    with pytest.raises(ValueError, match="already exist"):
        service_generator.generate(checkout, wrapper.parent, access, config, "https://robot.example.ts.net", server_ref="abc123")


@pytest.mark.parametrize("origin", ["http://robot.example.ts.net", "https://user:password@robot.example.ts.net", "https://robot.example.ts.net/?token=bad"])
def test_launchagent_rejects_insecure_or_credential_bearing_origin(tmp_path, service_generator, origin):
    checkout, config, access = make_checkout(tmp_path)
    with pytest.raises(ValueError):
        service_generator.generate(checkout, tmp_path / "generated", access, config, origin, server_ref="abc123")
    assert not (tmp_path / "generated").exists()
