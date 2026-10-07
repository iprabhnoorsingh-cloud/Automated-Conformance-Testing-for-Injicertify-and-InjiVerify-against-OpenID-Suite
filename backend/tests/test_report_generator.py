"""Tests for M8's pure conformance-report projection and Markdown renderer."""

from datetime import datetime, timezone

from app.json_execution_repository import JsonFileExecutionRepository
from app.orchestration import (
    BenchmarkEvaluation,
    BenchmarkStatus,
    BenchmarkViolation,
    Execution,
    ExecutionStatus,
    Step,
    StepResult,
)
from app.report_generator import build_conformance_report, render_markdown_report
from app.result_normalizer import InjiTestCounts, NormalizedStepResult, OpenIDModuleResult
from app.schemas import (
    BenchmarkConfig,
    Environment,
    TestRunConfig,
    TestRunStatus,
    TestSuiteConfig,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _run():
    return TestRunConfig(
        id="run-1",
        run_name="M8 report run",
        environment=Environment.STAGING,
        components=["inji-certify"],
        test_suites=[TestSuiteConfig(provider="mock", suite_id="suite", display_name="Suite")],
        benchmark=BenchmarkConfig(minimum_pass_rate=80, critical_failures_allowed=1),
        status=TestRunStatus.PASSED,
        created_at=NOW,
    )


def _normalized(index, provider, status=ExecutionStatus.PASSED):
    step_id = f"inji-certify:{provider}:suite-{index}"
    raw = StepResult(
        step_id=step_id,
        status=status,
        started_at=NOW,
        completed_at=NOW,
        message="raw result should not be reported",
        details={"secret": "not included"},
    )
    values = {}
    if provider == "openid":
        values = {
            "openid_plan_id": "plan-1",
            "openid_plan_name": "OIDC Plan",
            "openid_modules": [
                OpenIDModuleResult(
                    module_id="module-1",
                    module_name="OIDC Module",
                    external_state="FINISHED",
                    result="PASSED",
                )
            ],
        }
    if provider in {"injicertify", "injiverify"}:
        values = {
            "inji_test_counts": InjiTestCounts(
                total=2, passed=2 if status == ExecutionStatus.PASSED else 1,
                failed=0 if status == ExecutionStatus.PASSED else 1,
                skipped=0,
            )
        }
    return NormalizedStepResult(
        step_id=step_id,
        display_name=f"{provider} suite",
        provider=provider,
        component="inji-certify",
        suite_id=f"suite-{index}",
        status=status,
        started_at=NOW,
        completed_at=NOW,
        duration_seconds=1.25,
        message=f"{provider} normalized result",
        raw_result=raw,
        source_details={"secret": "not included"},
        **values,
    )


def _execution(results, evaluation=None):
    steps = [
        Step(
            step_id=result.step_id,
            display_name=result.display_name,
            provider=result.provider,
            component=result.component,
            order=index,
        )
        for index, result in enumerate(results)
    ]
    return Execution(
        id="execution-1",
        test_run_id="run-1",
        status=ExecutionStatus.PASSED,
        started_at=NOW,
        completed_at=NOW,
        total_steps=len(steps),
        completed_steps=len(results),
        steps=steps,
        step_results=[result.raw_result for result in results],
        normalized_results=results,
        benchmark_evaluation=evaluation
        or BenchmarkEvaluation(
            status=BenchmarkStatus.PASSED,
            evidence_complete=True,
            total_planned_steps=len(steps),
            normalized_result_count=len(results),
            passed_steps=sum(result.status == ExecutionStatus.PASSED for result in results),
            failed_steps=sum(result.status == ExecutionStatus.FAILED for result in results),
            pass_rate=100,
            minimum_pass_rate=80,
            critical_failures_allowed=1,
        ),
    )


def test_complete_report_projects_all_four_providers_without_raw_evidence():
    results = [_normalized(i, provider) for i, provider in enumerate(
        ["mock", "openid", "injicertify", "injiverify"]
    )]

    report = build_conformance_report(_run(), _execution(results))

    assert report.schema_version == "1.0"
    assert [step.provider for step in report.steps] == [
        "mock", "openid", "injicertify", "injiverify"
    ]
    assert report.steps[1].openid_plan_id == "plan-1"
    assert report.steps[2].inji_test_counts.total == 2
    assert report.summary.pass_rate == 100
    assert "raw_result" not in report.model_dump_json()
    assert "source_details" not in report.model_dump_json()
    assert "not included" not in report.model_dump_json()


def test_failed_benchmark_and_violations_are_projected_not_recalculated():
    result = _normalized(0, "mock", ExecutionStatus.FAILED)
    evaluation = BenchmarkEvaluation(
        status=BenchmarkStatus.FAILED,
        evidence_complete=False,
        total_planned_steps=3,
        normalized_result_count=1,
        passed_steps=0,
        failed_steps=1,
        pass_rate=0,
        minimum_pass_rate=90,
        critical_failures_allowed=0,
        violations=[
            BenchmarkViolation(
                code="incomplete_normalized_evidence",
                message="Persisted M7 evidence is incomplete.",
            )
        ],
    )

    report = build_conformance_report(_run(), _execution([result], evaluation))

    assert report.benchmark == evaluation
    assert report.summary.benchmark_status == "FAILED"
    assert report.summary.evidence_complete is False
    assert report.summary.pass_rate == 0
    assert report.benchmark.violations[0].code == "incomplete_normalized_evidence"


def test_json_and_markdown_are_deterministic_with_sorted_breakdowns():
    results = [_normalized(0, "openid"), _normalized(1, "mock")]
    report_one = build_conformance_report(_run(), _execution(results))
    report_two = build_conformance_report(_run(), _execution(results))

    assert report_one.model_dump_json() == report_two.model_dump_json()
    assert render_markdown_report(report_one) == render_markdown_report(report_two)
    assert [item.key for item in report_one.breakdowns.provider] == ["mock", "openid"]
    markdown = render_markdown_report(report_one)
    assert "# Conformance Report" in markdown
    assert "## Benchmark Gate" in markdown
    assert "## Step Results" in markdown
    assert "## Component Breakdown" in markdown
    assert "## Suite Breakdown" in markdown
    assert "## Provider Breakdown" in markdown
    assert "## Violations" in markdown


def test_repository_loaded_execution_generates_identical_report(tmp_path):
    execution = _execution([_normalized(0, "injicertify")])
    repository = JsonFileExecutionRepository(tmp_path / "executions.json")
    repository.create(execution)
    loaded = repository.get(execution.id)

    assert loaded is not None
    assert build_conformance_report(_run(), loaded) == build_conformance_report(_run(), execution)


def test_markdown_step_table_is_not_interrupted_by_provider_details():
    results = [_normalized(i, provider) for i, provider in enumerate(
        ["openid", "injicertify", "mock"]
    )]
    markdown = render_markdown_report(build_conformance_report(_run(), _execution(results)))
    section = markdown.split("## Step Results\n\n")[1].split("\n\n")[0]

    assert all(line.startswith("|") for line in section.splitlines())
    assert len(section.splitlines()) == 2 + len(results)
    assert "## Step Details" in markdown
    assert "OpenID: plan" in markdown and "Inji TestNG:" in markdown
