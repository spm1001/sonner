"""Discovery tests, each guarding a failure that actually happened (2026-08-09).

The config-dir sweep exists because a session homed in ~/.claude-commis was
invisible to a reader of ~/.claude/sessions, and sonner watched the wrong
letterbox for 90 seconds. The socket-union exists because macOS binds sockets
in a layout no registry dir predicted.
"""

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from sonner import cli


@pytest.fixture
def estate(tmp_path, monkeypatch):
    """A fake machine: two config dirs, one socket dir, three sessions.

    - pid 1 (init, alive-but-not-ours): record in ~/.claude, socket present
    - our own pid: socket only, no record anywhere (the commis-gap shape)
    - a reaped child pid: record and socket both present, process gone
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    sock_dir = tmp_path / "runtime" / "cc-socks"
    sock_dir.mkdir(parents=True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    # Discovery also sweeps uid-derived roots that ignore the env; point them
    # back into the fake estate so the real machine can't leak in.
    monkeypatch.setattr(cli, "_RUN_USER", tmp_path / "run-user-absent")
    monkeypatch.setattr(cli.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(tmp_path)))

    def record(config: str, pid: int, cwd: str, name: str) -> None:
        d = tmp_path / config / "sessions"
        d.mkdir(parents=True, exist_ok=True)
        sock = sock_dir / f"{pid}.sock"
        sock.touch()
        (d / f"{pid}.json").write_text(
            json.dumps(
                {
                    "pid": pid,
                    "cwd": cwd,
                    "name": name,
                    "messagingSocketPath": str(sock),
                    "startedAt": 1000 + pid,
                }
            )
        )

    record(".claude", 1, "/repo/alpha", "alpha-11")

    (sock_dir / f"{os.getpid()}.sock").touch()  # live, recordless

    dead = subprocess.Popen(["true"])
    dead.wait()
    record(".claude-commis", dead.pid, "/repo/beta", "beta-22")

    return tmp_path


def test_records_swept_across_config_dirs(estate):
    records = cli.session_records()
    assert 1 in records, "record in ~/.claude missed"
    assert any(r.get("name") == "beta-22" for r in records.values()), (
        "record in ~/.claude-commis missed — the commis gap is back"
    )


def test_live_sessions_socket_truth(estate):
    by_pid = {s.pid: s for s in cli.live_sessions()}

    assert 1 in by_pid, "alive-but-not-ours pid (PermissionError) should count as live"
    assert by_pid[1].name == "alpha-11"
    assert by_pid[1].cwd == cli.Path("/repo/alpha")

    me = os.getpid()
    assert me in by_pid, "recordless socket must still be discovered"
    assert by_pid[me].cwd is not None, "/proc should place a recordless local session"

    assert len(by_pid) == 2, "the dead session's record+socket should be excluded"


def test_sessions_in_matches_repo_and_subdirs(estate):
    assert [s.name for s in cli.sessions_in(cli.Path("/repo/alpha"))] == ["alpha-11"]
    assert cli.sessions_in(cli.Path("/repo")) != [], "parent dir should match sessions below it"
    assert cli.sessions_in(cli.Path("/repo/gamma")) == []


def test_pick_prefers_exact_cwd_over_deeper():
    """Ringing /home/u reaches the session AT /home/u, not a newer one deeper in."""
    deeper = cli.Session(
        pid=2, cwd=cli.Path("/home/u/repos/x"), socket=cli.Path("/s/2.sock"), name="x-2", started=2000
    )
    exact = cli.Session(
        pid=3, cwd=cli.Path("/home/u"), socket=cli.Path("/s/3.sock"), name="home-3", started=1000
    )
    assert cli.pick([deeper, exact], cli.Path("/home/u")) == [exact]
    assert cli.pick([deeper], cli.Path("/home/u")) == [deeper], "no exact match: newest wins as before"
    assert cli.pick([], cli.Path("/home/u")) == []


def test_discovery_survives_a_rewritten_environment(tmp_path, monkeypatch):
    """The receptionnaire shape: HOME points somewhere barren, XDG_RUNTIME_DIR unset.

    Everything real is keyed on the uid — sockets under /run/user/<uid>/cc-socks,
    records under the passwd-database home — and three live sessions vanished
    behind the env-only sweep while a duplicate spawned beside them (2026-08-09).
    Discovery must not need the caller's env to see the machine.
    """
    barren = tmp_path / "srv-home"
    barren.mkdir()
    monkeypatch.setenv("HOME", str(barren))
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    real_home = tmp_path / "passwd-home"
    monkeypatch.setattr(cli.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(real_home)))
    monkeypatch.setattr(cli, "_RUN_USER", tmp_path / "run" / "user")

    sock_dir = tmp_path / "run" / "user" / str(os.getuid()) / "cc-socks"
    sock_dir.mkdir(parents=True)
    me = os.getpid()
    (sock_dir / f"{me}.sock").touch()

    sessions = real_home / ".claude" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / f"{me}.json").write_text(
        json.dumps(
            {
                "pid": me,
                "cwd": "/repo/delta",
                "name": "delta-33",
                "messagingSocketPath": str(sock_dir / f"{me}.sock"),
                "startedAt": 2000,
            }
        )
    )

    by_pid = {s.pid: s for s in cli.live_sessions()}
    assert me in by_pid, "socket under /run/user/<uid> missed when XDG_RUNTIME_DIR is unset"
    assert by_pid[me].name == "delta-33", (
        "record under the passwd-database home missed when HOME points elsewhere"
    )
