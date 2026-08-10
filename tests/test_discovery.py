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


def test_by_name(estate):
    assert [s.pid for s in cli.by_name("alpha-11")] == [1]
    assert cli.by_name("nobody-99") == []


def test_name_with_repo_and_message_is_refused(estate, monkeypatch):
    monkeypatch.setattr("sys.argv", ["sonner", "/repo/alpha", "hello", "--name", "alpha-11"])
    with pytest.raises(SystemExit):
        cli.main()


def test_unknown_name_fails_showing_roster(estate, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["sonner", "--name", "nobody-99", "hi"])
    assert cli.main() == 1
    err = capsys.readouterr().err
    assert "nobody-99" in err
    assert "alpha-11" in err, "the roster should be shown so the caller can correct the name"


def test_wake_reports_existing_without_spawning(estate, monkeypatch, capsys):
    wake_repo = estate / "wake-repo"
    wake_repo.mkdir()
    me = os.getpid()
    sock = estate / "runtime" / "cc-socks" / f"{me}.sock"
    (estate / ".claude" / "sessions" / f"{me}.json").write_text(
        json.dumps(
            {"pid": me, "cwd": str(wake_repo), "name": "waked-55",
             "messagingSocketPath": str(sock), "startedAt": 4000}
        )
    )
    monkeypatch.setattr(cli, "spawn", lambda repo: pytest.fail("spawned beside a live session"))
    monkeypatch.setattr(cli, "spawn_work", lambda repo: pytest.fail("spawned beside a live session"))
    monkeypatch.setattr("sys.argv", ["sonner", "--wake", str(wake_repo)])
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "already awake" in out
    assert "waked-55" in out
    assert "deaf" not in out


def test_wake_sees_deaf_session_and_refuses_to_double(estate, monkeypatch, capsys):
    """The socket roster can't see a deaf session; the record sweep must."""
    deaf_repo = estate / "deaf-repo"
    deaf_repo.mkdir()
    deaf_pid = os.getppid()  # alive, not pid 1, and holds no socket in the estate
    (estate / ".claude" / "sessions" / f"{deaf_pid}.json").write_text(
        json.dumps({"pid": deaf_pid, "cwd": str(deaf_repo), "name": "deaf-44", "startedAt": 3000})
    )
    monkeypatch.setattr(cli, "spawn", lambda repo: pytest.fail("spawned a sibling beside a deaf session"))
    monkeypatch.setattr(cli, "spawn_work", lambda repo: pytest.fail("spawned a sibling beside a deaf session"))
    monkeypatch.setattr("sys.argv", ["sonner", "--wake", str(deaf_repo)])
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "deaf-44" in out
    assert "deaf" in out, "the human must be told the session is unreachable, not just that it exists"


def test_spawn_work_readiness_keys_on_registry_record(estate, monkeypatch):
    """A work session never binds a socket — the record appearing IS readiness."""
    work_repo = estate / "work-repo"
    work_repo.mkdir()
    me = os.getpid()

    def fake_tmux(repo, argv):
        assert argv == ["bash", "-ic", "claudefv"], "work spawn must go through an interactive shell"
        (estate / ".claude" / "sessions" / f"{me}.json").write_text(
            json.dumps({"pid": me, "cwd": str(work_repo), "name": "work-66", "startedAt": 5000})
        )
        return "rung-work-repo"

    monkeypatch.setattr(cli, "_tmux_spawn", fake_tmux)
    s = cli.spawn_work(work_repo, timeout=5)
    assert s.name == "work-66"
    assert s.socket is None
    assert s.pid == me


def test_work_ring_drops_file_and_points_at_it(estate, monkeypatch, capsys):
    empty_repo = estate / "empty-repo"
    empty_repo.mkdir()
    seen = {}

    def fake_spawn_work(repo, timeout=180.0, prompt=None):
        seen["prompt"] = prompt
        return cli.Session(pid=99, cwd=repo, socket=None, name="work-99", started=1)

    monkeypatch.setattr(cli, "spawn_work", fake_spawn_work)
    monkeypatch.setattr("sys.argv", ["sonner", str(empty_repo), "the deadman went red", "--work"])
    assert cli.main() == 0

    prompt = seen["prompt"]
    assert prompt is not None
    assert "peer" in prompt, "the pointer must name the framing"
    drop = cli.Path(prompt.split("awaits at ")[1].split(" —")[0])
    content = drop.read_text()
    assert "the deadman went red" in content, "the payload lives in the file, framed"
    assert "<cross-session-message" in content
    assert "the deadman went red" not in prompt, "the prompt carries the pointer, never the payload"


