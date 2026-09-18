"""Test-Only Compatibility Fixtures.

These structures represent Member 2 / Shared Run and Incident data contracts
strictly for local testing and compatibility validation.

NOTICE:
Do NOT export or use these as secondary production models. They exist solely as
test fixtures until live shared contracts are linked from Member 2.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TestRunFixture:
    """Test compatibility fixture for the shared Member 2 Run contract."""
    __test__ = False  # Prevent pytest from collecting as a test class

    run_id: str
    agent_version: str
    prompt_version: str
    request: str
    events: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens: int = 0
    latency_ms: int = 0
    errors: list[str] = field(default_factory=list)
    outcome: str = "SUCCESS"
    detected_failures: list[str] = field(default_factory=list)


@dataclass
class TestIncidentFixture:
    """Test compatibility fixture for the shared Member 2 Incident contract."""
    __test__ = False  # Prevent pytest from collecting as a test class

    incident_id: str
    run_id: str
    failure_type: str
    severity: str
    evidence: dict[str, Any] = field(default_factory=dict)
    rca_status: str = "PENDING"
    recommended_fix: Optional[str] = None
