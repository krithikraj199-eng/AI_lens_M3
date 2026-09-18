"""Member 3 Reliability Lab Contracts.

Defines the core domain data structures for chaos configuration, replay records,
paired evaluations, regression tests, and regression results.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


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
    expected_behavior: str
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
    expected_behavior: str
    latest_result: Optional[RegressionResult] = None
    history: list[RegressionResult] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
