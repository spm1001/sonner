"""Invocation-log adoption tests (erg-tebapi).

sonner vendors the estate invocation-log shim as src/sonner/_invlog.py —
canonical copy and the cross-estate conformance test live in
spm1001/harness-ergonomics (shim/invocation_log.py, tests/test_conformance.py).
These tests pin the adoption facts locally: every invocation appends exactly
one caller-stamped JSONL line — success and failure alike — and a broken log
path never breaks the CLI.

The sonner-specific fact under test: main() returns exit codes rather than
raising, and the shim derives outcome from exceptions — so the adoption
bridges returned codes through a private SystemExit subclass. The
"returned 2 logs as error" test below is the one that goes red if that
bridge is ever lost.
"""

import json
import os
import subprocess
import sys

import pytest

from sonner import cli


def _run(*argv, env):
    return subprocess.run(
        [sys.executable, "-m", "sonner.cli", *argv],
        capture_output=True, text=True, env=env,
        stdin=subprocess.DEVNULL,
    )


def _env(tmp_path, **overrides):
    """Env with a hermetic log dir and a deterministic model caller stamp."""
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg")
    env.update(overrides)
    return env


def _log_lines(tmp_path):
    log = tmp_path / "xdg" / "sonner" / "invocations.jsonl"
    assert log.exists(), f"no invocation log at {log}"
    return [json.loads(l) for l in log.read_text().splitlines() if l.strip()]


class TestInvocationLog:
    def test_ok_invocation_logs_one_line(self, tmp_path):
        env = _env(tmp_path, CLAUDECODE="1", CLAUDE_CODE_ENTRYPOINT="cli")
        result = _run("--list", env=env)
        assert result.returncode == 0, result.stderr
        (line,) = _log_lines(tmp_path)
        assert line["tool"] == "sonner"
        assert line["subcommand"] == "list"
        assert line["argv"] == ["--list"]
        assert line["parsed"]["list"] is True
        assert line["outcome"] == "ok" and line["exit_code"] == 0
        assert line["caller"] == "model" and line["caller_detail"] == "cli"
        assert line["duration_ms"] >= 0
        assert line["version"]  # whatever the CLI reports, non-empty

    def test_returned_error_code_logs_as_error(self, tmp_path):
        """main() RETURNS 2 for a bad repo dir — no exception ever raised.
        This is the false-green the return-int bridge exists to prevent."""
        env = _env(tmp_path, CLAUDECODE="1", CLAUDE_CODE_ENTRYPOINT="cli")
        result = _run("/nonexistent-repo-dir", "hello", env=env)
        assert result.returncode == 2
        (line,) = _log_lines(tmp_path)
        assert line["outcome"] == "error" and line["exit_code"] == 2
        assert line["subcommand"] == "ring"
        assert line["parsed"]["repo"] == "/nonexistent-repo-dir"

    def test_p_error_systemexit_logged(self, tmp_path):
        """Post-parse p.error (repo without message) exits 2 via SystemExit."""
        env = _env(tmp_path, CLAUDECODE="1")
        result = _run("some-repo", env=env)
        assert result.returncode == 2
        (line,) = _log_lines(tmp_path)
        assert line["outcome"] == "error" and line["exit_code"] == 2
        assert line["subcommand"] == "ring"
        assert line["parsed"] is not None  # parse succeeded; the check failed

    def test_misinvocation_dies_in_argparse_still_logged(self, tmp_path):
        """An invented flag never reaches post-parse — raw argv is the
        evidence."""
        env = _env(tmp_path, CLAUDECODE="1")
        result = _run("--definitely-not-a-flag", env=env)
        assert result.returncode == 2
        (line,) = _log_lines(tmp_path)
        assert line["outcome"] == "error" and line["exit_code"] == 2
        assert line["argv"] == ["--definitely-not-a-flag"]
        assert line["subcommand"] is None and line["parsed"] is None

    def test_robot_stamp_without_cc_env_or_tty(self, tmp_path):
        env = _env(tmp_path)  # no CC env; stdin/stdout/stderr are pipes
        result = _run("--list", env=env)
        assert result.returncode == 0
        (line,) = _log_lines(tmp_path)
        assert line["caller"] == "robot"
        assert line["caller_detail"]  # parent process name, non-empty

    def test_unwritable_log_path_never_breaks_cli(self, tmp_path):
        blocker = tmp_path / "xdg"
        blocker.write_text("occupied")  # a file where the data dir should be
        env = dict(os.environ, XDG_DATA_HOME=str(blocker), CLAUDECODE="1")
        result = _run("--list", env=env)
        assert result.returncode == 0, result.stderr
        assert "Traceback" not in result.stderr


class TestReturnContractPreserved:
    """The wrap must not change main()'s observable contract in-process."""

    def test_main_still_returns_int(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["sonner", "--list"])
        assert cli.main() == 0

    def test_p_error_still_raises_systemexit(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["sonner", "--wake"])  # --wake needs a repo
        with pytest.raises(SystemExit):
            cli.main()
