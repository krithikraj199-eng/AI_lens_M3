"""Controlled Replay and Scenario Fixtures for Reliability Lab.

Provides deterministic test fixtures for canonical scenarios:
- timeout (canonical demo)
- rate_limit (429)
- empty_result
- slow_response
- wrong_tool
- normal
"""

from dataclasses import dataclass, field
from typing import Any
from reliability_lab.contracts import FailureMode, ChaosConfig


@dataclass
class ControlledScenarioFixture:
    """Standardized descriptor for a controlled scenario fixture."""
    name: str
    prompt: str
    agent_version: str
    prompt_version: str
    failure_mode: FailureMode
    chaos_config: ChaosConfig
    expected_behavior: str
    mocked_responses: dict[str, Any] = field(default_factory=dict)


CANONICAL_TIMEOUT_FIXTURE = ControlledScenarioFixture(
    name="canonical_order_timeout",
    prompt="Where is order #8271?",
    agent_version="v1.0.0-failing",
    prompt_version="p1.0",
    failure_mode=FailureMode.TIMEOUT,
    chaos_config=ChaosConfig(
        failure_mode=FailureMode.TIMEOUT,
        target_tool="get_order",
        error_message="Controlled timeout: carrier service unreachable",
    ),
    expected_behavior="Agent must handle timeout within max 2 retries and invoke fallback without unhandled loop.",
    mocked_responses={
        "get_order": {
            "status": "TIMEOUT",
            "error": "TimeoutError: carrier service unreachable",
        }
    },
)

RATE_LIMIT_FIXTURE = ControlledScenarioFixture(
    name="carrier_rate_limit",
    prompt="Where is order #8271?",
    agent_version="v1.0.0-failing",
    prompt_version="p1.0",
    failure_mode=FailureMode.RATE_LIMIT,
    chaos_config=ChaosConfig(
        failure_mode=FailureMode.RATE_LIMIT,
        status_code=429,
        error_message="Too Many Requests: rate limit exceeded",
    ),
    expected_behavior="Agent must apply exponential backoff or return carrier rate limit fallback notice.",
    mocked_responses={
        "get_order": {
            "status_code": 429,
            "error": "Too Many Requests: rate limit exceeded",
        }
    },
)

EMPTY_RESULT_FIXTURE = ControlledScenarioFixture(
    name="order_empty_result",
    prompt="Where is order #8271?",
    agent_version="v1.0.0-failing",
    prompt_version="p1.0",
    failure_mode=FailureMode.EMPTY_RESULT,
    chaos_config=ChaosConfig(failure_mode=FailureMode.EMPTY_RESULT),
    expected_behavior="Agent must gracefully inform user when order lookup returns empty result.",
    mocked_responses={"get_order": {}},
)

SLOW_RESPONSE_FIXTURE = ControlledScenarioFixture(
    name="carrier_slow_response",
    prompt="Where is order #8271?",
    agent_version="v1.0.0-failing",
    prompt_version="p1.0",
    failure_mode=FailureMode.SLOW_RESPONSE,
    chaos_config=ChaosConfig(failure_mode=FailureMode.SLOW_RESPONSE, delay_ms=3000),
    expected_behavior="Agent must wait or notify user of extended carrier delay without crashing.",
    mocked_responses={
        "get_order": {
            "order_id": "8271",
            "status": "IN_TRANSIT",
            "delayed": True,
        }
    },
)

WRONG_TOOL_FIXTURE = ControlledScenarioFixture(
    name="inventory_wrong_tool",
    prompt="Where is order #8271?",
    agent_version="v1.0.0-failing",
    prompt_version="p1.0",
    failure_mode=FailureMode.WRONG_TOOL,
    chaos_config=ChaosConfig(failure_mode=FailureMode.WRONG_TOOL, target_tool="get_inventory"),
    expected_behavior="Agent must recognize inventory data is not order fulfillment data and clarify prompt.",
    mocked_responses={
        "get_inventory": {
            "inventory_id": "INV-8271",
            "stock_count": 42,
        }
    },
)

NORMAL_FIXTURE = ControlledScenarioFixture(
    name="canonical_order_normal",
    prompt="Where is order #8271?",
    agent_version="v1.0.0-failing",
    prompt_version="p1.0",
    failure_mode=FailureMode.NORMAL,
    chaos_config=ChaosConfig(failure_mode=FailureMode.NORMAL),
    expected_behavior="Order lookup succeeds immediately returning tracking details.",
    mocked_responses={
        "get_order": {
            "order_id": "8271",
            "status": "IN_TRANSIT",
            "tracking_number": "TRK-987654",
        }
    },
)
