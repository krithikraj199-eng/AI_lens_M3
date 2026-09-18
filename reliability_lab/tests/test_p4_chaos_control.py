"""Tests for Phase P4: Chaos Control Contract for Member 4.

Tests P4-T01 through P4-T08.
"""

import json
import time

from reliability_lab.chaos.exceptions import ChaosTimeoutError, ChaosRateLimitError


def test_p4_t01_chaos_payload_stable_for_member4():
    """P4-T01: chaos input/output payload is stable for Member 4."""
    from reliability_lab.chaos.service import handle_chaos_request, reset_chaos

    reset_chaos()

    # 1. Valid request payload
    req = {
        "failure_mode": "timeout",
        "target_tool": "get_order",
        "error_message": "Carrier unreachable",
    }
    resp = handle_chaos_request(req)

    assert isinstance(resp, dict)
    assert resp["status"] == "APPLIED"
    assert resp["active_failure_mode"] == "timeout"
    assert "applied_at" in resp
    assert "active_config" in resp
    assert resp["active_config"]["failure_mode"] == "timeout"

    # Assert strictly JSON-serializable
    serialized = json.dumps(resp)
    deserialized = json.loads(serialized)
    assert deserialized["status"] == "APPLIED"

    # 2. Invalid failure mode returns clean ERROR response without crashing
    invalid_req = {"failure_mode": "unsupported_chaos_mode"}
    err_resp = handle_chaos_request(invalid_req)
    assert err_resp["status"] == "ERROR"
    assert "Invalid failure_mode" in err_resp["error"]
    assert json.dumps(err_resp)  # JSON-serializable

    reset_chaos()


def test_p4_t02_timeout_smoke_test():
    """P4-T02: timeout smoke test passes."""
    from reliability_lab.chaos.service import handle_chaos_request, reset_chaos, get_active_proxy

    reset_chaos()
    resp = handle_chaos_request({"failure_mode": "timeout", "target_tool": "get_order"})
    assert resp["status"] == "APPLIED"

    proxy = get_active_proxy("get_order")
    raised_timeout = False
    try:
        proxy("8271")
    except ChaosTimeoutError:
        raised_timeout = True
    assert raised_timeout

    reset_chaos()


def test_p4_t03_rate_limit_smoke_test():
    """P4-T03: 429 smoke test passes."""
    from reliability_lab.chaos.service import handle_chaos_request, reset_chaos, get_active_proxy

    reset_chaos()
    resp = handle_chaos_request({"failure_mode": "rate_limit", "status_code": 429})
    assert resp["status"] == "APPLIED"

    proxy = get_active_proxy("get_order")
    raised_rate_limit = False
    try:
        proxy("8271")
    except ChaosRateLimitError as exc:
        raised_rate_limit = True
        assert exc.status_code == 429
    assert raised_rate_limit
    reset_chaos()


def test_p4_t04_empty_result_smoke_test():
    """P4-T04: empty_result smoke test passes."""
    from reliability_lab.chaos.service import handle_chaos_request, reset_chaos, get_active_proxy

    reset_chaos()
    resp = handle_chaos_request({"failure_mode": "empty_result"})
    assert resp["status"] == "APPLIED"

    proxy = get_active_proxy("get_order")
    result = proxy("8271")
    assert result == {}

    reset_chaos()


def test_p4_t05_slow_response_smoke_test():
    """P4-T05: slow_response smoke test passes."""
    from reliability_lab.chaos.service import handle_chaos_request, reset_chaos, get_active_proxy

    reset_chaos()
    resp = handle_chaos_request({"failure_mode": "slow_response", "delay_ms": 25})
    assert resp["status"] == "APPLIED"

    proxy = get_active_proxy("get_order")
    start = time.perf_counter()
    result = proxy("8271")
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms >= 20.0
    assert result["status"] == "IN_TRANSIT"

    reset_chaos()


def test_p4_t06_wrong_tool_smoke_test():
    """P4-T06: wrong_tool smoke test passes."""
    from reliability_lab.chaos.service import handle_chaos_request, reset_chaos, get_active_proxy

    reset_chaos()
    resp = handle_chaos_request({"failure_mode": "wrong_tool"})
    assert resp["status"] == "APPLIED"

    proxy = get_active_proxy("get_order")
    result = proxy("8271")
    # Returns inventory schema or synthetic wrong-tool schema
    assert "inventory_id" in result or result.get("tool") == "wrong_tool"

    reset_chaos()


def test_p4_t07_reset_restores_normal_behavior():
    """P4-T07: reset correctly restores normal behavior."""
    from reliability_lab.chaos.service import handle_chaos_request, reset_chaos, get_active_proxy

    # Put into failure mode
    handle_chaos_request({"failure_mode": "timeout"})
    proxy = get_active_proxy("get_order")
    raised_timeout = False
    try:
        proxy("8271")
    except ChaosTimeoutError:
        raised_timeout = True
    assert raised_timeout

    # Reset
    reset_resp = reset_chaos()
    assert reset_resp["status"] == "RESET"
    assert reset_resp["active_failure_mode"] == "normal"

    # Verify normal execution restored
    result = proxy("8271")
    assert result["status"] == "IN_TRANSIT"
    assert result["order_id"] == "8271"


def test_p4_t08_canonical_timeout_repeatedly_demo_stable():
    """P4-T08: canonical timeout is repeatedly demo-stable across 10 cycles."""
    from reliability_lab.chaos.service import handle_chaos_request, reset_chaos, get_active_proxy

    proxy = get_active_proxy("get_order")

    for cycle in range(10):
        # 1. Baseline NORMAL
        reset_chaos()
        res_normal = proxy("8271")
        assert res_normal["status"] == "IN_TRANSIT", f"Cycle {cycle}: normal failed"

        # 2. Inject TIMEOUT
        resp = handle_chaos_request({"failure_mode": "timeout", "target_tool": "get_order"})
        assert resp["status"] == "APPLIED"
        cycle_raised = False
        try:
            proxy("8271")
        except ChaosTimeoutError:
            cycle_raised = True
        assert cycle_raised, f"Cycle {cycle}: timeout not raised"

        # 3. Restore NORMAL
        reset_resp = reset_chaos()
        assert reset_resp["status"] == "RESET"
        res_restored = proxy("8271")
        assert res_restored["status"] == "IN_TRANSIT", f"Cycle {cycle}: restore failed"
