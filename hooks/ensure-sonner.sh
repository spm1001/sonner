#!/bin/bash
# SessionStart hook: ensure the sonner CLI is on PATH and the always-on rules
# shard is linked. Install-if-MISSING only — no version-drift check here: the
# vendored plugin.json carries the stamped SUITE version, not sonner's own, so
# any version comparison at session start is structurally false (bds-japoca,
# inherited from bon's hook). Freshness is /batterie:update's job.
# Silent when all is well.

export PATH="$HOME/.local/bin:$PATH"
FIXED=""
ISSUES=""

# Capture auto-install output so failures are diagnosable, not silent.
UPDATE_LOG="$HOME/.cache/sonner/auto-update.log"
mkdir -p "$(dirname "$UPDATE_LOG")" 2>/dev/null

# --- Instruction shard ---
# Symlink into ~/.claude/rules/ so the always-on shard loads every session.
# Idempotent — ln -sf overwrites stale symlinks from old plugin versions.
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(dirname "$HOOK_DIR")"
if [ -f "$PLUGIN_ROOT/instructions.md" ]; then
    mkdir -p "$HOME/.claude/rules"
    ln -sf "$PLUGIN_ROOT/instructions.md" "$HOME/.claude/rules/sonner.md"
fi

# Resolve install source. A source checkout carries pyproject.toml; the
# vendored marketplace plugin does not (skill-plugin copy list ships no
# Python), so fall back to git — spm1001/sonner is public and stdlib-only,
# so this works on a clean machine with nothing but uv.
if [ -n "$PLUGIN_ROOT" ] && [ -f "$PLUGIN_ROOT/pyproject.toml" ]; then
    INSTALL_SRC="$PLUGIN_ROOT"
else
    INSTALL_SRC="git+https://github.com/spm1001/sonner"
fi

# CLI missing → auto-install. No version claim in the report — sonner has no
# --version flag, and claiming a number nobody read is the bds-zelowe bug.
if ! command -v sonner &>/dev/null; then
    if uv tool install "$INSTALL_SRC" --force --reinstall --no-cache >"$UPDATE_LOG" 2>&1; then
        FIXED="${FIXED}• sonner CLI installed\n"
    else
        ISSUES="${ISSUES}• sonner CLI not found and auto-install failed (full error: ${UPDATE_LOG}). Run manually:\n\n  uv tool install \"$INSTALL_SRC\" --force --reinstall --no-cache\n"
    fi
fi

# Silent exit if nothing happened
[ -z "$FIXED" ] && [ -z "$ISSUES" ] && exit 0

# Report
MSG=""
[ -n "$FIXED" ] && MSG="${MSG}✓ sonner auto-fixed:\n\n${FIXED}"
[ -n "$ISSUES" ] && MSG="${MSG}⚠️ sonner needs attention:\n\n${ISSUES}"

python3 -c "import json; print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': '''${MSG}'''}}))"
