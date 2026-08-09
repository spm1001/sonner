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

**Remote control mechanics:** `claude remote-control` daemons run under the user systemd, one per directory (8 on tube: gueridon, infra, ~/repos, home, notes, bon, sonde, mise-en-space — this is Guéridon's substrate). When the iOS app opens a session, the daemon spawns a child running `claude --print --sdk-url https://api.anthropic.com/v1/code...` which registers and binds a socket like any terminal session. RC and Vertex are mutually exclusive — CC refuses `claude rc` when `CLAUDE_CODE_USE_VERTEX` is set (api.anthropic.com only) — so **rc sessions are never deaf**. Whether a peer message delivered to an rc child *surfaces on the phone* was live-tested 2026-08-09 (~21:30, message to modha-7a); check the son board / handoff for the verdict.

## Discovery design (post son-sotize)

Sockets are the roster, records are enrichment — and since son-sireto, **env vars are hints layered on uid-derived ground truth**: `/run/user/<uid>/cc-socks` is swept even with `XDG_RUNTIME_DIR` unset, and homes come from both `$HOME` and the passwd database. The forcing incident: the receptionnaire mail harness (HOME=/srv/receptionnaire/home, no XDG_RUNTIME_DIR) saw an empty machine past three live sessions, spawned a duplicate, and timed out after 180s. Tests neutralize the uid-derived roots via `cli._RUN_USER` and a patched `pwd.getpwuid` — keep that pattern or the fake-estate tests leak the real machine.

## Grammar gaps (observed, not yet designed)

- Repo addressing picks the newest session in the subtree: ringing `/home/modha` to reach the phone session actually targets whichever repo session under it is newest. No name-addressing in the CLI yet.
- A Vertex spawn can't reuse `spawn()` as-is: `claudefv` is a commons-managed shell *function* (not argv-swappable), and readiness would have to key on the registry record appearing, since no socket ever will.
- Delivery to a deaf session has no peer route at all; the candidate fallback is wake-or-file (durable message in a file, spawn prompt carries only a pointer) — bends the spawn-then-deliver convention, needs Sameer's verdict.
