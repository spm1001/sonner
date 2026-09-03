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
    monkeypatch.setattr(cli, "_TMP", tmp_path / "tmp-absent")
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


# --- son-nukuzi: the deaf class in --list, and the discriminator's edges ---


def _deaf_record(estate, repo, name, pid=None, **extra) -> int:
    """A registry record with NO messagingSocketPath — what Claude Code writes
    for a provider-billed session. Defaults to our parent pid: alive, not 1, no
    socket in the estate."""
    pid = pid or os.getppid()
    body = {"pid": pid, "cwd": str(repo), "name": name, "startedAt": 9000, **extra}
    (estate / ".claude" / "sessions" / f"{pid}.json").write_text(json.dumps(body))
    return pid


def test_list_annotates_deaf_session(estate, monkeypatch, capsys):
    """--list must show a live-but-deaf session, marked — the socket roster
    alone reported its repo as empty, which is true for delivery and false for
    a human (5 of 8 live sessions on tube were this class, 2026-08-09)."""
    deaf_repo = estate / "deaf-list-repo"
    deaf_repo.mkdir()
    deaf_pid = _deaf_record(estate, deaf_repo, "deaf-88")
    monkeypatch.setattr("sys.argv", ["sonner", "--list"])
    assert cli.main() == 0
    out, err = capsys.readouterr()
    lines = out.splitlines()
    deaf_lines = [l for l in lines if "deaf-88" in l]
    assert len(deaf_lines) == 1, out
    assert str(deaf_pid) in deaf_lines[0]
    assert cli._DEAF_TAG in deaf_lines[0], "the annotation is the whole point"
    alpha = [l for l in lines if "alpha-11" in l]
    assert alpha and cli._DEAF_TAG not in alpha[0], "a socketed session must not be marked deaf"
    assert "no sessions" not in out
    assert "1 deaf" in err, "the summary line names the count"
    assert "--force-spawn" in err, "and tells the human the override exists"


def test_list_prints_each_session_once(estate, monkeypatch, capsys):
    """A socketed session has a record AND a socket — it must not appear twice."""
    monkeypatch.setattr("sys.argv", ["sonner", "--list"])
    assert cli.main() == 0
    out, err = capsys.readouterr()
    assert out.count("alpha-11") == 1, out
    assert err == "", "no deaf sessions, no summary line"


def test_list_with_no_sessions_says_so(estate, monkeypatch, capsys):
    monkeypatch.setattr(cli, "live_sessions", lambda: [])
    monkeypatch.setattr(cli, "deaf_sessions", lambda: [])
    monkeypatch.setattr("sys.argv", ["sonner", "--list"])
    assert cli.main() == 0
    assert capsys.readouterr().out.strip() == "no sessions"


def test_socket_gone_is_leavings_not_deaf(estate, monkeypatch, capsys):
    """The discriminator's other half: messagingSocketPath PRESENT but the
    socket gone is a dead session's record, however alive its pid looks (pids
    are reused). It must not be listed, and it must not block a --wake."""
    ghost_repo = estate / "ghost-repo"
    ghost_repo.mkdir()
    ghost_pid = _deaf_record(
        estate, ghost_repo, "ghost-99",
        messagingSocketPath=str(estate / "runtime" / "cc-socks" / "gone.sock"),
    )
    assert cli.registered_alive_in(ghost_repo) == []
    assert all(s.pid != ghost_pid for s in cli.deaf_sessions())

    monkeypatch.setattr("sys.argv", ["sonner", "--list"])
    assert cli.main() == 0
    out, _ = capsys.readouterr()
    assert "ghost-99" not in out

    spawned = []
    monkeypatch.setattr(cli, "spawn", lambda repo: spawned.append(repo) or cli.Session(
        pid=4242, cwd=repo, socket=cli.Path("/s/4242.sock"), name="fresh-42", started=1))
    monkeypatch.setattr("sys.argv", ["sonner", "--wake", str(ghost_repo)])
    assert cli.main() == 0
    assert spawned == [ghost_repo], "a ghost record must not read as 'already awake'"
    assert "fresh-42" in capsys.readouterr().out


def test_reused_pid_is_leavings_not_deaf(estate):
    """A deaf record has only its pid to vouch for it. CC writes procStart (the
    kernel's start-time ticks); a live process with a different start time is
    a different process wearing a dead session's pid. Control first: the same
    record with the TRUE procStart is a deaf session."""
    actual = cli._proc_start_ticks(os.getppid())
    if actual is None:
        pytest.skip("no /proc on this host — procStart cannot be checked here")
    repo = estate / "reused-repo"
    repo.mkdir()
    _deaf_record(estate, repo, "genuine-11", procStart=str(actual))
    assert [s.name for s in cli.registered_alive_in(repo)] == ["genuine-11"], (
        "control failed: a matching procStart must count as a live deaf session"
    )
    _deaf_record(estate, repo, "reused-22", procStart=str(actual + 1))
    assert cli.registered_alive_in(repo) == [], "a mismatched procStart is a reused pid"
    assert all(s.name != "reused-22" for s in cli.deaf_sessions())


