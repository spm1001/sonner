# Handoff — 2026-08-24 (dispatched worker, son-sohowu prep legs)

purpose: Ship the in-repo legs of the sonner plugin (manifest, thin shard, banc pass) and bank a runbook for the publish legs, which the dispatch forbade this session
format: fond-v1

## For the next Claude

### Done

- **Plugin packaging shipped** (commits 1d70ce4, 9aaa967, 63fd499, all pushed): `.claude-plugin/plugin.json` (bon's shape, SessionStart hook only), `hooks/ensure-sonner.sh` (symlinks `instructions.md` → `~/.claude/rules/sonner.md`; installs the CLI if missing — local path in a source checkout, `git+https://github.com/spm1001/sonner` when vendored), `instructions.md` (the thin always-on shard: skill gate, ring-a-repo, `name [ref]` addressing, identical-text silent drop), `LICENSE` (MIT, pre-empts batterie-lint), and a CLAUDE.md "Plugin packaging" section.
- **Both hook shapes tested in sandbox HOMEs, not just written**: source shape silent-green with correct symlink; vendored shape (no pyproject, mimicking the assembler's lean copy-list) did a REAL git install into a temp HOME and the installed `sonner --list` worked from there.
- **Banc pass run and decisive.** Provenance-style isolated-HOME ardoise children, skill+shard seeded, stub-fenced `sonner`/`tmux` (zero real side effects, verified on both the CLI path and the native-tools path). **Fire 11/11** (F1×3 fable, F1×2 opus, F2×3, F3×3 — skill invoked FIRST every time, before any sonner attempt). **No-fire 0/20** (4 adjacent distractors × fable n=3 + opus n=2). Shard-load positive control passed: a child quoted the sandbox `rules/sonner.md` verbatim, so the zeros are about the true fleet default, not a half-installed sandbox. Full write-up + transcripts: `~/scratch/sonner-banc-2026-08-24/` (`results.md`); task prose deliberately kept out of this public repo per banc's privacy rule. son-jiliga tracks adopting the bench into banc proper.
- **A fresh-context refuting subagent reviewed both the packaging and the eval before anything was banked.** It found one genuine publish blocker — pyproject carried a static `version = "0.1.0"` while `/batterie:publish` lazy-stamps only plugin.json, so the FIRST publish would have failed batterie-lint's version-consistency check (a green that held only because 0.1.0==0.1.0 today). Fixed: version is now dynamic from plugin.json, bon's pattern; 18 tests green and reinstall verified after. It also caught three write-up errors in results.md (three max-turns rc=1 fire runs, not one; a lexical "sonner attempts" count presented as stub hits; a fence claim wider than its instrument) — all corrected in results.md with the corrections named as such. It sustained the eval measurement itself after independently re-parsing transcripts.

### The publish runbook (the legs this session was forbidden to run)

Run in ONE supervised sitting — step 2's ordering constraint is real:

1. `git -C ~/repos/spm1001/batterie pull --ff-only`.
2. **Registration commit in spm1001/batterie** (the one hand-edit that repo takes; never touch `plugins/`):
   - `assemble.sh`: add `sonner:sonner` to the PLUGINS map.
   - `.claude-plugin/marketplace.json`, plugins array entry:
     ```json
     {
       "name": "sonner",
       "source": "./plugins/sonner",
       "description": "Repo-addressed peer messaging — ring a repo and a Claude answers. CLI + peer-messaging skill.",
       "category": "integration",
       "homepage": "https://github.com/spm1001/sonner",
       "keywords": ["messaging", "peer", "cross-session", "doorbell"]
     }
     ```
   - Commit, push to main. **Then go straight to step 3 — do not leave this overnight.** A registered plugin with no vendored dir in HEAD, hit by a later no-bump daily assemble, takes the quarantine branch, whose `git checkout HEAD -- plugins/sonner` errors on a path absent from HEAD and kills the whole run under `set -euo pipefail` (refuting-review finding against `assemble.sh` ~lines 299–314). Registration + suite bump in the same cycle avoids the branch entirely.
3. From `~/repos/spm1001/sonner`: **`/batterie:publish`** — bumps the suite version in batterie-de-savoir, pushes both repos, dispatches assemble.yml, watches to green, pulls this machine current. The ratchet allows a brand-new plugin (no last-published version to compare).
4. **Read the CI before the verdict**: `gh run list --repo spm1001/batterie --workflow=assemble.yml --limit 1`. Then `claude plugin marketplace update batterie && claude plugin install sonner@batterie` on tube; NEXT session, verify `~/.claude/rules/sonner.md` symlinks into the plugin cache and `sonner --list` works. (The vendored hook's git-install path is already sandbox-proven; the clean-machine criterion needs this live pass.)
5. **Retire the user-skill copy in the same window** (son-rewota step 6): in `~/repos/spm1001/.claude`, `git rm -r skills/peer-messaging`, commit, push. Until then two identically-named skills sit in the picker — harmless, brief. Skill loading is session-cached: verify in a fresh session.
6. **Mac leg** (son-rewota step 7): from an INTERACTIVE session on the Mac — non-interactive ssh has a locked keychain, so don't attempt it that way — `claude plugin marketplace add spm1001/batterie` (or `update`), `claude plugin install sonner@batterie`. Next session the hook replaces the stale pre-grammar CLI from the public git URL (no credentials needed). Verify `sonner --list`. `--work` on the Mac remains untested — that's a watch item on son-rewota, not this runbook.
7. After the ship: son-pilalu (sonnette retirement sweep) unblocks — pointer only.

### Uncertain

- Whether the plugin-installed skill answers to bare `peer-messaging` or only `sonner:peer-messaging` in Skill invocations. The shard now tells the reader to use the name their listing shows, which sidesteps it; the clean-machine check will settle it.
- Crowded-context over-trigger (estate corpus + decoy skills co-resident) was not measured — the sterile-context 0/20 is necessary, not sufficient, for the fleet-wide default. Sameer's gate.

### Risks

- Eval artifacts live in `~/scratch/sonner-banc-2026-08-24/` — the ephemeral zone. The counts and method survive in this handoff and the board; the transcripts survive only until son-jiliga moves them into banc.
- The literal `(user)` suffix is baked into this skill's description line — matching five shipped trousse skills and bon:plan, so it was left for suite-wide consistency; under a plugin install it will cosmetically mislabel the skill in pickers. A one-line fix if the suite ever sweeps it.
- `--work` spawns via `bash -ic claudefv`, an estate-only shell function now shipping in a public CLI. Fails gracefully off-estate; reads as general in the docs. Pre-existing, out of this card's scope.

## For Claudes to come

**A version-consistency check that passes before the event it guards is not evidence — ask what the pipeline's first real run will do to the values.** sonner's pyproject and plugin.json both read 0.1.0, so every lint pass was green — and the first `/batterie:publish` would have stamped plugin.json to the suite number and gone red, on the exact run that mattered most. The general form: when two copies of a value are compared by a guard, and some machinery rewrites ONE of them at release time, the guard's pre-release greens are vacuous. Check what the stamping step touches, then make the other copy derive rather than duplicate. A fresh-context refuter caught this precisely because it read the stamping code instead of trusting the passing lint.
