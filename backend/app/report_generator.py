"""Pure M8 conformance-report projection and deterministic Markdown renderer."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.orchestration import BenchmarkEvaluation, Execution, ExecutionStatus
from app.result_normalizer import InjiTestCounts, OpenIDModuleResult
from app.schemas import TestRunConfig


REPORT_SCHEMA_VERSION = "1.0"


class ReportTestRun(BaseModel):
    test_run_id: str
    run_name: str
    environment: str


class ReportExecution(BaseModel):
    execution_id: str
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    total_planned_steps: int
    completed_steps: int


class ReportSummary(BaseModel):
    benchmark_status: str
    evidence_complete: bool
    planned_steps: int
    completed_steps: int
    passed_steps: int
    failed_steps: int
    pass_rate: float
    minimum_pass_rate: float


class ReportStepResult(BaseModel):
    step_id: str
    display_name: str
    component: str
    suite_id: Optional[str] = None
    provider: str
    status: ExecutionStatus
    duration_seconds: Optional[float] = None
    message: str
    error_type: Optional[str] = None
    normalization_error: Optional[str] = None
    provider_mismatch: Optional[str] = None
    openid_plan_id: Optional[str] = None
    openid_plan_name: Optional[str] = None
    openid_modules: Optional[List[OpenIDModuleResult]] = None
    inji_test_counts: Optional[InjiTestCounts] = None


class ReportBreakdown(BaseModel):
    key: str
    total_steps: int
    passed: int
    failed: int
    non_final: int


class ReportBreakdowns(BaseModel):
    component: List[ReportBreakdown] = Field(default_factory=list)
    suite: List[ReportBreakdown] = Field(default_factory=list)
    provider: List[ReportBreakdown] = Field(default_factory=list)


class ConformanceReport(BaseModel):
    schema_version: str
    test_run: ReportTestRun
    execution: ReportExecution
    summary: ReportSummary
    benchmark: BenchmarkEvaluation
    steps: List[ReportStepResult]
    breakdowns: ReportBreakdowns


def build_conformance_report(
    test_run: TestRunConfig, execution: Execution
) -> ConformanceReport:
    """Project persisted M6/M7 evidence into a report without recalculation.

    The only computed values are informational breakdown counts. Benchmark
    values are copied from the persisted M7 evaluation verbatim.
    """
    evaluation = execution.benchmark_evaluation
    if evaluation is None:
        raise ValueError("Execution has no persisted benchmark evaluation")

    steps = [
        ReportStepResult(
            step_id=result.step_id,
            display_name=result.display_name,
            component=result.component,
            suite_id=result.suite_id,
            provider=result.provider,
            status=result.status,
            duration_seconds=result.duration_seconds,
            message=result.message,
            error_type=result.error_type,
            normalization_error=result.normalization_error,
            provider_mismatch=result.provider_mismatch,
            openid_plan_id=result.openid_plan_id,
            openid_plan_name=result.openid_plan_name,
            openid_modules=result.openid_modules,
            inji_test_counts=result.inji_test_counts,
        )
        for result in execution.normalized_results
    ]

    return ConformanceReport(
        schema_version=REPORT_SCHEMA_VERSION,
        test_run=ReportTestRun(
            test_run_id=test_run.id,
            run_name=test_run.run_name,
            environment=test_run.environment.value,
        ),
        execution=ReportExecution(
            execution_id=execution.id,
            status=execution.status,
            started_at=execution.started_at,
            completed_at=execution.completed_at,
            total_planned_steps=execution.total_steps,
            completed_steps=execution.completed_steps,
        ),
        summary=ReportSummary(
            benchmark_status=evaluation.status.value,
            evidence_complete=evaluation.evidence_complete,
            planned_steps=evaluation.total_planned_steps,
            completed_steps=execution.completed_steps,
            passed_steps=evaluation.passed_steps,
            failed_steps=evaluation.failed_steps,
            pass_rate=evaluation.pass_rate,
            minimum_pass_rate=evaluation.minimum_pass_rate,
        ),
        benchmark=evaluation,
        steps=steps,
        breakdowns=ReportBreakdowns(
            component=_build_breakdown(steps, "component"),
            suite=_build_breakdown(steps, "suite_id"),
            provider=_build_breakdown(steps, "provider"),
        ),
    )


def render_markdown_report(report: ConformanceReport) -> str:
    """Render one ConformanceReport as stable, human-readable Markdown."""
    summary = report.summary
    benchmark = report.benchmark
    lines = [
        "# Conformance Report",
        "",
        "## Summary",
        "",
        f"- Schema version: `{report.schema_version}`",
        f"- Test run: `{report.test_run.run_name}` (`{report.test_run.test_run_id}`)",
        f"- Environment: `{report.test_run.environment}`",
        f"- Execution: `{report.execution.execution_id}` (`{report.execution.status.value}`)",
        f"- Started: {_format_datetime(report.execution.started_at)}",
        f"- Completed: {_format_datetime(report.execution.completed_at)}",
        f"- Benchmark status: `{summary.benchmark_status}`",
        f"- Evidence complete: `{str(summary.evidence_complete).lower()}`",
        f"- Steps: {summary.passed_steps} passed, {summary.failed_steps} failed, "
        f"{summary.completed_steps}/{summary.planned_steps} completed",
        f"- Pass rate: {summary.pass_rate:g}% (minimum {summary.minimum_pass_rate:g}%)",
        "",
        "## Benchmark Gate",
        "",
        "| Status | Evidence complete | Planned | Normalized | Passed | Failed | Pass rate | Minimum | Critical failures allowed |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        "| " + " | ".join(
            [
                benchmark.status.value,
                str(benchmark.evidence_complete).lower(),
                str(benchmark.total_planned_steps),
                str(benchmark.normalized_result_count),
                str(benchmark.passed_steps),
                str(benchmark.failed_steps),
                f"{benchmark.pass_rate:g}%",
                f"{benchmark.minimum_pass_rate:g}%",
                str(benchmark.critical_failures_allowed),
            ]
        ) + " |",
        "",
        "## Step Results",
        "",
        "| Step | Component | Suite | Provider | Status | Duration | Message | Error | Normalization | Provider mismatch |",
        "| --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for step in report.steps:
        lines.append(
            "| " + " | ".join(
                [
                    _cell(step.step_id),
                    _cell(step.component),
                    _cell(step.suite_id),
                    _cell(step.provider),
                    _cell(step.status.value),
                    _cell(step.duration_seconds),
                    _cell(step.message),
                    _cell(step.error_type),
                    _cell(step.normalization_error),
                    _cell(step.provider_mismatch),
                ]
            ) + " |"
        )
    if not report.steps:
        lines.append("| — | — | — | — | — | — | No normalized step results | — | — | — |")

    # Provider detail lives outside the table: list items between table rows
    # would terminate the table and break rendering of every later row.
    detail_lines: List[str] = []
    for step in report.steps:
        if step.openid_plan_id or step.openid_plan_name or step.openid_modules:
            detail_lines.append(
                f"- `{_cell(step.step_id)}` OpenID: plan `{_cell(step.openid_plan_name)}` "
                f"(`{_cell(step.openid_plan_id)}`), modules: "
                f"{len(step.openid_modules or [])}"
            )
        if step.inji_test_counts is not None:
            counts = step.inji_test_counts
            detail_lines.append(
                f"- `{_cell(step.step_id)}` Inji TestNG: {counts.passed}/{counts.total} "
                f"passed, {counts.failed} failed, {counts.skipped} skipped"
            )
    if detail_lines:
        lines.extend(["", "## Step Details", ""])
        lines.extend(detail_lines)

    lines.extend(_render_breakdown("Component Breakdown", report.breakdowns.component))
    lines.extend(_render_breakdown("Suite Breakdown", report.breakdowns.suite))
    lines.extend(_render_breakdown("Provider Breakdown", report.breakdowns.provider))
    lines.extend(["", "## Violations", ""])
    if not benchmark.violations:
        lines.append("None.")
    else:
        lines.extend(
            [
                "| Code | Message | Expected | Actual | Steps |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for violation in benchmark.violations:
            lines.append(
                "| " + " | ".join(
                    [
                        _cell(violation.code),
                        _cell(violation.message),
                        _cell(violation.expected),
                        _cell(violation.actual),
                        _cell(", ".join(violation.step_ids or [])),
                    ]
                ) + " |"
            )
    return "\n".join(lines) + "\n"


def _build_breakdown(
    steps: List[ReportStepResult], key_name: str
) -> List[ReportBreakdown]:
    grouped: dict[str, List[ReportStepResult]] = {}
    for step in steps:
        value = getattr(step, key_name)
        key = value if value is not None else "(none)"
        grouped.setdefault(key, []).append(step)

    return [
        ReportBreakdown(
            key=key,
            total_steps=len(group),
            passed=sum(step.status == ExecutionStatus.PASSED for step in group),
            failed=sum(step.status == ExecutionStatus.FAILED for step in group),
            non_final=sum(
                step.status not in {ExecutionStatus.PASSED, ExecutionStatus.FAILED}
                for step in group
            ),
        )
        for key, group in sorted(grouped.items())
    ]


def _render_breakdown(title: str, breakdowns: List[ReportBreakdown]) -> List[str]:
    lines = ["", f"## {title}", "", "| Key | Total | Passed | Failed | Non-final |", "| --- | ---: | ---: | ---: | ---: |"]
    if breakdowns:
        lines.extend(
            f"| {_cell(item.key)} | {item.total_steps} | {item.passed} | {item.failed} | {item.non_final} |"
            for item in breakdowns
        )
    else:
        lines.append("| — | 0 | 0 | 0 | 0 |")
    return lines


def _format_datetime(value: Optional[datetime]) -> str:
    return value.isoformat() if value is not None else "—"


def _cell(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value).replace("|", "\\|").replace("\n", " ")
