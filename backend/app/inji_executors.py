"""Inji API Test-Rig executors.

Implements the M3 TestStepExecutor protocol by running the actual
inji-certify/inji-verify `api-test` Java module as an external process
(`java -jar ... apitest-<module>-<version>-jar-with-dependencies.jar`) and
normalizing its generated TestNG report into a StepResult. This is not an
invented REST integration — see docs/architecture.md §6 for the exact
upstream contract (JVM args, environment-variable property overrides,
report location) this was built against, and the actual `entrypoint.sh` /
`InjiTestRunner.java` / `ConfigManager.java` sources it was verified from.

Class hierarchy: `InjiApiTestRigExecutor` holds everything that's identical
between Certify and Verify (process invocation, timeout/cleanup, report
discovery/parsing, StepResult normalization). `CertifyApiTestRigExecutor`
and `VerifyApiTestRigExecutor` supply only what actually differs: which
suite_config key to read, the `modules` JVM property value, and how their
typed config maps to MOSIP property environment-variable overrides.

Critical, source-verified fact: `InjiTestRunner.main()` calls
`System.exit(0)` unconditionally at the end, regardless of whether TestNG
reported failures. The process exit code therefore NEVER determines
pass/fail here — only the parsed testng-results.xml does. Exit code is
still recorded as supplementary evidence.
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.executors import ExecutionContext
from app.inji_process import ProcessResult, ProcessRunner, ProcessStartError, truncate_output
from app.inji_report import (
    MalformedReportError,
    ReportNotFoundError,
    TestRigResultParser,
    locate_report,
)
from app.orchestration import ExecutionStatus, Step, StepResult

logger = logging.getLogger(__name__)


class InjiConfigurationError(Exception):
    """Raised when a suite's typed config is present but incomplete for
    building the process invocation (distinct from `missing_configuration`,
    which means the whole config block was absent)."""


@dataclass
class InjiTestRigSettings:
    """Deployment-level configuration for one provider's test rig — where
    its JAR/working directory live, which java binary to use, and how long
    to allow it to run. Never contains per-test-run data; that comes from
    the suite's typed config (InjiCertifyTestRigConfig/InjiVerifyTestRigConfig).
    """

    jar_path: Optional[str]
    working_directory: Optional[str]
    java_executable: str
    timeout_seconds: float


# (jar_path, working_directory) on success; (None, None) with a message and
# error_type on failure. A plain tuple keeps this internal to the class
# without needing a StepResult (no `step`/timestamps available yet) or an
# extra sentinel type.
_DeploymentResolution = Tuple[Optional[Path], Optional[Path], Optional[str], Optional[str]]


class InjiApiTestRigExecutor:
    provider_name: str = ""  # set by subclass, e.g. "injicertify"
    modules_value: str = ""  # set by subclass, e.g. "injicertify"

    def __init__(self, settings: InjiTestRigSettings, process_runner: Optional[ProcessRunner] = None):
        self._settings = settings
        self._process_runner = process_runner or ProcessRunner()

    def execute(self, step: Step, context: ExecutionContext) -> StepResult:
        started_at = datetime.now(timezone.utc)
        suite_config = step.suite_config or {}
        config = self._extract_config(suite_config)

        if config is None:
            return self._result(
                step,
                started_at,
                ExecutionStatus.FAILED,
                (
                    f"Step '{step.display_name}' has provider "
                    f"'{self.provider_name}' but no matching test-rig "
                    "configuration was supplied on the test suite."
                ),
                {"provider": self.provider_name, "error_type": "missing_configuration"},
            )

        jar_path, working_directory, error_message, error_type = self._resolve_deployment()
        if error_message is not None:
            return self._result(
                step,
                started_at,
                ExecutionStatus.FAILED,
                error_message,
                {"provider": self.provider_name, "error_type": error_type},
            )

        try:
            args = self._build_jvm_args(config, jar_path)
            env_overrides = self._build_environment(config)
        except InjiConfigurationError as exc:
            return self._result(
                step,
                started_at,
                ExecutionStatus.FAILED,
                str(exc),
                {"provider": self.provider_name, "error_type": "invalid_configuration"},
            )

        details: Dict[str, Any] = {
            "provider": self.provider_name,
            "test_rig": f"{self.provider_name}-api-test-rig",
            "test_level": config.get("test_level"),
        }

        process_env = {**os.environ, **env_overrides}
        try:
            process_result = self._process_runner.run(
                executable=self._settings.java_executable,
                args=args,
                cwd=working_directory,
                env=process_env,
                timeout_seconds=self._settings.timeout_seconds,
            )
        except ProcessStartError as exc:
            return self._result(
                step,
                started_at,
                ExecutionStatus.FAILED,
                f"Could not start the {self.provider_name} test rig process: {exc}",
                {**details, "error_type": "process_start_failed"},
            )

        details["process_exit_code"] = process_result.exit_code
        details["timed_out"] = process_result.timed_out

        if process_result.timed_out:
            return self._result(
                step,
                started_at,
                ExecutionStatus.FAILED,
                (
                    f"{self.provider_name} test rig did not finish within "
                    f"{self._settings.timeout_seconds:.0f}s and was terminated."
                ),
                {
                    **details,
                    "error_type": "timeout",
                    "process_output_excerpt": truncate_output(
                        process_result.stdout + "\n" + process_result.stderr
                    ),
                },
            )

        return self._interpret_report(step, started_at, working_directory, process_result, details)

    def _interpret_report(
        self,
        step: Step,
        started_at: datetime,
        working_directory: Path,
        process_result: ProcessResult,
        details: Dict[str, Any],
    ) -> StepResult:
        report_path = locate_report(working_directory)
        if report_path is None:
            return self._result(
                step,
                started_at,
                ExecutionStatus.FAILED,
                (
                    f"{self.provider_name} test rig process exited "
                    f"(code {process_result.exit_code}) but produced no "
                    "testng-report/testng-results.xml — its own exit code "
                    "is not a reliable pass/fail signal for this test rig."
                ),
                {
                    **details,
                    "error_type": "report_not_found",
                    "process_output_excerpt": truncate_output(
                        process_result.stdout + "\n" + process_result.stderr
                    ),
                },
            )

        try:
            report = TestRigResultParser().parse(report_path)
        except (ReportNotFoundError, MalformedReportError) as exc:
            return self._result(
                step,
                started_at,
                ExecutionStatus.FAILED,
                f"Could not parse {self.provider_name} test rig report: {exc}",
                {**details, "error_type": "malformed_report", "report_path": str(report_path)},
            )

        details.update(
            {
                "tests_total": report.tests_total,
                "tests_passed": report.tests_passed,
                "tests_failed": report.tests_failed,
                "tests_skipped": report.tests_skipped,
                "report_path": report.report_path,
                "report_file": "testng-results.xml",
                "failure_summary": report.failure_summary,
            }
        )

        status = ExecutionStatus.PASSED if report.all_passed else ExecutionStatus.FAILED
        message = (
            f"{self.provider_name} test rig: {report.tests_passed}/{report.tests_total} "
            f"passed, {report.tests_failed} failed, {report.tests_skipped} skipped."
        )
        return self._result(step, started_at, status, message, details)

    def _resolve_deployment(self) -> _DeploymentResolution:
        if not self._settings.jar_path or not self._settings.working_directory:
            return (
                None,
                None,
                f"{self.provider_name} test rig is not configured on this "
                "deployment (missing JAR path / working directory).",
                "test_rig_not_configured",
            )

        working_directory = Path(self._settings.working_directory)
        if not working_directory.is_dir():
            return (
                None,
                None,
                f"Configured working directory does not exist: {working_directory}",
                "invalid_working_directory",
            )

        jar_path = self._resolve_jar_path(working_directory)
        if jar_path is None:
            return (
                None,
                None,
                "Configured JAR path/pattern did not resolve to exactly one "
                f"file: {self._settings.jar_path}",
                "jar_not_found",
            )

        return jar_path, working_directory, None, None

    def _resolve_jar_path(self, working_directory: Path) -> Optional[Path]:
        configured = self._settings.jar_path
        if "*" not in configured:
            candidate = Path(configured)
            if not candidate.is_absolute():
                candidate = working_directory / candidate
            return candidate if candidate.is_file() else None

        # Mirrors the actual upstream entrypoint.sh, which also globs for
        # the versioned jar name (e.g. apitest-injicertify-*-jar-with-dependencies.jar)
        # rather than hard-coding a version.
        base = Path(configured)
        if base.is_absolute():
            matches = sorted(base.parent.glob(base.name))
        else:
            matches = sorted(working_directory.glob(configured))
        return matches[0] if len(matches) == 1 else None

    def _build_jvm_args(self, config: Dict[str, Any], jar_path: Path) -> List[str]:
        test_level = config.get("test_level", "smoke")
        env_user = config.get("env_user", "")
        env_endpoint = config.get("env_endpoint", "")
        if not env_user or not env_endpoint:
            raise InjiConfigurationError(
                f"{self.provider_name} configuration is missing env_user/env_endpoint."
            )
        # Mirrors the actual entrypoint.sh invocation order verbatim:
        # `java -jar -Dmodules=... -Denv.user=... -Denv.endpoint=... -Denv.testLevel=... <jar>`
        return [
            "-jar",
            f"-Dmodules={self.modules_value}",
            f"-Denv.user={env_user}",
            f"-Denv.endpoint={env_endpoint}",
            f"-Denv.testLevel={test_level}",
            str(jar_path),
        ]

    def _extract_config(self, suite_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def _build_environment(self, config: Dict[str, Any]) -> Dict[str, str]:
        raise NotImplementedError

    @staticmethod
    def _result(
        step: Step,
        started_at: datetime,
        status: ExecutionStatus,
        message: str,
        details: Dict[str, Any],
    ) -> StepResult:
        return StepResult(
            step_id=step.step_id,
            status=status,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            message=message,
            details=details,
        )


class CertifyApiTestRigExecutor(InjiApiTestRigExecutor):
    provider_name = "injicertify"
    modules_value = "injicertify"

    def _extract_config(self, suite_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return suite_config.get("injicertify_config")

    def _build_environment(self, config: Dict[str, Any]) -> Dict[str, str]:
        # ConfigManager.getValueForKeyAddToPropertiesMap() (apitest-commons)
        # checks System.getenv(<exact property name>) before falling back to
        # its bundled properties file — these are OS environment variables
        # the java process reads, not JVM -D flags.
        env: Dict[str, str] = {}
        mapping = {
            "esignet_base_url": "eSignetbaseurl",
            "inji_certify_base_url": "injiCertifyBaseURL",
            "mosip_components_base_urls": "mosip_components_base_urls",
            "use_case_to_execute": "useCaseToExecute",
            "esignet_actuator_property_section": "esignetActuatorPropertySection",
            "sunbird_base_url": "sunBirdBaseURL",
        }
        for field_name, env_name in mapping.items():
            value = config.get(field_name)
            if value:
                env[env_name] = str(value)
        if config.get("use_pre_configured_otp") is not None:
            env["usePreConfiguredOtp"] = "true" if config["use_pre_configured_otp"] else "false"
        return env


class VerifyApiTestRigExecutor(InjiApiTestRigExecutor):
    provider_name = "injiverify"
    modules_value = "injiverify"

    def _extract_config(self, suite_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return suite_config.get("injiverify_config")

    def _build_environment(self, config: Dict[str, Any]) -> Dict[str, str]:
        base_url = config.get("inji_verify_base_url")
        if not base_url:
            raise InjiConfigurationError(
                "injiverify configuration is missing inji_verify_base_url."
            )
        return {"injiVerifyBaseUrl": str(base_url)}
