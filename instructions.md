# Sonner — Instruction Shard

Auto-loaded via `~/.claude/rules/sonner.md`, symlinked at session start by this
plugin's `hooks/ensure-sonner.sh` — edit `instructions.md` in the source repo,
never the copy in `rules/`.

**Invoke the `peer-messaging` skill BEFORE any `SendMessage`, `ListAgents` or
`sonner` call, and when a cross-session peer message arrives** — use the exact
name your skills listing shows (`sonner:peer-messaging` under the plugin
install; bare `peer-messaging` as a user skill). The skill
carries the house protocol; this shard holds only what bites before you would
think to load it:

- **`sonner REPO "message"` rings a repo, not a session.** A live session there
  gets a peer message on its inbox socket; an empty repo gets a session spawned
  first. `sonner --list` shows who is reachable. It is a CLI on PATH, not an
  MCP tool.
- **Address `SendMessage` with the full `name [ref]` form from the ListAgents
  row** (e.g. `idle-target [79cf80]`) — the bare name is refused for
  cross-session peers, costing a round trip.
- **A repeated byte-identical message is silently dropped while the sender is
  told success.** Vary the text of anything you repeat — sonner stamps every
  message by default for exactly this reason.
