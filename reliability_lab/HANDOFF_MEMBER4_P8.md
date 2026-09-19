# Member 4 Handoff Contract: Phase P8 Core Outputs & Evidence

This document defines the truthful, structured evidence outputs delivered by **Member 3 (Reliability Lab)** for **Member 4 (AWS Platform & UI Dashboard)** for **AgentLens — AI Reliability Intelligence**.

> **MEMBER 4 RESPONSIBILITY**: Member 4 owns frontend dashboard rendering, visual styling, card layouts, and graph visualization.
> **MEMBER 3 RESPONSIBILITY**: Member 3 provides structured, truthful, auditable evidence with **zero metric fabrication**.

---

## 1. Replay Timeline Payload

### Endpoint / Function:
- Python: `build_replay_timeline(run_or_telemetry)` / `serialize_replay_timeline(timeline)`
- API: Exposed inside Replay response `POST /runs/{run_id}/replay` as `timeline` or standalone helper.

### Guaranteed Event Ordering:
$$\text{user} \longrightarrow \text{agent} \longrightarrow \text{tool} \longrightarrow \text{response/error} \longrightarrow \text{retry/fallback} \longrightarrow \text{agent\_end}$$

Every event in the timeline originates from an **actual recorded telemetry event**. No synthetic placeholder events are added for visual polish. If an agent did not retry, no retry step exists. If an agent did not invoke a fallback, no fallback step exists.

### Example JSON Payload:
```json
{
  "run_id": "run-replay-a1b2c3d4",
  "total_events": 6,
  "stages_present": ["user", "agent", "tool", "error", "retry", "fallback"],
  "has_retry": true,
  "has_fallback": true,
  "has_error": true,
  "final_outcome": "FALLBACK",
  "events": [
    {
      "step_number": 1,
      "stage": "user",
      "event_type": "user_request",
      "timestamp": 1726718400.100,
      "data": {
        "request": "Where is order #8271?"
      },
      "description": "User submitted request: 'Where is order #8271?'"
    },
    {
      "step_number": 2,
      "stage": "agent",
      "event_type": "agent_start",
      "timestamp": 1726718400.102,
      "data": {
        "agent_version": "v1.0.1-fixed"
      },
      "description": "Agent initiated execution (v1.0.1-fixed)"
    },
    {
      "step_number": 3,
      "stage": "tool",
      "event_type": "tool_call_start",
      "timestamp": 1726718400.105,
      "data": {
        "tool": "get_order",
        "args": {"order_id": "8271", "attempt": 1}
      },
      "description": "Invoked tool 'get_order' (attempt 1)"
    },
    {
      "step_number": 4,
      "stage": "error",
      "event_type": "tool_call_error",
      "timestamp": 1726718400.120,
      "data": {
        "tool": "get_order",
        "error": "TimeoutError: carrier service unreachable"
      },
      "description": "Tool 'get_order' failed: TimeoutError: carrier service unreachable"
    },
    {
      "step_number": 5,
      "stage": "retry",
      "event_type": "retry_attempt",
      "timestamp": 1726718400.122,
      "data": {
        "attempt": 2,
        "tool": "get_order"
      },
      "description": "Retry attempt 2 initiated for 'get_order'"
    },
    {
      "step_number": 6,
      "stage": "fallback",
      "event_type": "fallback_invoked",
      "timestamp": 1726718400.150,
      "data": {
        "response": {
          "order_id": "8271",
          "status": "CARRIER_DELAYED",
          "fallback_triggered": true
        }
      },
      "description": "Fallback handler invoked: status=CARRIER_DELAYED"
    }
  ]
}
```

---

## 2. Before/After Panel Payload

### Endpoint / Function:
- Python: `build_before_after_panel(evaluation_pair_or_result)`
- API: Returned in `POST /evaluations` as both root metrics and `panel`.

### Exposed Fields:
- `before_run_id`: Original failing run ID
- `after_run_id`: Replay fixed run ID
- `tool_calls`: `{ "before": int, "after": int, "delta": int, "pct_change": float | null }`
- `tokens`: `{ "before": int, "after": int, "delta": int, "pct_change": float | null }`
- `latency_ms`: `{ "before": int, "after": int, "delta": int, "pct_change": float | null }`
- `task_result`: `"PASS" | "FAIL"` (derived from defined expected behavior)
- `regression_result`: `"PASS" | "FAIL" | "NOT_EVALUATED"` (derived strictly from genuine regression test results)

