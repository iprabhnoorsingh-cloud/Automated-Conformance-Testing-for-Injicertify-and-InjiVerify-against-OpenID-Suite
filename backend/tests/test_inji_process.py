"""Tests for ProcessRunner — the only place this project calls subprocess.

These use the real Python interpreter (`sys.executable -c "..."`) as a
throwaway "external process" to exercise real OS-level subprocess
mechanics (real exit codes, real timeout+kill, real stdout/stderr capture)
without needing Java or any Inji artifact.
"""

import os
import sys
import time

import pytest

from app.inji_process import ProcessRunner, ProcessStartError, sanitize_output, truncate_output


@pytest.fixture
def runner():
    return ProcessRunner()


def test_successful_launch_captures_stdout(runner, tmp_path):
    result = runner.run(
        executable=sys.executable,
        args=["-c", "print('hello from child')"],
        cwd=tmp_path,
        env={**os.environ},
        timeout_seconds=10,
    )
    assert result.exit_code == 0
    assert "hello from child" in result.stdout
    assert result.timed_out is False


def test_nonzero_exit_code_is_captured(runner, tmp_path):
    result = runner.run(
        executable=sys.executable,
        args=["-c", "import sys; sys.exit(7)"],
        cwd=tmp_path,
        env={**os.environ},
        timeout_seconds=10,
    )
    assert result.exit_code == 7
    assert result.timed_out is False


def test_stderr_is_captured_separately(runner, tmp_path):
    result = runner.run(
        executable=sys.executable,
        args=["-c", "import sys; sys.stderr.write('oops')"],
        cwd=tmp_path,
        env={**os.environ},
        timeout_seconds=10,
    )
    assert "oops" in result.stderr


def test_environment_is_passed_through(runner, tmp_path):
    result = runner.run(
        executable=sys.executable,
        args=["-c", "import os; print(os.environ.get('MY_CUSTOM_VAR'))"],
        cwd=tmp_path,
        env={**os.environ, "MY_CUSTOM_VAR": "custom-value-123"},
        timeout_seconds=10,
    )
    assert "custom-value-123" in result.stdout


def test_working_directory_is_respected(runner, tmp_path):
    result = runner.run(
        executable=sys.executable,
        args=["-c", "import os; print(os.getcwd())"],
        cwd=tmp_path,
        env={**os.environ},
        timeout_seconds=10,
    )
    assert result.stdout.strip() == str(tmp_path.resolve()) or result.stdout.strip() == str(tmp_path)


def test_timeout_terminates_process_and_reports_timed_out(runner, tmp_path):
    started = time.monotonic()
    result = runner.run(
        executable=sys.executable,
        args=["-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        env={**os.environ},
        timeout_seconds=0.5,
    )
    elapsed = time.monotonic() - started

    assert result.timed_out is True
    assert result.exit_code is None
    # Should return promptly after the configured timeout, not wait for the
    # full 30s sleep — proves the process was actually killed, not just
    # abandoned.
    assert elapsed < 10


def test_process_start_failure_raises_clean_error(runner, tmp_path):
    with pytest.raises(ProcessStartError):
        runner.run(
            executable="/definitely/not/a/real/executable/path",
            args=[],
            cwd=tmp_path,
            env={**os.environ},
            timeout_seconds=5,
        )


def test_no_shell_metacharacter_injection(runner, tmp_path):
    # A value containing shell metacharacters must be passed through as a
    # single literal argument, never interpreted by a shell (there is no
    # shell involved at all).
    dangerous = "; touch /tmp/should-not-exist-from-test; echo"
    result = runner.run(
        executable=sys.executable,
        args=["-c", "import sys; print(sys.argv[1])", dangerous],
        cwd=tmp_path,
        env={**os.environ},
        timeout_seconds=10,
    )
    assert result.stdout.strip() == dangerous
    assert not os.path.exists("/tmp/should-not-exist-from-test")


def test_sanitize_output_redacts_bearer_token():
    text = "calling API with Authorization: Bearer abcdef123456"
    sanitized = sanitize_output(text)
    assert "abcdef123456" not in sanitized
    assert "[REDACTED]" in sanitized


def test_sanitize_output_redacts_password_field():
    text = "config password=supersecret123 loaded"
    sanitized = sanitize_output(text)
    assert "supersecret123" not in sanitized


def test_truncate_output_caps_length():
    long_text = "x" * 10000
    truncated = truncate_output(long_text, limit=100)
    assert len(truncated) < 200
    assert truncated.endswith("truncated)")


def test_truncate_output_leaves_short_text_untouched():
    short_text = "short output"
    assert truncate_output(short_text, limit=100) == short_text
