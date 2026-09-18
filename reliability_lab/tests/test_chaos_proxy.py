"""Tests for Phase P1: Controlled Chaos Injection.

Tests P1-T01 through P1-T11.
"""

import time

from reliability_lab.contracts import ChaosConfig, FailureMode
from reliability_lab.mocks.mock_tool import MockOrderTool, get_order


def test_p1_t01_normal_returns_underlying_result():
    """P1-T01: NORMAL returns exactly the underlying tool result."""
    from reliability_lab.chaos.proxy import ChaosProxy

    proxy = ChaosProxy(get_order)
    result = proxy("8271")

    expected = get_order("8271")
    assert result == expected
    assert result["order_id"] == "8271"
    assert result["status"] == "IN_TRANSIT"


def test_p1_t02_timeout_produces_deterministic_timeout():
    """P1-T02: TIMEOUT produces deterministic controlled timeout."""
    from reliability_lab.chaos.proxy import ChaosProxy
    from reliability_lab.chaos.exceptions import ChaosTimeoutError

    cfg = ChaosConfig(
        failure_mode=FailureMode.TIMEOUT,
        error_message="Controlled timeout on order lookup",
    )
    proxy = ChaosProxy(get_order, config=cfg)

    raised = False
    try:
        proxy("8271")
    except ChaosTimeoutError as exc:
        raised = True
        assert "Controlled timeout on order lookup" in str(exc)
        assert isinstance(exc, TimeoutError)
    assert raised


def test_p1_t03_rate_limit_produces_deterministic_429():
    """P1-T03: RATE_LIMIT produces deterministic 429 behavior."""
    from reliability_lab.chaos.proxy import ChaosProxy
    from reliability_lab.chaos.exceptions import ChaosRateLimitError

    cfg = ChaosConfig(
        failure_mode=FailureMode.RATE_LIMIT,
        status_code=429,
        error_message="Too Many Requests: rate limit exceeded",
    )
    proxy = ChaosProxy(get_order, config=cfg)

    raised = False
    try:
        proxy("8271")
    except ChaosRateLimitError as exc:
        raised = True
        assert exc.status_code == 429
        assert "Too Many Requests" in str(exc)
    assert raised


def test_p1_t04_empty_result_produces_deterministic_empty():
    """P1-T04: EMPTY_RESULT produces deterministic empty result."""
    from reliability_lab.chaos.proxy import ChaosProxy

    cfg = ChaosConfig(failure_mode=FailureMode.EMPTY_RESULT)
    proxy = ChaosProxy(get_order, config=cfg)

    result = proxy("8271")
    assert result == {}


def test_p1_t05_slow_response_applies_deterministic_delay():
    """P1-T05: SLOW_RESPONSE applies configured deterministic delay."""
    from reliability_lab.chaos.proxy import ChaosProxy

    cfg = ChaosConfig(failure_mode=FailureMode.SLOW_RESPONSE, delay_ms=25)
    proxy = ChaosProxy(get_order, config=cfg)

    start = time.perf_counter()
    result = proxy("8271")
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms >= 20.0, f"Expected at least ~25ms delay, got {elapsed_ms}ms"
    assert result["order_id"] == "8271"
    assert result["status"] == "IN_TRANSIT"


def test_p1_t06_wrong_tool_applies_deterministic_mapping():
    """P1-T06: WRONG_TOOL applies configured deterministic mapping."""
    from reliability_lab.chaos.proxy import ChaosProxy
    from reliability_lab.mocks.mock_tool import get_inventory

    cfg = ChaosConfig(failure_mode=FailureMode.WRONG_TOOL)
    proxy = ChaosProxy(get_order, config=cfg, wrong_tool_target=get_inventory)

    result = proxy("8271")
    assert "inventory_id" in result or result.get("tool") == "get_inventory"
    # Should not return the normal order status dictionary
    assert result.get("status") != "IN_TRANSIT"


def test_p1_t07_repeating_identical_config_produces_equivalent_behavior():
    """P1-T07: Repeating identical ChaosConfig produces equivalent behavior."""
    from reliability_lab.chaos.proxy import ChaosProxy
    from reliability_lab.chaos.exceptions import ChaosTimeoutError

    cfg = ChaosConfig(failure_mode=FailureMode.TIMEOUT)
    proxy = ChaosProxy(get_order, config=cfg)

    for i in range(5):
        raised_iter = False
        try:
            proxy("8271")
        except ChaosTimeoutError:
            raised_iter = True
        assert raised_iter


def test_p1_t08_switching_back_to_normal_restores_behavior():
    """P1-T08: Switching back to NORMAL fully restores underlying tool behavior."""
    from reliability_lab.chaos.proxy import ChaosProxy
    from reliability_lab.chaos.exceptions import ChaosTimeoutError

    proxy = ChaosProxy(get_order, config=ChaosConfig(failure_mode=FailureMode.TIMEOUT))

    # In timeout mode
    raised = False
    try:
        proxy("8271")
    except ChaosTimeoutError:
        raised = True
    assert raised

    # Switch back to NORMAL via set_config
    proxy.set_config(ChaosConfig(failure_mode=FailureMode.NORMAL))
    result1 = proxy("8271")
    assert result1["status"] == "IN_TRANSIT"

    # Inject rate limit, then switch back via reset()
    proxy.set_config(ChaosConfig(failure_mode=FailureMode.RATE_LIMIT))
    proxy.reset()
    result2 = proxy("8271")
    assert result2["status"] == "IN_TRANSIT"


def test_p1_t09_invalid_failure_mode_rejected_safely():
    """P1-T09: Invalid failure mode is rejected safely."""
    from reliability_lab.chaos.proxy import ChaosProxy

    proxy = ChaosProxy(get_order)

    # Passing invalid failure mode should raise ValueError
    raised = False
    try:
        proxy.set_config(ChaosConfig(failure_mode="corrupt_unknown_mode"))  # type: ignore
    except ValueError:
        raised = True
    assert raised


def test_p1_t10_production_fault_injection_prevented_by_boundary():
    """P1-T10: Production fault injection is prevented by the approved boundary."""
    from reliability_lab.chaos.proxy import ChaosProxy
    from reliability_lab.chaos.exceptions import UnapprovedToolError

    def production_payment_service(card_number: str):
        return {"status": "CHARGED"}

    raised = False
    try:
        ChaosProxy(production_payment_service)
    except UnapprovedToolError as exc:
        raised = True
        assert "unapproved tool" in str(exc).lower()
    assert raised


def test_p1_t11_agent_and_tool_contain_no_embedded_chaos():
    """P1-T11: Agent/tool business modules contain no embedded chaos implementation."""
    tool = MockOrderTool()
    tool_attributes = dir(tool)

    for attr in tool_attributes:
        assert "chaos" not in attr.lower(), f"Tool should not have chaos attribute {attr}"
        assert "proxy" not in attr.lower(), f"Tool should not have proxy attribute {attr}"
        assert "inject" not in attr.lower(), f"Tool should not have inject attribute {attr}"
