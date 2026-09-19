# Member 4 Handoff Contract: Regression Library API

This document defines the service interfaces, endpoints, and JSON payloads provided by **Member 3 (Reliability Lab)** for **Member 4 (AWS Platform & API Shell)**.

> **CRITICAL NOTICE ON SYNTHETIC DATA**:
> All IDs (e.g. `reg-timeout-001`, `run-replay-abc12345`), latency numbers (e.g. `950`), token counts (e.g. `320`), tool-call counts (e.g. `3`), pass rates, and timestamps in this document are **synthetic API examples for illustration only**.

---

## 1. Overview & Service Semantics

Member 4 exposes the Regression Library via API Gateway / Lambda routes mapped directly to Member 3 service handlers:

| Route | HTTP Method | Member 3 Service Handler |
| :--- | :--- | :--- |
| `/tests` | `GET` | `list_tests_service(storage: Optional[Storage] = None) -> dict` |
| `/tests` | `POST` | `create_test_service(payload: dict, storage: Optional[Storage] = None) -> dict` |
| `/tests/run` | `POST` | `run_tests_service(payload: dict, storage: Optional[Storage] = None) -> dict` |

**Storage Abstraction**:
The public regression API accepts any storage adapter adhering to the `Storage` protocol (`save(key, item)`, `get(key)`, `list()`). In production, Member 4 can provide a DynamoDB-backed storage adapter; locally, `MockStorage` is used by default.

---

## 2. Python Lambda Integration Example

```python
import json
from reliability_lab.regression import (
    list_tests_service,
    create_test_service,
    run_tests_service,
)

def lambda_handler(event, context):
    http_method = event.get("httpMethod", "GET").upper()
    path = event.get("path", "/tests").rstrip("/")
    
    try:
        body = json.loads(event.get("body", "{}")) if event.get("body") else {}
    except Exception:
        body = {}

    # Member 4 can pass a DynamoDB storage adapter if available: storage=dynamo_adapter
    if path == "/tests" and http_method == "GET":
        response = list_tests_service()
    elif path == "/tests" and http_method == "POST":
        response = create_test_service(body)
    elif path == "/tests/run" and http_method == "POST":
        response = run_tests_service(body)
    else:
        response = {"status": "ERROR", "error": f"Unsupported route {http_method} {path}"}

    status_code = 400 if response.get("status") == "ERROR" else (201 if response.get("status") == "CREATED" else 200)

    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(response),
    }
```

---

## 3. Scorecard Rule & Transparent Metrics

> **STRICT SCORECARD RULE**:
> **Allowed**:
> - `"8 / 10 tests passed"`
> - `"80.0% defined test pass rate"`
> 
> **FORBIDDEN**:
> - `"The AI agent is 80% reliable"` (No AI-generated or subjective universal reliability scores).

All results and metrics:
1. Derive strictly from actual execution evidence (tool calls, tokens, latency, errors, outcome).
2. Missing metrics remain `null` (`None`). Zero fabrication.
3. Deterministic PASS/FAIL is evaluated against structured expected behavior assertions (zero LLMs).

---

## 4. Endpoint Specifications & Payloads

### A. `GET /tests`
Retrieves all registered regression tests.

*(Synthetic API Response Example)*:
```json
{
  "status": "SUCCESS",
  "count": 1,
  "tests": [
    {
      "test_id": "reg-timeout-001",
      "scenario": "Order lookup timeout retry limit",
      "expected_behavior": {
        "description": "Order lookup should fallback gracefully on timeout",
        "expected_outcome": "FALLBACK",
        "fallback_required": true,
        "max_retries": 2
      },
      "replay_record_id": "replay-scenario-abc12345",
      "latest_result": {
        "test_id": "reg-timeout-001",
        "run_id": "run-replay-fedcba98",
        "status": "PASS",
        "measured_evidence": {
          "tool_calls": 3,
          "tokens": 320,
          "latency_ms": 950,
          "outcome": "FALLBACK",
          "errors": ["TimeoutError: carrier service unreachable"]
        },
        "timestamp": "2026-09-18T15:00:00.000000+00:00"
      },
      "history_count": 3,
      "created_at": "2026-09-18T14:30:00.000000+00:00"
    }
  ]
}
```