def test_ring_refuses_deaf_occupied_repo(estate, monkeypatch, capsys):
    deaf_repo = estate / "deaf-ring-repo"
    deaf_repo.mkdir()
    deaf_pid = os.getppid()
    (estate / ".claude" / "sessions" / f"{deaf_pid}.json").write_text(
        json.dumps({"pid": deaf_pid, "cwd": str(deaf_repo), "name": "deaf-77", "startedAt": 6000})
    )
    monkeypatch.setattr(cli, "spawn", lambda *a, **k: pytest.fail("spawned beside a deaf session"))
    monkeypatch.setattr(cli, "spawn_work", lambda *a, **k: pytest.fail("spawned beside a deaf session"))
    monkeypatch.setattr("sys.argv", ["sonner", str(deaf_repo), "anyone home?"])
    assert cli.main() == 1
    err = capsys.readouterr().err
    assert "deaf-77" in err
    assert "cannot be delivered" in err


def test_calling_session_walks_to_enclosing_record(estate, monkeypatch):
    sock = estate / "runtime" / "cc-socks" / "50.sock"
    (estate / ".claude" / "sessions" / "50.json").write_text(
        json.dumps(
            {"pid": 50, "cwd": "/repo/caller", "name": "caller-50",
             "messagingSocketPath": str(sock), "startedAt": 7000}
        )
    )
    monkeypatch.setattr(cli.os, "getppid", lambda: 100)
    monkeypatch.setattr(cli, "_ppid", {100: 50}.get)
    caller = cli.calling_session()
    assert caller is not None
    assert caller.name == "caller-50"
    assert caller.socket is not None


def test_calling_session_never_matches_init(estate, monkeypatch):
    """pid 1 has a record in the fixture — the walk must stop before it."""
    monkeypatch.setattr(cli.os, "getppid", lambda: 100)
    monkeypatch.setattr(cli, "_ppid", {100: 1}.get)
    assert cli.calling_session() is None


def test_sender_identity_three_shapes(monkeypatch):
    socketed = cli.Session(pid=5, cwd=None, socket=cli.Path("/s/5.sock"), name="alive-5", started=1)
    deaf = cli.Session(pid=6, cwd=None, socket=None, name="deaf-6", started=1)

    monkeypatch.setattr(cli, "calling_session", lambda: socketed)
    display, from_addr, footer = cli.sender_identity(None)
    assert (display, from_addr, footer) == ("alive-5", "alive-5", None)

    monkeypatch.setattr(cli, "calling_session", lambda: deaf)
    display, from_addr, footer = cli.sender_identity(None)
    assert display == "deaf-6"
    assert from_addr == "script:deaf-6", "a deaf caller must not present a resolvable-looking address"
    assert footer and "do not attempt a reply" in footer

    monkeypatch.setattr(cli, "calling_session", lambda: None)
    display, from_addr, footer = cli.sender_identity("custom")
    assert (display, from_addr) == ("custom", "script:custom")
    assert footer is not None


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


def test_spawn_joins_the_home_session_as_a_window(monkeypatch):
    """One tmux session, one window per repo (Sameer, 2026-08-10).

    Session-per-spawn scattered live Claudes across sessions a tab bar cannot
    show — it lists only the windows of the session you are attached to.
    """
    calls = []
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/tmux")

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "has-session":
            return SimpleNamespace(returncode=0)  # home session already exists
        return SimpleNamespace(returncode=0, stdout="@42\n", text="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    window = cli._tmux_spawn(cli.Path("/repos/spm1001/infra"), ["claude"])

    assert window == "@42", "the durable coordinate is the window id, not a session name"
    probe, spawn = calls
    assert probe == ["tmux", "has-session", "-t", "=claude"], (
        "bare 'claude' prefix-matches — a session named claude-anything would swallow spawns"
    )
    assert spawn[:3] == ["tmux", "new-window", "-d"], "a window, and never stealing focus"
    assert "-t" in spawn and spawn[spawn.index("-t") + 1] == "=claude:"
    assert spawn[spawn.index("-n") + 1] == "infra", (
        "-n names the tab AND disables automatic-rename, which otherwise overwrites it"
    )
    assert "new-session" not in spawn


def test_spawn_creates_the_home_session_when_absent(monkeypatch):
    """A cold machine has no home session — make it, don't fall back to per-repo."""
    calls = []
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/tmux")

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "has-session":
            return SimpleNamespace(returncode=1)  # nothing running
        return SimpleNamespace(returncode=0, stdout="@0\n", text="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    cli._tmux_spawn(cli.Path("/repos/spm1001/infra"), ["claude"])

    spawn = calls[1]
    assert spawn[:5] == ["tmux", "new-session", "-d", "-s", "claude"]
    assert spawn[spawn.index("-n") + 1] == "infra"