def test_proc_start_ticks_reads_field_22():
    ticks = cli._proc_start_ticks(os.getpid())
    if ticks is None:
        pytest.skip("no /proc on this host")
    with open(f"/proc/{os.getpid()}/stat") as f:
        raw = f.read()
    assert ticks == int(raw.split()[21]), "field 22 by position, for a comm without spaces"
    assert cli._proc_start_ticks(2**22 + 1) is None, "an absent pid answers None, not an exception"


def _spawn_recorder(monkeypatch):
    """Stub spawn/deliver; return the lists they append to."""
    spawned, delivered = [], []

    def fake_spawn(repo, timeout=180.0):
        spawned.append(repo)
        return cli.Session(pid=4343, cwd=repo, socket=cli.Path("/s/4343.sock"), name="sib-43", started=1)

    monkeypatch.setattr(cli, "spawn", fake_spawn)
    monkeypatch.setattr(cli, "spawn_work", lambda *a, **k: pytest.fail("work spawn not asked for"))
    monkeypatch.setattr(cli, "deliver", lambda sock, body, sender, from_addr=None: delivered.append((sock, body)))
    return spawned, delivered


def test_ring_force_spawn_plants_sibling_beside_deaf(estate, monkeypatch, capsys):
    """Without the flag a deaf-occupied repo refuses (test_ring_refuses_deaf_occupied_repo);
    with it, the human has said 'yes, a sibling' — spawn, deliver, and say what happened."""
    repo = estate / "force-ring-repo"
    repo.mkdir()
    _deaf_record(estate, repo, "deaf-66")
    spawned, delivered = _spawn_recorder(monkeypatch)
    monkeypatch.setattr("sys.argv", ["sonner", str(repo), "anyone home?", "--force-spawn"])
    assert cli.main() == 0
    out, err = capsys.readouterr()
    assert spawned == [repo]
    assert len(delivered) == 1 and "anyone home?" in delivered[0][1]
    assert "woke sib-43" in out
    assert "deaf-66" in err and "--force-spawn" in err, "the override must be audible, never silent"


def test_wake_force_spawn_beside_deaf(estate, monkeypatch, capsys):
    repo = estate / "force-wake-repo"
    repo.mkdir()
    _deaf_record(estate, repo, "deaf-67")
    spawned, _ = _spawn_recorder(monkeypatch)
    monkeypatch.setattr("sys.argv", ["sonner", "--wake", str(repo), "--force-spawn"])
    assert cli.main() == 0
    out, err = capsys.readouterr()
    assert spawned == [repo]
    assert "woke sib-43" in out
    assert "deaf-67" in err


def test_wake_without_force_names_the_override(estate, monkeypatch, capsys):
    repo = estate / "hint-repo"
    repo.mkdir()
    _deaf_record(estate, repo, "deaf-68")
    monkeypatch.setattr(cli, "spawn", lambda *a, **k: pytest.fail("spawned without --force-spawn"))
    monkeypatch.setattr("sys.argv", ["sonner", "--wake", str(repo)])
    assert cli.main() == 0
    out, err = capsys.readouterr()
    assert "already awake" in out and cli._DEAF_TAG in out
    assert "--force-spawn" in err


def test_force_spawn_ignored_when_an_inbox_is_present(estate, monkeypatch, capsys):
    """--force-spawn is for deaf occupancy only. A repo that already has a
    ringable session gets no sibling, and the human is told the flag did nothing."""
    repo = estate / "socketed-repo"
    repo.mkdir()
    me = os.getpid()
    sock = estate / "runtime" / "cc-socks" / f"{me}.sock"
    (estate / ".claude" / "sessions" / f"{me}.json").write_text(json.dumps(
        {"pid": me, "cwd": str(repo), "name": "here-70", "messagingSocketPath": str(sock), "startedAt": 1}))
    _deaf_record(estate, repo, "deaf-71")  # a deaf one beside it, too
    spawned, delivered = _spawn_recorder(monkeypatch)

    monkeypatch.setattr("sys.argv", ["sonner", "--wake", str(repo), "--force-spawn"])
    assert cli.main() == 0
    out, err = capsys.readouterr()
    assert spawned == []
    assert "here-70" in out and "deaf-71" in out
    assert "ignored" in err

    monkeypatch.setattr("sys.argv", ["sonner", str(repo), "hi", "--force-spawn"])
    assert cli.main() == 0
    assert spawned == [], "a ring with an inbox present delivers; it never spawns"
    assert len(delivered) == 1


def test_force_spawn_contradictions_are_refused(estate, monkeypatch):
    for argv in (
        ["sonner", "/repo/alpha", "hi", "--force-spawn", "--no-spawn"],
        ["sonner", "--name", "alpha-11", "hi", "--force-spawn"],
    ):
        monkeypatch.setattr("sys.argv", argv)
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 2, argv
