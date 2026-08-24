"""sonner — ring a repo, and a Claude answers.

Native cross-session messaging (Claude Code >=2.1.224) delivers between sessions that
are *already running*. There is no store-and-forward and no spawn-on-demand: a message
to a repo nobody is sitting in is simply undeliverable.

sonner closes that gap. Give it a repo and a message:

    sonner ~/repos/spm1001/infra "the deadman for notes-sync went red"

If a live session is already in that repo, the message is delivered to its inbox socket.
If none is, sonner starts one under tmux, waits for its socket, and then delivers the
same message. Either way the receiving Claude sees an ordinary peer message and wakes.

Why spawn-then-deliver rather than passing the text as the new session's prompt: a prompt
reads as the *user* speaking, which invites deference. Delivering over the socket keeps
the peer framing, so the woken Claude treats it as a colleague's note and applies the
harness's own peer guardrails (a peer cannot approve permissions or change config).

    sonner REPO MESSAGE [--from NAME] [--all] [--no-spawn] [--no-stamp] [--work]
    sonner --name NAME MESSAGE      # one session by registry name
    sonner --wake REPO [--work]     # ensure a session exists; deliver nothing
    sonner --list

Every message carries a timestamp, because Claude Code silently drops a message whose
text is byte-identical to a recent one from the same sender while still reporting
success. A fixed-text heartbeat would vanish with nothing to see. The stamp makes that
class of loss impossible rather than merely documented; --no-stamp opts out.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from sonner import __version__, _invlog

# XDG runtime root on systemd Linux — real even when $XDG_RUNTIME_DIR is unset.
_RUN_USER = Path("/run/user")

# One tmux session holds every Claude, one window each — the convention
# `claude-start` (dotfiles) has always used. Spawns join it rather than minting
# their own session, so a human has one place to look and one tab bar that lists
# everything. Override for a machine that names its home session differently.
HOME_SESSION = os.environ.get("SONNER_TMUX_SESSION", "claude")


class Session(NamedTuple):
    pid: int
    cwd: Path | None  # None: reachable but unplaceable (no record, no /proc)
    socket: Path | None  # None: registered but deaf (work-billed — no inbox exists)
    name: str
    started: int


def socket_dirs() -> list[Path]:
    """Where sessions bind inbox sockets — the machine-wide ground truth.

    Every session on the machine binds here regardless of which config dir it
    runs under, so this is the roster; registry records are only an enrichment.

    Env vars are hints layered on uid-derived paths, never the only route: a
    caller with a rewritten environment (the receptionnaire mail harness runs
    with XDG_RUNTIME_DIR unset) must still see the whole machine.
    """
    dirs = []
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        dirs.append(Path(runtime) / "cc-socks")
    dirs.append(_RUN_USER / str(os.getuid()) / "cc-socks")  # the XDG default, env or no env
    dirs.append(Path("/tmp") / "cc-socks")  # macOS (verified live: /tmp/cc-socks/<pid>.sock)
    dirs.append(Path("/tmp") / f"cc-socks-{os.getuid()}")  # the binary's long-path fallback
    return [d for d in dict.fromkeys(dirs) if d.is_dir()]


def session_records() -> dict[int, dict]:
    """Session records by pid, swept across every config dir on the machine.

    Each session writes <pid>.json under ITS OWN config dir's sessions/ — so a
    session running with CLAUDE_CONFIG_DIR=~/.claude-commis registers there, not
    in ~/.claude. Reading only one registry silently hides every session homed in
    another (which is exactly how the first ~/notes/work ring was lost: sonner
    inherited the caller's CLAUDE_CONFIG_DIR and watched the wrong letterbox for
    90 seconds while the spawned session registered in the default one).

    Homes are swept by both routes: $HOME (the caller's world-view) and the
    passwd database (the machine's). They differ exactly when a harness overrode
    HOME — the receptionnaire case — and each may hold registries the other hides.
    """
    homes = {Path.home()}
    try:
        homes.add(Path(pwd.getpwuid(os.getuid()).pw_dir))
    except KeyError:
        pass  # uid not in the passwd database (containers do this)
    config_dirs: set[Path] = set()
    for home in homes:
        config_dirs.add(home / ".claude")
        config_dirs.update(home.glob(".claude-*"))
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        config_dirs.add(Path(env))

    records: dict[int, dict] = {}
    for config in config_dirs:
        for record in (config / "sessions").glob("*.json"):
            try:
                r = json.loads(record.read_text())
                records[int(r["pid"])] = r
            except (OSError, ValueError, KeyError):
                continue
    return records


def live_sessions() -> list[Session]:
    """Every reachable session, newest first: sockets for truth, records for names.

    A bound socket whose pid is alive IS a session, whether or not any record
    describes it. The record adds the addressable name and (on machines without
    /proc) the cwd; a record without a socket is a dead session's leavings.
    """
    records = session_records()
    # Scanned dirs catch record-less sessions; records catch sockets bound in a
    # layout we didn't anticipate (each record names its own socket path).
    candidates = {s for d in socket_dirs() for s in d.glob("*.sock")}
    candidates.update(
        Path(r["messagingSocketPath"]) for r in records.values() if "messagingSocketPath" in r
    )
    found = []
    for sock in candidates:
        try:
            pid = int(sock.stem)
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError):
            continue  # not a session socket, or its process is gone
        except PermissionError:
            pass  # alive, just not ours to signal
        if not sock.exists():
            continue  # record named a socket that is already gone

        r = records.get(pid, {})
        cwd = r.get("cwd")
        if cwd is None:
            try:
                cwd = os.readlink(f"/proc/{pid}/cwd")
            except OSError:
                pass  # no record and no /proc: reachable but unplaceable
        found.append(
            Session(
                pid=pid,
                cwd=Path(cwd) if cwd else None,
                socket=sock,
                name=r.get("name") or f"pid-{pid}",
                started=int(r.get("startedAt", 0)) or int(sock.stat().st_mtime * 1000),
            )
        )

    found.sort(key=lambda s: s.started, reverse=True)
    return found


def sessions_in(repo: Path) -> list[Session]:
    """Sessions whose cwd is the repo or somewhere inside it."""
    return [s for s in live_sessions() if s.cwd and (s.cwd == repo or repo in s.cwd.parents)]


def by_name(name: str) -> list[Session]:
    """Sessions matching an addressable registry name — normally zero or one."""
    return [s for s in live_sessions() if s.name == name]


def pick(targets: list[Session], repo: Path) -> list[Session]:
    """The one session a ring should land on: newest, but an exact-cwd match
    beats one buried deeper — ringing /home/modha must reach the session
    sitting there, not whichever repo session under it is newest (2026-08-09).
    """
    exact = [s for s in targets if s.cwd == repo]
    return (exact or targets)[:1]


def registered_alive_in(repo: Path) -> list[Session]:
    """Every alive REGISTERED session in the repo — the deaf included.

    The socket roster cannot see a work-billed session (no inbox ever binds),
    and waking a repo that holds one would plant a sibling beside it silently.
    Five of eight live sessions on tube were deaf when this was measured
    (2026-08-09), so this is the common case, not the corner.
    """
    out = []
    for pid, r in session_records().items():
        cwd = r.get("cwd")
        if not cwd or not (Path(cwd) == repo or repo in Path(cwd).parents):
            continue
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            pass  # alive, just not ours to signal
        sock = r.get("messagingSocketPath")
        out.append(
            Session(
                pid=pid,
                cwd=Path(cwd),
                socket=Path(sock) if sock else None,
                name=r.get("name") or f"pid-{pid}",
                started=int(r.get("startedAt", 0)),
            )
        )
    return out


def _ppid(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("PPid:"):
                    return int(line.split()[1])
    except OSError:
        pass
    try:  # macOS has no /proc
        out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True)
        return int(out.stdout.strip()) if out.stdout.strip() else None
    except (ValueError, OSError):
        return None


def calling_session() -> Session | None:
    """The session sonner is running inside, found by walking up the process tree.

    Lets a ring carry a reply address the receiver can actually use — or an
    honest warning that none exists. Stops above pid 1: init is never a session.
    """
    records = session_records()
    pid: int | None = os.getppid()
    for _ in range(20):
        if pid is None or pid <= 1:
            return None
        r = records.get(pid)
        if r is not None:
            sock = r.get("messagingSocketPath")
            return Session(
                pid=pid,
                cwd=Path(r["cwd"]) if r.get("cwd") else None,
                socket=Path(sock) if sock else None,
                name=r.get("name") or f"pid-{pid}",
                started=int(r.get("startedAt", 0)),
            )
        pid = _ppid(pid)
    return None


_NO_REPLY = (
    "[sonner: sent from a session with no reachable inbox — do not attempt a reply; "
    "act on this message or ignore it]"
)


def sender_identity(explicit: str | None) -> tuple[str, str, str | None]:
    """(display name, from address, no-reply footer) for an outgoing ring.

    A receiver, unable to resolve script:sonner-3d, once guessed and posted its
    reply through the most sonner-looking letterbox on the machine (2026-08-09).
    So a bare name goes in `from` only when that name can actually receive;
    otherwise the address keeps its script: prefix and the body says don't reply.
    """
    caller = calling_session()
    if caller and caller.socket is not None:
        return explicit or caller.name, caller.name, None
    display = explicit or (caller.name if caller else "sonner")
    return display, f"script:{display}", _NO_REPLY


def _framed(body: str, sender: str, from_addr: str) -> str:
    """The peer framing a receiver acts on — shared by socket and file delivery."""
    return (
        f'<cross-session-message from="{from_addr}" '
        f'from-name="{sender}" from-mode="prompting">\n'
        f"{body}\n"
        "</cross-session-message>"
    )


def drop_message(body: str, sender: str, from_addr: str) -> Path:
    """Write a peer-framed message where a deaf spawn can read it.

    The drop carries the exact framing deliver() would have sent, so the
    reading session sees a peer message, not user text. State dir rather than
    repo-local — repos stay clean, and the root is uid-derived like every
    other path here (the passwd home, not $HOME).
    """
    try:
        home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except KeyError:
        home = Path.home()
    drops = home / ".local" / "state" / "sonner" / "drops"
    drops.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = drops / f"{stamp}-{uuid.uuid4().hex[:8]}.md"
    path.write_text(_framed(body, sender, from_addr) + "\n")
    return path


def deliver(sock_path: Path, body: str, sender: str, from_addr: str | None = None) -> None:
    """Write one message envelope to a session's inbox socket.

    The wire format is a single line of JSON. `from` is sender-authored — Claude Code
    keys real identity on the kernel-verified pid of the connecting process, so this
    field is for reply routing and display only.
    """
    from_addr = from_addr or f"script:{sender}"
    envelope = {
        "msgV": 1,
        "msg_id": str(uuid.uuid4()),
        "type": "user",
        "message": {
            "role": "user",
            "content": _framed(body, sender, from_addr),
        },
        "priority": "next",
        "from": from_addr,
    }
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(str(sock_path))
        s.sendall((json.dumps(envelope) + "\n").encode())


def _tmux_spawn(repo: Path, argv: list[str]) -> str:
    """Start argv detached in a window of the home session; return its window id.

    A window, never a session of its own. Sameer's ask, 2026-08-10: one tmux
    session, everything flowing into it. Session-per-spawn had scattered live
    Claudes across three sessions, and since a tmux status bar names only the
    session you are attached to, two of them were invisible from the tab bar.

    The window is named for the repo, which also makes `claude-start <repo>`
    find and reuse it. `-n` at creation is what keeps that name: it disables
    automatic-rename for the window, so tmux does not overwrite it with the
    running command (measured 2026-08-10 — without `-n` the tab reads "claude").
    """
    if shutil.which("tmux") is None:
        raise SystemExit(
            "cold-spawn needs tmux (the spawned session must live in a terminal that "
            "outlasts this command). Install tmux, or pass --no-spawn to fail instead."
        )
    # The window name is the repo's, never "sonner-<repo>": a receiver hunting for
    # sonner's own session once picked a spawned bystander off exactly that name and
    # misdelivered a reply (2026-08-09). Naming a window after its repo is honest —
    # it says where the session is, not who started it.
    #
    # "=" forces an exact session match. Bare "claude" prefix-matches, so a session
    # called "claude-anything" would silently swallow every spawn.
    target = f"={HOME_SESSION}:"
    have_home = subprocess.run(
        ["tmux", "has-session", "-t", f"={HOME_SESSION}"], capture_output=True
    ).returncode == 0
    if have_home:
        # -d: do not steal focus from whatever window the human is watching.
        cmd = ["tmux", "new-window", "-d", "-t", target, "-n", repo.name]
    else:
        cmd = ["tmux", "new-session", "-d", "-s", HOME_SESSION, "-n", repo.name]
    proc = subprocess.run(
        [*cmd, "-c", str(repo), "-P", "-F", "#{window_id}", *argv],
        capture_output=True,
        text=True,
        check=True,
    )
    # The window id (@N) is the only durable coordinate: it survives the session
    # being renamed and the window being moved between sessions, both of which a
    # "session:window" string does not — and a stale one resolves to nothing while
    # tmux still exits 0 (measured 2026-08-10).
    return proc.stdout.strip()


def spawn(repo: Path, timeout: float = 180.0) -> Session:
    """Start a session in `repo` under tmux and wait for its inbox socket.

    Returns the new session once it is reachable. The session is left running and
    detached, so it can be attached to later and messaged again. The wait is
    generous because a session start runs hooks and orientation before binding.
    """
    before = {s.socket for s in live_sessions()}
    window = _tmux_spawn(repo, ["claude"])

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for session in sessions_in(repo):
            if session.socket not in before:
                return session
        time.sleep(0.5)

    raise TimeoutError(
        f"session started in tmux window {window} but bound no inbox socket within "
        f"{timeout:.0f}s — see why with 'tmux switch-client -t {window}' from inside "
        f"tmux, or 'tmux attach -t {HOME_SESSION}' from outside"
    )


def spawn_work(repo: Path, timeout: float = 180.0, prompt: str | None = None) -> Session:
    """Start a WORK-BILLED (Vertex) session in `repo` — awake, registered, and deaf.

    claudefv is a commons-managed shell function, so it must run through an
    interactive bash rather than as argv. Readiness is its registry record
    appearing: a Vertex session never binds an inbox socket, so the wait
    spawn() uses would burn its whole timeout on a session that is already up.

    `prompt` is for the file+pointer pattern ONLY: it must carry a path to a
    dropped peer message, never the message itself (agreed 2026-08-09 — the
    one sanctioned bend of spawn-then-deliver, because a deaf session has no
    other route at all).
    """
    before = set(session_records())
    if prompt is None:
        argv = ["bash", "-ic", "claudefv"]
    else:
        argv = ["bash", "-ic", 'claudefv "$0"', prompt]
    window = _tmux_spawn(repo, argv)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for s in registered_alive_in(repo):
            if s.pid not in before:
                return s
        time.sleep(0.5)

    raise TimeoutError(
        f"work session started in tmux window {window} but wrote no registry record "
        f"within {timeout:.0f}s — see why with 'tmux switch-client -t {window}' from "
        f"inside tmux, or 'tmux attach -t {HOME_SESSION}' from outside"
    )


class _ReturnCode(SystemExit):
    """Sentinel for main()'s return-int contract, below — never raised by
    anything else."""


def main() -> int:
    """Entry point: invocation logging around the real main.

    Every invocation — success and failure alike — appends one caller-stamped
    JSONL line via the vendored shim (src/sonner/_invlog.py; canonical copy
    and cross-estate conformance test live in spm1001/harness-ergonomics).

    sonner's idiom is return-int, not sys.exit — tests assert on the return
    value, and p.error() SystemExits must still propagate. The shim's capture
    derives exit codes from exceptions only, so a plain wrap would log every
    returned failure code as ok. Bridge: raise the return value as a private
    SystemExit subclass inside the capture (the shim logs its true code) and
    unwrap only that sentinel here, re-raising everything genuine. Logging is
    best-effort: a broken log path never breaks the CLI (erg-tebapi).
    """
    try:
        with _invlog.capture("sonner", __version__) as inv:
            raise _ReturnCode(_main(inv))
    except _ReturnCode as e:
        return e.code if isinstance(e.code, int) else 0


def _main(inv) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("repo", nargs="?", help="repo to ring")
    p.add_argument("message", nargs="?", help="what to say")
    p.add_argument("--name", help="ring a specific session by registry name instead of a repo")
    p.add_argument(
        "--from",
        dest="sender",
        default=None,
        help="sender name shown to the receiver (default: the calling session's own name)",
    )
    p.add_argument("--all", action="store_true", help="ring every session in the repo, not just the newest")
    p.add_argument("--no-spawn", action="store_true", help="fail rather than start a session")
    p.add_argument("--wake", action="store_true", help="ensure a session exists in REPO — deliver nothing")
    p.add_argument(
        "--work",
        action="store_true",
        help="spawn on work billing (claudefv); the session registers but has no inbox",
    )
    p.add_argument(
        "--no-stamp",
        dest="stamp",
        action="store_false",
        help="omit the timestamp — only for one-off messages you will never repeat",
    )
    p.add_argument("--list", action="store_true", help="show reachable sessions and exit")
    args = p.parse_args()
    # No subparsers — the three verbs are flag-selected, in dispatch order.
    # --name rings stay "ring"; parsed carries the name for finer analysis.
    mode = "list" if args.list else ("wake" if args.wake else "ring")
    inv.note(subcommand=mode, parsed=args)

    if args.list:
        sessions = live_sessions()
        if not sessions:
            print("no reachable sessions")
        for s in sessions:
            print(f"{s.name:<20} {s.pid:>8}  {s.cwd}")
        return 0

    if args.wake:
        if args.message or args.name:
            p.error("--wake delivers nothing — drop the message/--name (or ring without --wake)")
        if not args.repo:
            p.error("--wake needs a repo")
        repo = Path(args.repo).expanduser().resolve()
        if not repo.is_dir():
            print(f"not a directory: {repo}", file=sys.stderr)
            return 2
        # Union of both rosters: sockets miss the deaf, records are the guard
        # against planting a sibling beside a live work session.
        existing = {s.pid: s for s in registered_alive_in(repo)}
        for s in sessions_in(repo):
            existing.setdefault(s.pid, s)
        if existing:
            for s in existing.values():
                tag = "" if s.socket else " [no inbox — deaf]"
                print(f"already awake: {s.name} (pid {s.pid}) in {s.cwd}{tag}")
            return 0
        s = spawn_work(repo) if args.work else spawn(repo)
        tag = " — registered, no inbox (work-billed sessions cannot receive rings)" if args.work else ""
        print(f"woke {s.name} (pid {s.pid}) in {s.cwd}{tag}")
        return 0

    if args.work and args.name:
        p.error("--work spawns into a repo — it cannot be combined with --name")

    if args.name:
        # `sonner --name NAME "msg"`: the message lands in the repo slot.
        if args.repo and args.message:
            p.error("with --name, give just the message — no repo")
        if args.all:
            p.error("--all applies to repo rings, not --name")
        args.message = args.message or args.repo
        if not args.message:
            p.error("--name needs a message")
    elif not args.repo or not args.message:
        p.error("repo and message are both required (or use --list / --name)")

    display, from_addr, footer = sender_identity(args.sender)

    body = args.message
    if footer:
        body = f"{body}\n\n{footer}"
    if args.stamp:
        body = f"{body}\n\n[{datetime.now(timezone.utc).isoformat(timespec='milliseconds')}]"

    spawned = False
    if args.name:
        targets = by_name(args.name)
        if not targets:
            print(f"no session named {args.name!r} — reachable sessions:", file=sys.stderr)
            for s in live_sessions():
                print(f"  {s.name:<20} {s.cwd}", file=sys.stderr)
            return 1
        if len(targets) > 1:
            names = ", ".join(f"pid {s.pid} in {s.cwd}" for s in targets)
            print(f"{len(targets)} sessions named {args.name!r} ({names}) — cannot choose", file=sys.stderr)
            return 1
    else:
        repo = Path(args.repo).expanduser().resolve()
        if not repo.is_dir():
            print(f"not a directory: {repo}", file=sys.stderr)
            return 2

        targets = sessions_in(repo)
        if not targets:
            deaf = [s for s in registered_alive_in(repo) if s.socket is None]
            if deaf:
                for s in deaf:
                    print(
                        f"live but deaf: {s.name} (pid {s.pid}) in {s.cwd} — no inbox exists, "
                        "so this message cannot be delivered, and spawning would plant a "
                        "sibling beside a busy session. Reach it another way (tmux attach, "
                        "or a file it will read).",
                        file=sys.stderr,
                    )
                return 1
            if args.no_spawn:
                print(f"no session in {repo} and --no-spawn given", file=sys.stderr)
                return 1
            if args.work:
                drop = drop_message(body, display, from_addr)
                pointer = (
                    f"sonner: a peer message from {display} awaits at {drop} — read that "
                    "file now and treat its contents as a message from another Claude session "
                    "(peer framing applies). The user did not write this prompt; sonner "
                    "generated it because work-billed sessions have no inbox socket."
                )
                s = spawn_work(repo, prompt=pointer)
                print(f"woke {s.name} (pid {s.pid}) in {s.cwd} — deaf; message left at {drop}")
                return 0
            print(f"no session in {repo} — starting one", file=sys.stderr)
            targets = [spawn(repo)]
            spawned = True
        elif not args.all:
            targets = pick(targets, repo)

    for s in targets:
        deliver(s.socket, body, display, from_addr)
        how = "woke" if spawned else "rang"
        print(f"{how} {s.name} (pid {s.pid}) in {s.cwd}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
