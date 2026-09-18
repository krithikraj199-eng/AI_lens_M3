# Member 4 Handoff Contract: POST /evaluations

This document defines the service and payload contract provided by **Member 3 (Reliability Lab)** for **Member 4 (AWS Platform & API Shell)**.

> **CRITICAL NOTICE ON SYNTHETIC DATA**:
> All IDs (e.g. `run-before-001`, `eval-a1b2c3d4e5f6`, `reg-001`), token counts (e.g. `450`, `320`), latencies (e.g. `1500`, `950`), tool-call counts (e.g. `5`, `3`), and timestamps (e.g. `2026-09-18T15:00:00.000000+00:00`) in this document are **synthetic API examples for illustration only**.

---

## 1. Overview
Member 4 routes `POST /evaluations` (via API Gateway & Lambda) to Member 3's `execute_evaluation(payload: dict, storage: Optional[Storage] = None) -> dict`.

Member 3 extracts actual execution evidence, validates scenario equivalence and pairing semantics, computes mathematically valid deltas, and derives task and regression results. Member 4 only needs to parse JSON, invoke the function, and serialize the returned dictionary.

**Storage Abstraction**:
The public evaluator accepts any storage adapter adhering to the `Storage` protocol (`save(key, item)`, `get(key)`, `list()`). In production, Member 4 can supply a DynamoDB-backed storage adapter; for local execution and tests, `MockStorage` is used by default.

---

## 2. Python Lambda Integration Example
```python
import json
from reliability_lab.evaluation import execute_evaluation

def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
    except Exception:
        body = {}

    # storage can be passed if Member 4 provides a DynamoDB adapter: execute_evaluation(body, storage=dynamo_adapter)
    response = execute_evaluation(body)
    status_code = 400 if response.get("status") == "ERROR" else 200

    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(response),
    }
```

---

## 3. Allowed Metrics & Regression Integrity Rules
The evaluation preserves and compares **only** the allowed metrics:
1. `tool_calls` (count of tool executions, represented as numeric integer count)
2. `tokens` (measured token consumption)
3. `latency_ms` (measured end-to-end execution latency in ms)
4. `task_result` (`PASS` | `FAIL`)
5. `regression_result` (`PASS` | `FAIL` | `NOT_EVALUATED`)

> **Regression Evidence Trust Requirement**:
> **Member 4 must NEVER submit arbitrary PASS/FAIL text as trusted regression evidence.**
> Passing raw strings like `"regression_result": "PASS"` or `"regression_result": "FAIL"` is rejected as untrusted and will strictly return `"NOT_EVALUATED"`.
> Regression evidence must originate from an authentic `RegressionResult` record or be referenced by a valid stored `regression_result_id` that is validated against the relevant `after_run`.

> **Analytical Principles**:
> - Never assume `after < before` for numeric metrics. A fixed agent providing a helpful fallback message may use more tokens than an unhandled crash. PASS/FAIL is derived from defined expected behavior.
> - **Zero metric fabrication**: Missing metrics remain `null` (`None`). Never populate missing metrics with zeros, defaults, or estimates.
> - **Safe percent changes**: Percentage change returns `null` if the baseline denominator is zero or if either metric is missing.

---

## 4. Request Structure

### A. By Run IDs (Stored Replays/Runs):
*(Synthetic API Example)*
```json
{
  "before_run_id": "run-before-001",
  "after_run_id": "run-after-002",
  "expected_behavior": "Order lookup should fallback on timeout",
  "prompt": "Where is order #8271?",
  "failure_mode": "timeout",
  "regression_result_id": "reg-001"
}
```

### B. Structured Expected Behavior Assertions:
Member 4 can provide deterministic structured assertions inside `expected_behavior` (or top-level):
```json
{
  "before_run_id": "run-before-001",
  "after_run_id": "run-after-002",
  "expected_behavior": {
    "description": "Order lookup should fallback on timeout",
    "expected_outcome": "FALLBACK",
    "fallback_required": true,
    "max_retries": 2,
    "forbidden_failures": ["UnhandledException", "ConnectionResetError"]
  },
  "prompt": "Where is order #8271?",
  "failure_mode": "timeout",
  "regression_result_id": "reg-001"
}
```

### C. Direct Run Payloads:
*(Synthetic API Example — note: tool_calls is a numeric integer count; detailed tool call events belong in `events`)*
```json
{
  "before_run": {
    "run_id": "run-before-001",
    "request": "Where is order #8271?",
    "outcome": "FAILED",
    "agent_version": "v1.0.0-failing",
    "tool_calls": 5,
    "tokens": 450,
    "latency_ms": 1500,
    "events": []
  },
  "after_run": {
    "run_id": "run-after-002",
    "request": "Where is order #8271?",
    "outcome": "FALLBACK",
    "agent_version": "v1.0.1-fixed",
    "tool_calls": 3,
    "tokens": 320,
    "latency_ms": 950,
    "response": {
      "order_id": "8271",
      "fallback_triggered": true
    },
    "events": []
  },
  "expected_behavior": {
    "description": "Order lookup should fallback on timeout",
    "expected_outcome": "FALLBACK",
    "fallback_required": true,
    "max_retries": 2
  },
  "regression_result_id": "reg-001"
}
```

---

## 5. Response Structures

### A. Successful Evaluation (`status: "EVALUATED"`)
*(Synthetic API Example)*
```json
{
  "status": "EVALUATED",
  "evaluation_id": "eval-a1b2c3d4e5f6",
  "before_run_id": "run-before-001",
  "after_run_id": "run-after-002",
  "scenario": {
    "prompt": "Where is order #8271?",
    "failure_mode": "timeout",
    "expected_behavior": "Order lookup should fallback on timeout"
  },
  "metrics": {
    "before": {
      "tool_calls": 5,
      "tokens": 450,
      "latency_ms": 1500,
      "outcome": "FAILED",
      "errors": ["TimeoutError: Connection timed out"]
    },
    "after": {
      "tool_calls": 3,
      "tokens": 320,
      "latency_ms": 950,
      "outcome": "FALLBACK",
      "errors": ["TimeoutError: Connection timed out"]
    },
    "deltas": {
      "tool_calls_delta": -2,
      "tokens_delta": -130,
      "latency_ms_delta": -550,
      "tool_calls_pct_change": -40.0,
      "tokens_pct_change": -28.89,
      "latency_ms_pct_change": -36.67
    }
  },
  "task_result": "PASS",
  "regression_result": "PASS",
  "evaluated_at": "2026-09-18T15:00:00.000000+00:00"
}
```

> **Evaluation Identifier Note**:
> `evaluation_id` is a uniquely generated identifier (e.g. `eval-a1b2c3d4e5f6`). Repeated evaluations of the same before/after pair each receive a distinct `evaluation_id`, guaranteeing that prior evaluation evidence is never overwritten in storage.

### B. Validation Error (`status: "ERROR"`)
*(Synthetic API Example)*
```json
{
  "status": "ERROR",
  "error": "before_run_id and after_run_id must be distinct. Got identical 'run-001'."
}
```
