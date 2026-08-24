# Sonner

Ring a repo, and a Claude answers — repo-addressed messaging for Claude Code sessions.

`SendMessage` addresses a *session*; sonner addresses a *repo*, which is usually what you mean. A live session in the repo gets the message on its inbox socket; an empty repo gets a session spawned under tmux first, so the message still lands as a **peer message** rather than a user prompt. Born 2026-08-09 from the native cross-session-messaging review (`aboyeur/docs/native-xsm-review-2026-08-08.md` — the measurements behind every design choice here).

## Quick Commands

```bash
uv run --group dev pytest          # run tests
uv tool install .                  # put `sonner` on PATH
sonner --list                      # every reachable session and its repo
sonner REPO "message"              # ring (spawns if nobody's home)
sonner --name NAME "message"       # ring one session by registry name
sonner --wake REPO [--work]        # ensure a session exists (--work: claudefv, deaf by design)
sonner REPO "message" --work       # empty repo: work spawn + file-drop, prompt carries only the pointer
```

## Module Map

| Module | Role |
|--------|------|
| `cli` | The whole tool: discovery (sockets + registries), wire-format delivery, tmux spawn, argparse `main()` |

One module is a deliberate choice — this is a doorbell, not a framework. Split only when a second consumer of discovery actually exists.

## Key Conventions

- **Stdlib only.** No dependencies, ever — sonner must run anywhere `uv` exists, including a Mac over non-interactive ssh.
- **Sockets are the roster; registry records are enrichment.** Every session binds `<pid>.sock` in a shared socket dir; records live under *each config dir's* `sessions/` (`~/.claude`, `~/.claude-commis`, any `~/.claude-*`), so reading one registry silently hides sessions homed in another. Discovery unions sockets across known layouts (`$XDG_RUNTIME_DIR/cc-socks`, `/run/user/<uid>/cc-socks` even when that env var is unset, `/tmp/cc-socks` on macOS, `/tmp/cc-socks-<uid>`) with every record's own `messagingSocketPath`. Don't "simplify" this to a single source — each half catches sessions the other misses (learned the hard way, 2026-08-09).
- **Env vars are hints; the uid is ground truth.** Homes are swept by both `$HOME` and the passwd database — they differ exactly when a harness overrode HOME, which is how the receptionnaire mail session saw an empty machine, spawned a duplicate, and timed out (son-sotize, 2026-08-09). Never key discovery solely on the caller's environment.
- **Every message is timestamped by default.** Claude Code silently drops byte-identical repeat messages *while reporting success to the sender*. `--no-stamp` exists for genuine one-offs; do not make it the default.
- **Spawn-then-deliver, never prompt-injection — with exactly one sanctioned exception.** Passing the message as the spawned session's prompt would make it read as the user speaking. Delivering over the socket after the session binds keeps peer framing and the harness's peer guardrails. The exception (Sameer's verdict, 2026-08-09): a **deaf spawn** (`--work`) has no socket ever, so the message goes to a drop file with full peer framing and the prompt carries *only the pointer*. Never widen this: live sessions and socketed spawns keep the socket path.
- **Cold-spawn needs a trusted cwd.** A session spawned into a directory Claude Code doesn't trust stalls at the folder-trust dialog and never binds its socket — the ring times out looking like a slow start. Trust the repo first (or `tmux attach -t claude`, switch to the window named for the repo, and answer the dialog).
- **One tmux session, one window per repo — a spawn is a window, never a session.** `HOME_SESSION` (default `claude`, matching dotfiles' `claude-start`) is the single session everything joins; the window is named for the repo, which is also how `claude-start <repo>` finds and reuses it. This supersedes son-fomuno's `rung-<repo>` session-per-spawn, shipped the night before (Sameer, 2026-08-10) — a sequence, not a reversal: `rung-` fixed sonner's children masquerading as sonner, and this fixes them scattering. Why it matters: a tmux status bar lists only the windows of the session you are attached to, so a session-per-spawn estate hides most of itself. Two mechanics hold it up — `-t '=claude'` forces an exact session match (bare `claude` prefix-matches, and a session named `claude-anything` would swallow every spawn), and `-n <repo>` both labels the tab and disables `automatic-rename`, without which tmux overwrites the name with the running command and every tab reads "claude".
- **A tmux coordinate is only durable as `@window` / `%pane`.** Registry records store `tmux` as `<session>:@win.%pane`; the session-name half is a registration-time snapshot that rots on any rename or window move, and a stale target resolves to nothing while `tmux` still exits `0` — silent, not loud. Strip to the id (measured 2026-08-10, after merging the estate into one session made both events routine).
- **Deaf sessions exist: a live session with no inbox.** Vertex/provider-billed sessions write a full registry record with the `messagingSocketPath` field absent — reachable by nothing, but present and busy (measured 2026-08-09). son-nukuzi tracks surfacing them instead of reporting their repo empty.
- **`from` in the envelope is display/reply-routing only** — receivers verify identity via `SO_PEERCRED` on the connecting process. Don't build anything that trusts the `from` string.
- **The companion skill (`skills/peer-messaging/`) carries the house habits** — addressing forms, wake-or-file test, machine-register replies. **This directory is now the only copy that matters** (shipped 2026-08-24, suite 1.73.0): the plugin vendors it, and the old `~/.claude/skills/peer-messaging/` user copy was retired on tube the same day. A machine whose `~/.claude` clone is behind may still show a duplicate picker entry until it pulls — benign, and it clears itself.

## Plugin packaging (batterie)

sonner ships as a batterie plugin: `.claude-plugin/plugin.json` (SessionStart hook only), `hooks/ensure-sonner.sh` (symlinks `instructions.md` → `~/.claude/rules/sonner.md`, installs the CLI if missing), `instructions.md` (the thin always-on shard), `skills/peer-messaging/`. Three things to hold:

- **The assembler's skill-plugin copy-list ships no Python** — no `pyproject.toml`, no `src/`. The hook therefore installs from `git+https://github.com/spm1001/sonner` when running vendored (repo is public, stdlib-only), and from `$PLUGIN_ROOT` in a source checkout. Don't add a dependency without re-checking that path.
- **The vendored plugin.json version is the SUITE version** — the assembler stamps it. This repo's own `0.1.0` is local-dev-only; release via `/batterie:publish`, never a hand-bump.
- **A shard/skill/hook edit here is vendored content** — it ships only on a suite bump, and takes effect in sessions only after restart (guidance is session-cached).

## Wire format (captured, not documented upstream)

One newline-terminated JSON line to the socket:

```json
{"msgV":1,"msg_id":"<uuid>","type":"user",
 "message":{"role":"user","content":"<cross-session-message from=\"...\" from-name=\"...\" from-mode=\"prompting\">\nBODY\n</cross-session-message>"},
 "priority":"next","from":"<reply address>"}
```

Captured from a real `SendMessage` on CC 2.1.226 (2026-08-08). Upstream may version it — `msgV` is the canary, and a delivery that stops working after a CC upgrade should check this first.

Work is tracked on a bon board in `.bon/` — read `.bon/README.md` before reading or changing anything there.