### Example JSON Payload:
```json
{
  "evaluation_id": "eval-9b7e41c2a014",
  "before_run_id": "run-failing-001",
  "after_run_id": "run-replay-002",
  "tool_calls": {
    "before": 5,
    "after": 3,
    "delta": -2,
    "pct_change": -40.0
  },
  "tokens": {
    "before": 450,
    "after": 320,
    "delta": -130,
    "pct_change": -28.89
  },
  "latency_ms": {
    "before": 1500,
    "after": 950,
    "delta": -550,
    "pct_change": -36.67
  },
  "task_result": "PASS",
  "regression_result": "PASS",
  "evaluated_at": "2026-09-19T04:10:00.000000+00:00"
}
```

---

## 3. Regression Suite & History Payload

### Endpoint / Function:
- API: `GET /tests`, `POST /tests`, `POST /tests/run`
- Serialized by: `_serialize_regression_test(test)`

### Exposed Fields:
- `test_id`: Unique test gate identifier
- `scenario`: Scenario description
- `expected_behavior`: Assertions or expected outcome
- `latest_result`: Most recent execution result
- `history`: **Complete array of all historical `RegressionResult` records**
- `history_count`: Total runs executed

### Example JSON Payload:
```json
{
  "test_id": "reg-test-8271",
  "scenario": "Canonical order carrier timeout handling",
  "expected_behavior": {
    "description": "Agent must handle timeout within max 2 retries and invoke fallback without unhandled loop.",
    "expected_outcome": "FALLBACK",
    "fallback_required": true,
    "max_retries": 2
  },
  "replay_record_id": "replay-8271-timeout",
  "latest_result": {
    "test_id": "reg-test-8271",
    "run_id": "run-replay-5544",
    "status": "PASS",
    "measured_evidence": {
      "tool_calls": 3,
      "tokens": 320,
      "latency_ms": 950,
      "outcome": "FALLBACK",
      "errors": ["TimeoutError: carrier service unreachable"]
    },
    "timestamp": "2026-09-19T04:12:00.000000+00:00"
  },
  "history": [
    {
      "test_id": "reg-test-8271",
      "run_id": "run-replay-5544",
      "status": "PASS",
      "measured_evidence": {
        "tool_calls": 3,
        "tokens": 320,
        "latency_ms": 950,
        "outcome": "FALLBACK"
      },
      "timestamp": "2026-09-19T04:12:00.000000+00:00"
    }
  ],
  "history_count": 1,
  "created_at": "2026-09-19T04:00:00.000000+00:00"
}
```

---

## 4. Transparent Scorecard Payload

### Endpoint / Function:
- API: Returned in `POST /tests/run` and `RegressionLibrary.get_scorecard()`

### Mathematical Transparency Rule:
- ONLY computes verified statistics from executed test results.
- **ZERO arbitrary AI-generated reliability numbers** (e.g. no fake "87% reliability score").

### Computed Fields:
- `total_tests` (`total`): Total tests evaluated
- `tests_passed` (`passed`): Count of PASS
- `tests_failed` (`failed`): Count of FAIL
- `pass_rate`: Ratio (`passed / total`)
- `pass_rate_pct`: Percentage (`pass_rate * 100`)
- `categories`: Breakdown by failure mode / scenario category
- `summary`: E.g. `"5 / 6 tests passed (83.33% defined test pass rate)"`

