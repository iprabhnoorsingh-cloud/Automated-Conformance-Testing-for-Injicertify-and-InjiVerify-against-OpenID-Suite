"""Parser for the Inji API Test-Rigs' generated TestNG report.

Both inji-certify's and inji-verify's `InjiTestRunner.main()` call
`runner.setOutputDirectory("testng-report")` on a plain `org.testng.TestNG`
instance with default listeners enabled — so `testng-report/testng-results.xml`
is TestNG's own standard XML reporter output, not a MOSIP-specific format.
That schema (`<testng-results total="" passed="" failed="" skipped="">`,
with nested `<suite>/<test>/<class>/<test-method status="PASS|FAIL|SKIP">`)
is public and stable, so this parses it with stdlib `xml.etree.ElementTree`
— no XML/HTML parsing library is needed.

This module never fabricates a result: a missing or malformed report is a
distinct, explicit failure mode, never silently treated as a pass.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Cap on how many failing test names get preserved in a StepResult —
# enough to be useful evidence without unbounded growth.
_MAX_FAILURE_SUMMARY = 20


class ReportNotFoundError(Exception):
    """No testng-results.xml could be located under the working directory."""


class MalformedReportError(Exception):
    """testng-results.xml exists but isn't a parseable/expected TestNG
    report (invalid XML, or missing the root count attributes)."""


@dataclass
class TestRigResult:
    """Normalized, provider-independent outcome of one Inji API Test-Rig
    run, derived only from what the report actually contains."""

    tests_total: int
    tests_passed: int
    tests_failed: int
    tests_skipped: int
    failure_summary: List[str] = field(default_factory=list)
    report_path: Optional[str] = None

    @property
    def all_passed(self) -> bool:
        """PASSED requires at least one real pass and zero failures — an
        all-skipped or zero-test report is never treated as a pass."""
        return self.tests_failed == 0 and self.tests_passed > 0


def locate_report(working_directory: Path) -> Optional[Path]:
    """Finds testng-report/testng-results.xml under `working_directory`.

    Bounded to that directory's own subtree (never escapes upward or
    follows an absolute path from configuration) — the test rig's actual
    output directory nesting (e.g. directly under the working directory vs.
    under a `target/` build folder within it) isn't fully pinned down by
    the source, so a shallow bounded search is used instead of assuming
    one fixed layout.
    """
    direct = working_directory / "testng-report" / "testng-results.xml"
    if direct.is_file():
        return direct

    for candidate in sorted(working_directory.glob("**/testng-report/testng-results.xml")):
        return candidate
    return None


class TestRigResultParser:
    def parse(self, report_path: Path) -> TestRigResult:
        if not report_path.is_file():
            raise ReportNotFoundError(f"Report not found: {report_path}")

        try:
            root = ET.parse(str(report_path)).getroot()
        except ET.ParseError as exc:
            raise MalformedReportError(
                f"Could not parse report as XML: {report_path} ({exc})"
            ) from exc

        if root.tag != "testng-results":
            raise MalformedReportError(
                f"Unexpected root element '{root.tag}' in {report_path}, "
                "expected 'testng-results'."
            )

        try:
            total = int(root.get("total", ""))
            passed = int(root.get("passed", ""))
            failed = int(root.get("failed", ""))
            skipped = int(root.get("skipped", ""))
        except ValueError as exc:
            raise MalformedReportError(
                f"testng-results element in {report_path} is missing or has "
                f"non-numeric total/passed/failed/skipped attributes: {exc}"
            ) from exc

        failure_summary = self._extract_failure_summary(root)

        return TestRigResult(
            tests_total=total,
            tests_passed=passed,
            tests_failed=failed,
            tests_skipped=skipped,
            failure_summary=failure_summary,
            report_path=str(report_path),
        )

    @staticmethod
    def _extract_failure_summary(root: ET.Element) -> List[str]:
        # ElementTree elements don't carry parent pointers, and
        # Element.find("..") does not work reliably across Python/ElementTree
        # versions for this — build an explicit parent map instead.
        parent_of = {child: parent for parent in root.iter() for child in parent}

        names: List[str] = []
        for method in root.iter("test-method"):
            if method.get("status") != "FAIL":
                continue
            class_name = ""
            parent_class = parent_of.get(method)
            if parent_class is not None and parent_class.tag == "class":
                class_name = parent_class.get("name", "")
            method_name = method.get("name", "unknown")
            names.append(f"{class_name}.{method_name}" if class_name else method_name)
            if len(names) >= _MAX_FAILURE_SUMMARY:
                break
        return names
