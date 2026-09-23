"""Safe external-process execution for the Inji API Test-Rig JARs.

This is the only place that calls subprocess in this project. It always
invokes an explicit executable with an explicit argument list — never a
shell string — so no caller-supplied value can inject additional shell
commands (see app/inji_executors.py for how arguments/environment are
built from typed configuration).
"""

import logging
import os
import re
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# How much of stdout/stderr to retain when a run fails before producing a
# parseable report (the only time we persist process output at all — a
# successful run's evidence comes from the parsed TestNG report instead).
_OUTPUT_EXCERPT_LIMIT = 4000

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?\S+"),
    re.compile(r"(?i)\b(password\w*\s*[:=]\s*)\S+"),
    re.compile(r"(?i)\b(secret\w*\s*[:=]\s*)\S+"),
    re.compile(r"(?i)\b(\w*token\w*\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(cookie\s*[:=]\s*)\S+"),
]


def sanitize_output(text: str) -> str:
    """Redacts common secret-shaped substrings before persisting process
    output. Best-effort, pattern-based — not a substitute for not logging
    secrets in the first place."""

    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + "[REDACTED]", text)
    return text


class ProcessStartError(Exception):
    """The process could not be started at all (bad executable, permission
    error, etc.) — never a shell/parsing ambiguity, since we never use a
    shell."""


@dataclass
class ProcessResult:
    exit_code: Optional[int]
    stdout: str
    stderr: str
    timed_out: bool


class ProcessRunner:
    """Runs one external process to completion (or until timeout),
    guaranteeing the child is not left running if we give up on it."""

    def run(
        self,
        executable: str,
        args: List[str],
        cwd: Path,
        env: Dict[str, str],
        timeout_seconds: float,
    ) -> ProcessResult:
        argv = [executable, *args]
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(cwd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,  # own process group, for clean kill
            )
        except (OSError, ValueError) as exc:
            raise ProcessStartError(str(exc)) from exc

        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            return ProcessResult(
                exit_code=process.returncode,
                stdout=sanitize_output(stdout or ""),
                stderr=sanitize_output(stderr or ""),
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            self._kill_process_group(process)
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                # The process is already killed; this just drains whatever
                # buffered output exists rather than blocking forever.
                stdout, stderr = "", ""
            return ProcessResult(
                exit_code=None,
                stdout=sanitize_output(stdout or ""),
                stderr=sanitize_output(stderr or ""),
                timed_out=True,
            )

    @staticmethod
    def _kill_process_group(process: "subprocess.Popen") -> None:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass  # already exited
        except OSError:
            logger.warning(
                "Could not kill process group for pid %s; falling back to "
                "killing the process directly.",
                process.pid,
            )
            process.kill()


def truncate_output(text: str, limit: int = _OUTPUT_EXCERPT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:] + "\n... (truncated)"