### Example JSON Payload:
```json
{
  "total": 6,
  "total_tests": 6,
  "passed": 5,
  "tests_passed": 5,
  "failed": 1,
  "tests_failed": 1,
  "pass_rate": 0.8333,
  "pass_rate_pct": 83.33,
  "categories": {
    "timeout": {
      "total": 2,
      "passed": 2,
      "failed": 0,
      "pass_rate_pct": 100.0
    },
    "rate_limit": {
      "total": 1,
      "passed": 1,
      "failed": 0,
      "pass_rate_pct": 100.0
    },
    "empty_result": {
      "total": 1,
      "passed": 1,
      "failed": 0,
      "pass_rate_pct": 100.0
    },
    "slow_response": {
      "total": 1,
      "passed": 1,
      "failed": 0,
      "pass_rate_pct": 100.0
    },
    "wrong_tool": {
      "total": 1,
      "passed": 0,
      "failed": 1,
      "pass_rate_pct": 0.0
    }
  },
  "summary": "5 / 6 tests passed (83.33% defined test pass rate)"
}
```

---

## 5. Hackathon Evidence Bundle Payload

### Endpoint / Function:
- Python: `build_canonical_evidence_bundle(storage)` / `serialize_evidence_bundle(bundle)`

### Preserved Canonical Linkages:
Retains all 8 required audit artifacts:
1. `original_run_id`
2. `incident_id`
3. `chaos_config`
4. `replay_record`
5. `replay_run_id`
6. `evaluation_pair`
7. `regression_test`
8. `regression_history` (plus timeline)

### Example JSON Payload:
```json
{
  "bundle_id": "bundle-canonical-timeout",
  "incident_id": "inc-canonical-timeout-001",
  "original_run_id": "run-orig-failing-101",
  "replay_run_id": "run-replay-fixed-202",
  "chaos_config": {
    "failure_mode": "timeout",
    "target_tool": "get_order",
    "delay_ms": 0,
    "error_message": "Controlled timeout: carrier service unreachable",
    "status_code": 504
  },
  "replay_record": {
    "run_id": "run-orig-failing-101",
    "prompt": "Where is order #8271?",
    "agent_version": "v1.0.0-failing",
    "prompt_version": "p1.0",
    "failure_mode": "timeout",
    "tool_calls": [{"tool": "get_order", "args": {"order_id": "8271"}}],
    "original_incident_id": "inc-canonical-timeout-001"
  },
  "evaluation_pair": {
    "evaluation_id": "eval-c1d2e3f4",
    "before_run_id": "run-orig-failing-101",
    "after_run_id": "run-replay-fixed-202",
    "task_result": "PASS",
    "regression_result": "PASS"
  },
  "regression_test": {
    "test_id": "reg-canonical-timeout",
    "scenario": "Canonical order carrier timeout handling"
  },
  "regression_history": [
    {
      "test_id": "reg-canonical-timeout",
      "run_id": "run-replay-fixed-202",
      "status": "PASS"
    }
  ],
  "timeline": { ... },
  "created_at": "2026-09-19T04:15:00.000000+00:00"
}
```

---

## 6. Repeatability Benchmark Payload

### Endpoint / Function:
- Python: `RepeatabilityBenchmark().run_scenario(iterations=10)` / `serialize_benchmark_report(report)`

### Proving Determinism:
- `iterations`: Number of repeated executions (e.g. 10)
- `deterministic_outcome_rate`: 1.0 (100% of runs produced identical outcome `FALLBACK`)
- `tool_calls_consistent`: `true` (every single run made exactly 3 tool calls: 1 initial + 2 retries)
- `unique_run_ids`: `true` (every single run was freshly isolated with a distinct run ID)
- `is_deterministic`: `true`
- **Zero Fabrication**: Precision, recall, and F1 are NOT fabricated.

### Example JSON Payload:
```json
{
  "scenario_name": "canonical_order_timeout",
  "failure_mode": "timeout",
  "iterations": 10,
  "agent_version": "v1.0.1-fixed",
  "outcomes": ["FALLBACK", "FALLBACK", "FALLBACK", "FALLBACK", "FALLBACK", "FALLBACK", "FALLBACK", "FALLBACK", "FALLBACK", "FALLBACK"],
  "deterministic_outcome_rate": 1.0,
  "tool_calls_counts": [3, 3, 3, 3, 3, 3, 3, 3, 3, 3],
  "tool_calls_consistent": true,
  "unique_run_ids": true,
  "pass_rate": 1.0,
  "pass_rate_pct": 100.0,
  "is_deterministic": true,
  "runs": [ ... ]
}
```