---

### B. `POST /tests`
Registers a new regression test from a discovered failure or replay scenario.

*(Synthetic API Request Example)*:
```json
{
  "test_id": "reg-timeout-001",
  "scenario": "Order lookup timeout retry limit",
  "expected_behavior": {
    "description": "Must not exceed 2 retries and should invoke fallback gracefully",
    "expected_outcome": "FALLBACK",
    "fallback_required": true,
    "max_retries": 2,
    "forbidden_failures": ["UnhandledException"]
  },
  "replay_record_id": "replay-scenario-abc12345"
}
```

*(Synthetic API Response Example)*:
```json
{
  "status": "CREATED",
  "test": {
    "test_id": "reg-timeout-001",
    "scenario": "Order lookup timeout retry limit",
    "expected_behavior": {
      "description": "Must not exceed 2 retries and should invoke fallback gracefully",
      "expected_outcome": "FALLBACK",
      "fallback_required": true,
      "max_retries": 2,
      "forbidden_failures": ["UnhandledException"]
    },
    "replay_record_id": "replay-scenario-abc12345",
    "latest_result": null,
    "history_count": 0,
    "created_at": "2026-09-18T15:10:00.000000+00:00"
  }
}
```

---

### C. `POST /tests/run`
Executes a single test by `test_id` or executes all registered regression tests.

#### 1. Run Single Test:
*(Synthetic API Request Example)*:
```json
{
  "test_id": "reg-timeout-001",
  "agent_version": "v1.0.1-fixed"
}
```

*(Synthetic API Response Example)*:
```json
{
  "status": "COMPLETED",
  "mode": "SINGLE",
  "results": [
    {
      "test_id": "reg-timeout-001",
      "run_id": "run-replay-99887766",
      "status": "PASS",
      "measured_evidence": {
        "tool_calls": 3,
        "tokens": 320,
        "latency_ms": 950,
        "outcome": "FALLBACK",
        "errors": ["TimeoutError: carrier service unreachable"]
      },
      "timestamp": "2026-09-18T15:15:00.000000+00:00"
    }
  ],
  "scorecard": {
    "total": 1,
    "passed": 1,
    "failed": 0,
    "pass_rate": 1.0,
    "pass_rate_pct": 100.0,
    "summary": "1 / 1 tests passed (100.0% defined test pass rate)"
  }
}
```

#### 2. Run All Tests:
*(Synthetic API Request Example)*:
```json
{
  "run_all": true,
  "agent_version": "v1.0.1-fixed"
}
```

*(Synthetic API Response Example)*:
```json
{
  "status": "COMPLETED",
  "mode": "ALL",
  "total_executed": 3,
  "results": [
    {
      "test_id": "reg-timeout-001",
      "run_id": "run-replay-11223344",
      "status": "PASS",
      "measured_evidence": {
        "tool_calls": 3,
        "tokens": 320,
        "latency_ms": 950,
        "outcome": "FALLBACK"
      },
      "timestamp": "2026-09-18T15:20:00.000000+00:00"
    },
    {
      "test_id": "reg-rate-limit-002",
      "run_id": "run-replay-55667788",
      "status": "PASS",
      "measured_evidence": {
        "tool_calls": 2,
        "tokens": 280,
        "latency_ms": 600,
        "outcome": "FALLBACK"
      },
      "timestamp": "2026-09-18T15:20:02.000000+00:00"
    },
    {
      "test_id": "reg-edge-003",
      "run_id": "run-replay-9900aabb",
      "status": "PASS",
      "measured_evidence": {
        "tool_calls": 1,
        "tokens": 150,
        "latency_ms": 300,
        "outcome": "SUCCESS"
      },
      "timestamp": "2026-09-18T15:20:03.000000+00:00"
    }
  ],
  "scorecard": {
    "total": 3,
    "passed": 3,
    "failed": 0,
    "pass_rate": 1.0,
    "pass_rate_pct": 100.0,
    "summary": "3 / 3 tests passed (100.0% defined test pass rate)"
  }
}
```
