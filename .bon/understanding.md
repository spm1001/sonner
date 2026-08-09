# Understanding

Sonner rings a repo, and a Claude answers. The CLI works and is installed fleet-adjacent (tube + Mac); the open work is plugin citizenship (son-rewota) and making the roster honest about sessions it can see but not reach.

## The session taxonomy (measured on tube, 2026-08-09 evening)

Three classes of live session, and sonner's view of each:

| Class | Record | Socket | sonner today |
|---|---|---|---|
| Terminal, first-party billed (Max) | full | yes | listed, ringable |
| Terminal, Vertex-billed (`claudev`/`claudefv`, `--settings` env block) | full, `messagingSocketPath` absent | never | **invisible** — reads as empty repo (son-nukuzi) |
| Remote-control child (iOS app) | full incl. socket path | yes | listed, ringable |

The evening census: 8 live sessions, 5 of them deaf Vertex ones — the invisible class was the *majority*. `--list` showing 3 sessions was true for delivery and false for a human.

**Remote control mechanics:** `claude remote-control` daemons run under the user systemd, one per directory (8 on tube: gueridon, infra, ~/repos, home, notes, bon, sonde, mise-en-space — this is Guéridon's substrate). When the iOS app opens a session, the daemon spawns a child running `claude --print --sdk-url https://api.anthropic.com/v1/code...` which registers and binds a socket like any terminal session. RC and Vertex are mutually exclusive — CC refuses `claude rc` when `CLAUDE_CODE_USE_VERTEX` is set (api.anthropic.com only) — so **rc sessions are never deaf**. Live-tested 2026-08-09 (~21:30 and ~21:52, messages to modha-7a; evidence in `~/.claude/logs/claude-remote-home-modha.log`): delivery works and is peer-framed. Arriving **mid-task**, the message queues and never gets a turn once the task completes (the phone showed an unread badge on a session its list view hides). Arriving **idle**, it *wakes* the session, which acts and completes a turn. rc sessions are genuinely persistent — one session handled a morning SSH debug and an evening infra task. Reply asymmetry measured from the far end: the woken session couldn't resolve the deaf sender's `from` address, guessed, and misdelivered its ack to the session in the tmux session named `sonner-infra-signboard` — sonner's own spawn-naming was the decoy (grammar consequences on son-butowo).

## Discovery design (post son-sotize)

Sockets are the roster, records are enrichment — and since son-sireto, **env vars are hints layered on uid-derived ground truth**: `/run/user/<uid>/cc-socks` is swept even with `XDG_RUNTIME_DIR` unset, and homes come from both `$HOME` and the passwd database. The forcing incident: the receptionnaire mail harness (HOME=/srv/receptionnaire/home, no XDG_RUNTIME_DIR) saw an empty machine past three live sessions, spawned a duplicate, and timed out after 180s. Tests neutralize the uid-derived roots via `cli._RUN_USER` and a patched `pwd.getpwuid` — keep that pattern or the fake-estate tests leak the real machine.

## The grammar (agreed with Sameer and shipped 2026-08-09, son-fomuno)

Ring by repo or `--name`; `--wake` ensures without delivering; `--work` spawns claudefv (readiness = registry record appearing, never a socket). Exact-cwd match beats deeper sessions. Deaf-occupied repos are refused with an explanation, never doubled. Deaf delivery exists in exactly one form — Sameer's verdict: message dropped to `~/.local/state/sonner/drops/` (passwd-home-derived) with full peer framing, spawn prompt carrying only the pointer. Caller identity: sonner walks the process tree to find its enclosing session; a socketed caller's name goes in `from` (replies route), a deaf/absent caller gets `script:` + a do-not-reply footer. Proven live: a `--work` ring into the empty bon repo spawned claudefv, and the session read the drop and executed it.

Operational facts learned doing it:

- **`tmux kill-session` orphans the spawned claude** — it survives reparented to systemd. Kill by pid; claude cleans its own registry record on SIGTERM.
- **`--work` depends on the tmux server's environment, not the caller's.** `bash -ic claudefv` sources `$HOME/.bashrc` — with a running tmux server that's modha's env and works; if a foreign-env caller (receptionnaire shape) ever starts the *first* tmux server, its HOME propagates and `claudefv` won't resolve. Watch item, not built around: the composed mail-inbox → work-spawn path has not run live end-to-end.
- The socketed-caller reply route is fixture-tested only (a deaf session, which built it, cannot exercise it live).
