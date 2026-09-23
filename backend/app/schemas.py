from typing import Optional
"""Test Run Configuration domain models.

This milestone only defines and validates configuration for a future test
run — it does not execute anything. See docs/architecture.md for how this
fits into the planned pipeline.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.components import ALLOWED_COMPONENTS


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class TestRunStatus(str, Enum):
    """Lifecycle states for a test run.

    Only CONFIGURED is produced by this milestone. The remaining states are
    reserved for the future orchestrator/execution milestones.
    """

    CONFIGURED = "CONFIGURED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class OpenIDSuiteConfig(BaseModel):
    """OpenID Foundation Conformance Suite configuration for a test suite
    whose provider is "openid" (see app/openid_executor.py).

    `plan_name` and `plan_configuration` are supplied by whoever configures
    the test run — real conformance plan names/configuration are never
    invented by this project. `plan_configuration` is sent verbatim as the
    JSON body of the Conformance Suite's `POST /api/plan` call, so this is
    where a real target (e.g. an Inji Certify OpenID4VCI issuer endpoint)
    is supplied.
    """

    plan_name: str = Field(..., min_length=1, max_length=200)
    plan_configuration: Dict[str, Any] = Field(default_factory=dict)
    variant: Optional[Dict[str, Any]] = None
    modules: Optional[List[str]] = Field(
        default=None,
        description=(
            "Explicit test module names to run from the created plan. If "
            "omitted, the executor resolves modules from the plan's own "
            "module list."
        ),
    )


class TestSuiteConfig(BaseModel):
    """A reference to a test suite to be run against this configuration.

    `suite_id` is a free-form identifier on purpose: this milestone does not
    know the real OpenID Foundation test-plan identifiers or MOSIP test-rig
    identifiers, so it must accept whatever identifier later integration
    milestones introduce without a schema change.

    `openid_config` is optional at this (configuration) layer — a suite can
    be saved without it. It is only required to actually *execute* a suite
    whose provider is "openid"; OpenIDConformanceExecutor rejects that with
    a clear, structured error rather than inventing plan details. Keeping
    the requirement out of this schema avoids forcing OpenID-specific
    fields onto non-OpenID providers.
    """

    provider: str = Field(..., min_length=1, max_length=100)
    suite_id: str = Field(..., min_length=1, max_length=200)
    display_name: str = Field(..., min_length=1, max_length=200)
    version: Optional[str] = Field(default=None, max_length=50)
    openid_config: Optional[OpenIDSuiteConfig] = None


class BenchmarkConfig(BaseModel):
    minimum_pass_rate: float = Field(..., ge=0, le=100)
    critical_failures_allowed: int = Field(..., ge=0)


class MetadataConfig(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=2000)
    created_by: Optional[str] = Field(default=None, max_length=200)


class TestRunBase(BaseModel):
    run_name: str = Field(..., min_length=1, max_length=200)
    environment: Environment
    components: list[str] = Field(..., min_length=1)
    test_suites: list[TestSuiteConfig] = Field(..., min_length=1)
    benchmark: BenchmarkConfig
    metadata: Optional[MetadataConfig] = None

    @field_validator("components")
    @classmethod
    def components_must_be_known(cls, value: list[str]) -> list[str]:
        unknown = [c for c in value if c not in ALLOWED_COMPONENTS]
        if unknown:
            allowed = ", ".join(sorted(ALLOWED_COMPONENTS))
            raise ValueError(
                f"Unknown component(s): {', '.join(unknown)}. Allowed: {allowed}"
            )
        return value


class TestRunCreateRequest(TestRunBase):
    """Shape accepted by POST /api/test-runs."""


class TestRunConfig(TestRunBase):
    """Stored domain representation of a Test Run Configuration."""

    id: str
    status: TestRunStatus
    created_at: datetime


class TestRunResponse(TestRunConfig):
    """Shape returned by the API. Kept distinct from TestRunConfig so the
    stored representation can evolve independently of the public contract.
    """
