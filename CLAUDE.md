# Sonner

Ring a repo, and a Claude answers — repo-addressed messaging for Claude Code sessions.

`SendMessage` addresses a *session*; sonner addresses a *repo*, which is usually what you mean. A live session in the repo gets the message on its inbox socket; an empty repo gets a session spawned under tmux first, so the message still lands as a **peer message** rather than a user prompt. Born 2026-08-09 from the native cross-session-messaging review (`aboyeur/docs/native-xsm-review-2026-08-08.md` — the measurements behind every design choice here).

## Quick Commands

```bash
uv run --group dev pytest          # run tests
uv tool install .                  # put `sonner` on PATH
sonner --list                      # every reachable session and its repo
sonner REPO "message"              # ring (spawns if nobody's home)
```

## Module Map

| Module | Role |
|--------|------|
| `cli` | The whole tool: discovery (sockets + registries), wire-format delivery, tmux spawn, argparse `main()` |

One module is a deliberate choice — this is a doorbell, not a framework. Split only when a second consumer of discovery actually exists.

## Key Conventions

- **Stdlib only.** No dependencies, ever — sonner must run anywhere `uv` exists, including a Mac over non-interactive ssh.
- **Sockets are the roster; registry records are enrichment.** Every session binds `<pid>.sock` in a shared socket dir; records live under *each config dir's* `sessions/` (`~/.claude`, `~/.claude-commis`, any `~/.claude-*`), so reading one registry silently hides sessions homed in another. Discovery unions sockets across known layouts (`$XDG_RUNTIME_DIR/cc-socks`, `/tmp/cc-socks` on macOS, `/tmp/cc-socks-<uid>`) with every record's own `messagingSocketPath`. Don't "simplify" this to a single source — each half catches sessions the other misses (learned the hard way, 2026-08-09).
- **Every message is timestamped by default.** Claude Code silently drops byte-identical repeat messages *while reporting success to the sender*. `--no-stamp` exists for genuine one-offs; do not make it the default.
- **Spawn-then-deliver, never prompt-injection.** Passing the message as the spawned session's prompt would make it read as the user speaking. Delivering over the socket after the session binds keeps peer framing and the harness's peer guardrails.
- **Cold-spawn needs a trusted cwd.** A session spawned into a directory Claude Code doesn't trust stalls at the folder-trust dialog and never binds its socket — the ring times out looking like a slow start. Trust the repo first (or attach to the tmux session and answer the dialog).
- **Deaf sessions exist: a live session with no inbox.** Vertex/provider-billed sessions write a full registry record with the `messagingSocketPath` field absent — reachable by nothing, but present and busy (measured 2026-08-09). son-nukuzi tracks surfacing them instead of reporting their repo empty.
- **`from` in the envelope is display/reply-routing only** — receivers verify identity via `SO_PEERCRED` on the connecting process. Don't build anything that trusts the `from` string.
- **The companion skill (`skills/peer-messaging/`) carries the house habits** — addressing forms, wake-or-file test, machine-register replies. The live copy on this machine is still `~/.claude/skills/peer-messaging/` until the plugin ships; keep them in step (son board tracks the handover).

## Wire format (captured, not documented upstream)

One newline-terminated JSON line to the socket:

```json
{"msgV":1,"msg_id":"<uuid>","type":"user",
 "message":{"role":"user","content":"<cross-session-message from=\"...\" from-name=\"...\" from-mode=\"prompting\">\nBODY\n</cross-session-message>"},
 "priority":"next","from":"<reply address>"}
```

Captured from a real `SendMessage` on CC 2.1.226 (2026-08-08). Upstream may version it — `msgV` is the canary, and a delivery that stops working after a CC upgrade should check this first.

Work is tracked on a bon board in `.bon/` — read `.bon/README.md` before reading or changing anything there.
