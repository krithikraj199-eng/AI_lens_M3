"""Member 3 Reliability Lab Contracts.

Defines the core domain data structures for chaos configuration, replay records,
paired evaluations, regression tests, and regression results.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Protocol, Union, runtime_checkable
import uuid


@runtime_checkable
class Storage(Protocol):
    """Minimal storage abstraction required for Reliability Lab persistence."""

    def save(self, key: str, item: Any) -> None:
        """Save or update an item by key."""
        ...

    def get(self, key: str) -> Optional[Any]:
        """Retrieve an item by key."""
        ...

    def list(self) -> list[Any]:
        """List all stored items."""
        ...


@dataclass
class ExpectedBehavior:
    """Structured assertions for deterministic task validation."""
    description: Optional[str] = None
    expected_outcome: Optional[str] = None  # "SUCCESS" | "FALLBACK"
    fallback_required: Optional[bool] = None
    max_retries: Optional[int] = None
    forbidden_failures: list[str] = field(default_factory=list)

    @classmethod
    def from_val(cls, val: Any) -> "ExpectedBehavior":
        if isinstance(val, cls):
            return val
        if isinstance(val, dict):
            return cls(
                description=val.get("description"),
                expected_outcome=val.get("expected_outcome"),
                fallback_required=val.get("fallback_required"),
                max_retries=val.get("max_retries"),
                forbidden_failures=list(val.get("forbidden_failures") or []),
            )
        if isinstance(val, str):
            return cls(description=val)
        return cls()


class FailureMode(str, Enum):
    """Supported controlled chaos failure modes."""
    NORMAL = "normal"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    EMPTY_RESULT = "empty_result"
    SLOW_RESPONSE = "slow_response"
    WRONG_TOOL = "wrong_tool"


@dataclass
class ChaosConfig:
    """Configuration for controlled chaos injection at the tool proxy boundary."""
    failure_mode: FailureMode = FailureMode.NORMAL
    delay_ms: int = 0
    error_message: Optional[str] = None
    status_code: int = 200
    target_tool: Optional[str] = None


@dataclass
class ReplayRecord:
    """Record storing scenario and mock response data for deterministic replay."""
    run_id: str
    prompt: str
    agent_version: str
    prompt_version: str
    failure_mode: FailureMode | str
    tool_calls: list[dict[str, Any]]
    mocked_responses: dict[str, Any]
    expected_behavior: Union[ExpectedBehavior, str]
    original_incident_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class EvaluationPair:
    """Before/after comparison pair capturing measured metrics and outcomes."""
    before_run_id: str
    after_run_id: str
    before_metrics: dict[str, Any]
    after_metrics: dict[str, Any]
    task_result: str
    regression_result: str
    evaluation_id: str = field(default_factory=lambda: f"eval-{uuid.uuid4().hex[:12]}")
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class RegressionResult:
    """Execution result of a single regression test run."""
    test_id: str
    run_id: str
    status: str  # "PASS" | "FAIL"
    measured_evidence: dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class RegressionTest:
    """Regression test definition containing scenario expectations and execution history."""
    test_id: str
    scenario: str
    expected_behavior: Union[ExpectedBehavior, str]
    latest_result: Optional[RegressionResult] = None
    history: list[RegressionResult] = field(default_factory=list)
    replay_record_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
