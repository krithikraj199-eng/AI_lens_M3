# Member 4 Handoff Contract: POST /chaos

This document defines the service and payload contract provided by **Member 3 (Reliability Lab)** for **Member 4 (AWS Platform & API Shell)**.

---

## 1. Overview
Member 4 routes `POST /chaos` (via API Gateway & Lambda) to Member 3's `handle_chaos_request(payload: dict) -> dict`.

Member 3 provides all validation, proxy state management, and error handling. Member 4 only needs to parse JSON, invoke the function, and serialize the returned dictionary.

---

## 2. Python Lambda Integration Example
```python
import json
from reliability_lab.chaos import handle_chaos_request

def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
    except Exception:
        body = {}
    
    response = handle_chaos_request(body)
    status_code = 400 if response.get("status") == "ERROR" else 200
    
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(response),
    }
```

---

## 3. Supported Failure Modes
- `normal`: Restores baseline tool execution without faults.
- `timeout`: Injects deterministic controlled timeout exception on the target tool.
- `rate_limit`: Injects deterministic HTTP 429 Too Many Requests response/error.
- `empty_result`: Injects deterministic empty `{}` response without invoking the tool.
- `slow_response`: Injects a deterministic delay (`delay_ms`) before returning normal results.
- `wrong_tool`: Returns wrong tool schema/mapping (e.g. inventory data for order request).

---

## 4. Request Structure
```json
{
  "failure_mode": "timeout",
  "target_tool": "get_order",
  "delay_ms": 0,
  "error_message": "Controlled timeout: carrier service unreachable",
  "status_code": 429
}
```
- `failure_mode` (*required, string*): One of `["normal", "timeout", "rate_limit", "empty_result", "slow_response", "wrong_tool"]`. Case-insensitive.
- `target_tool` (*optional, string*): Name of tool to inject chaos into. Defaults to `"get_order"`.
- `delay_ms` (*optional, integer >= 0*): Milliseconds of latency for `slow_response`. Defaults to `0`.
- `error_message` (*optional, string*): Custom error message.
- `status_code` (*optional, integer*): HTTP status code for `rate_limit`. Defaults to `429`.

---

## 5. Response Structures

### A. Success Application (`status: "APPLIED"`)
```json
{
  "status": "APPLIED",
  "active_failure_mode": "timeout",
  "active_config": {
    "failure_mode": "timeout",
    "target_tool": "get_order",
    "delay_ms": 0,
    "error_message": "Controlled timeout: carrier service unreachable",
    "status_code": 429
  },
  "applied_at": "2026-09-18T14:45:00.000000+00:00",
  "message": "Chaos mode 'timeout' successfully activated on tool 'get_order'."
}
```

### B. Reset (`status: "RESET"`)
When `failure_mode` is `"normal"` or `reset_chaos()` is called:
```json
{
  "status": "RESET",
  "active_failure_mode": "normal",
  "active_config": {
    "failure_mode": "normal",
    "target_tool": null,
    "delay_ms": 0,
    "error_message": null,
    "status_code": 200
  },
  "applied_at": "2026-09-18T14:45:05.000000+00:00",
  "message": "Chaos reset to NORMAL. All tools operating in baseline mode."
}
```

### C. Validation Error (`status: "ERROR"`)
When an invalid or unknown failure mode is supplied:
```json
{
  "status": "ERROR",
  "error": "Invalid failure_mode 'corrupt_mode'. Must be one of ['normal', 'timeout', 'rate_limit', 'empty_result', 'slow_response', 'wrong_tool'].",
  "active_failure_mode": "normal"
}
```

---

## 6. Real Scenario Examples

### Normal Example (Baseline)
**Request**:
```json
{
  "failure_mode": "normal"
}
```
**Response**:
```json
{
  "status": "RESET",
  "active_failure_mode": "normal",
  "active_config": {
    "failure_mode": "normal",
    "target_tool": null,
    "delay_ms": 0,
    "error_message": null,
    "status_code": 200
  },
  "applied_at": "2026-09-18T14:45:10.000000+00:00",
  "message": "Chaos reset to NORMAL. All tools operating in baseline mode."
}
```

### Timeout Example (Canonical Demo)
**Request**:
```json
{
  "failure_mode": "timeout",
  "target_tool": "get_order",
  "error_message": "Carrier service unreachable"
}
```
**Response**:
```json
{
  "status": "APPLIED",
  "active_failure_mode": "timeout",
  "active_config": {
    "failure_mode": "timeout",
    "target_tool": "get_order",
    "delay_ms": 0,
    "error_message": "Carrier service unreachable",
    "status_code": 200
  },
  "applied_at": "2026-09-18T14:45:15.000000+00:00",
  "message": "Chaos mode 'timeout' successfully activated on tool 'get_order'."
}
```
