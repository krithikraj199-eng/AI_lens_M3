"""Member 3 Before/After Evaluator for AgentLens.

Compares actual execution evidence between a failing agent version and a fixed
agent version running under the same controlled scenario (e.g. controlled timeout).
Extracts allowed metrics (tool_calls, tokens, latency_ms, task PASS/FAIL, regression PASS/FAIL)
with zero metric fabrication, mathematically valid deltas, and honest representation of
missing data.
"""

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
from typing import Any, Optional, Union

from reliability_lab.contracts import EvaluationPair, ExpectedBehavior, RegressionResult, Storage
from reliability_lab.mocks.mock_storage import MockStorage


def _extract_run_id(run: Any) -> str:
    """Extract run ID from any supported run representation."""
    if isinstance(run, dict):
        return str(run.get("run_id") or run.get("replay_run_id") or "")
    if hasattr(run, "replay_run_id"):
        return str(getattr(run, "replay_run_id"))
    if hasattr(run, "run_id"):
        return str(getattr(run, "run_id"))
    if hasattr(run, "telemetry") and hasattr(run.telemetry, "run_id"):
        return str(getattr(run.telemetry, "run_id"))
    return ""


def _extract_prompt(run: Any) -> Optional[str]:
    """Extract request/prompt from run representation."""
    if isinstance(run, dict):
        return run.get("request") or run.get("prompt")
    if hasattr(run, "telemetry") and hasattr(run.telemetry, "request"):
        return getattr(run.telemetry, "request")
    if hasattr(run, "request"):
        return getattr(run, "request")
    if hasattr(run, "prompt"):
        return getattr(run, "prompt")
    return None


def _extract_failure_mode(run: Any) -> Optional[str]:
    """Extract failure mode from run representation if present."""
    if isinstance(run, dict):
        fm = run.get("failure_mode")
        return str(fm).lower() if fm is not None else None
    if hasattr(run, "failure_mode"):
        fm = getattr(run, "failure_mode")
        if hasattr(fm, "value"):
            return str(fm.value).lower()
        return str(fm).lower() if fm is not None else None
    return None


def _extract_outcome(run: Any) -> Optional[str]:
    """Extract outcome status (e.g. SUCCESS, FAILED, FALLBACK)."""
    if isinstance(run, dict):
        outcome = run.get("outcome")
        if outcome is None and "telemetry" in run and isinstance(run["telemetry"], dict):
            outcome = run["telemetry"].get("outcome")
        return str(outcome).upper() if outcome is not None else None
    if hasattr(run, "telemetry") and hasattr(run.telemetry, "outcome"):
        return str(getattr(run.telemetry, "outcome")).upper()
    if hasattr(run, "outcome"):
        return str(getattr(run, "outcome")).upper()
    return None


def _extract_agent_version(run: Any) -> Optional[str]:
    """Extract agent version string."""
    if isinstance(run, dict):
        ver = run.get("agent_version")
        if ver is None and "telemetry" in run and isinstance(run["telemetry"], dict):
            ver = run["telemetry"].get("agent_version")
        return str(ver) if ver is not None else None
    if hasattr(run, "telemetry") and hasattr(run.telemetry, "agent_version"):
        return str(getattr(run.telemetry, "agent_version"))
    if hasattr(run, "agent_version"):
        return str(getattr(run, "agent_version"))
    return None


def _extract_errors(run: Any) -> list[str]:
    """Extract list of recorded errors."""
    if isinstance(run, dict):
        errors = run.get("errors")
        if errors is None and "telemetry" in run and isinstance(run["telemetry"], dict):
            errors = run["telemetry"].get("errors")
        return list(errors) if isinstance(errors, list) else []
    if hasattr(run, "telemetry") and hasattr(run.telemetry, "errors"):
        return list(getattr(run.telemetry, "errors"))
    if hasattr(run, "errors"):
        return list(getattr(run, "errors"))
    return []


def _extract_response(run: Any) -> Optional[dict[str, Any]]:
    """Extract final agent response payload."""
    if isinstance(run, dict):
        resp = run.get("response")
        if resp is None and "telemetry" in run and isinstance(run["telemetry"], dict):
            resp = run["telemetry"].get("response")
        return resp if isinstance(resp, dict) else None
    if hasattr(run, "telemetry") and hasattr(run.telemetry, "response"):
        return getattr(run.telemetry, "response")
    if hasattr(run, "response"):
        return getattr(run, "response")
    return None


class BeforeAfterEvaluator:
    """Evaluates and compares execution pairs under identical controlled scenarios.

    Strictly measures actual execution evidence without metric fabrication,
    synthetic reliability scores, or monotonic improvement assumptions.
    """

    def __init__(self, storage: Optional[Storage] = None) -> None:
        self.storage = storage or MockStorage()

    def resolve_run(self, run_or_id: Any) -> Any:
        """Resolve a run object from storage if a string ID is provided."""
        if isinstance(run_or_id, str):
            stored = self.storage.get(run_or_id)
            if stored is None:
                stored = self.storage.get(f"replay-res-{run_or_id}")
            if stored is None:
                raise KeyError(f"Run with ID '{run_or_id}' not found in storage.")
            return stored
        return run_or_id

    def validate_pair(
        self,
        before_run: Any,
        after_run: Any,
        expected_prompt: Optional[str] = None,
        expected_failure_mode: Optional[str] = None,
    ) -> tuple[str, str]:
        """Validate that before and after runs form a legitimate evaluation pair.

        Enforces:
        - Distinct and non-empty run IDs
        - Equivalent intended controlled scenario (prompt and failure mode)
        - Before run represents failing execution
        - After run represents candidate fixed execution

        Returns:
            Tuple of (before_run_id, after_run_id).

        Raises:
            ValueError: If validation conditions are violated.
        """
        before_id = _extract_run_id(before_run)
        after_id = _extract_run_id(after_run)

        if not before_id:
            raise ValueError("before_run must have a valid non-empty run_id.")
        if not after_id:
            raise ValueError("after_run must have a valid non-empty run_id.")
        if before_id == after_id:
            raise ValueError(f"before_run_id and after_run_id must be distinct. Got identical '{before_id}'.")

        # Scenario equivalence: prompt matching
        before_prompt = _extract_prompt(before_run)
        after_prompt = _extract_prompt(after_run)
        if expected_prompt:
            if before_prompt and before_prompt.strip().lower() != expected_prompt.strip().lower():
                raise ValueError(f"before_run prompt '{before_prompt}' does not match expected '{expected_prompt}'.")
            if after_prompt and after_prompt.strip().lower() != expected_prompt.strip().lower():
                raise ValueError(f"after_run prompt '{after_prompt}' does not match expected '{expected_prompt}'.")
        elif before_prompt and after_prompt:
            if before_prompt.strip().lower() != after_prompt.strip().lower():
                raise ValueError(
                    f"Scenario mismatch: before_run prompt ('{before_prompt}') "
                    f"and after_run prompt ('{after_prompt}') are not equivalent."
                )

        # Scenario equivalence: failure mode matching
        before_fm = _extract_failure_mode(before_run)
        after_fm = _extract_failure_mode(after_run)
        if expected_failure_mode:
            efm = expected_failure_mode.strip().lower()
            if before_fm and before_fm != efm:
                raise ValueError(f"before_run failure_mode '{before_fm}' does not match expected '{efm}'.")
            if after_fm and after_fm != efm:
                raise ValueError(f"after_run failure_mode '{after_fm}' does not match expected '{efm}'.")
        elif before_fm and after_fm:
            if before_fm != after_fm:
                raise ValueError(
                    f"Scenario mismatch: before_run failure_mode ('{before_fm}') "
                    f"and after_run failure_mode ('{after_fm}') are not equivalent."
                )

        # Validate that before_run represents a failing execution
        before_outcome = _extract_outcome(before_run)
        before_ver = _extract_agent_version(before_run) or ""
        before_errors = _extract_errors(before_run)

        is_before_failing = (
            before_outcome in ("FAILED", "ERROR", "TIMEOUT")
            or "failing" in before_ver.lower()
            or len(before_errors) > 0
        )
        if not is_before_failing:
            raise ValueError(
                f"before_run '{before_id}' does not represent a failing execution "
                f"(outcome={before_outcome}, version={before_ver})."
            )

        return before_id, after_id

    def extract_metrics(self, run: Any) -> dict[str, Any]:
        """Extract allowed numeric and operational metrics directly from actual run evidence.

        Allowed metrics:
        - tool_calls: int or None
        - tokens: int or None
        - latency_ms: int/float or None
        - outcome: str or None
        - errors: list[str]

        Never fabricates values. Missing metrics are returned as None.
        """
        target = getattr(run, "telemetry", run)

        # 1. tool_calls
        tool_calls_val: Optional[int] = None
        raw_tc = None
        if isinstance(target, dict):
            raw_tc = target.get("tool_calls")
        elif hasattr(target, "tool_calls"):
            raw_tc = getattr(target, "tool_calls")

        if isinstance(raw_tc, list):
            tool_calls_val = len(raw_tc)
        elif isinstance(raw_tc, (int, float)) and not isinstance(raw_tc, bool):
            tool_calls_val = int(raw_tc)
        elif raw_tc is None:
            tool_calls_val = None

        # 2. tokens
        tokens_val: Optional[int] = None
        raw_tok = None
        if isinstance(target, dict):
            raw_tok = target.get("tokens")
        elif hasattr(target, "tokens"):
            raw_tok = getattr(target, "tokens")

        if isinstance(raw_tok, (int, float)) and not isinstance(raw_tok, bool):
            tokens_val = int(raw_tok)
        elif raw_tok is None:
            tokens_val = None

        # 3. latency_ms
        latency_val: Optional[int] = None
        raw_lat = None
        if isinstance(target, dict):
            raw_lat = target.get("latency_ms")
        elif hasattr(target, "latency_ms"):
            raw_lat = getattr(target, "latency_ms")

        if isinstance(raw_lat, (int, float)) and not isinstance(raw_lat, bool):
            latency_val = int(raw_lat)
        elif raw_lat is None:
            latency_val = None

        return {
            "tool_calls": tool_calls_val,
            "tokens": tokens_val,
            "latency_ms": latency_val,
            "outcome": _extract_outcome(run),
            "errors": _extract_errors(run),
        }

    def compute_deltas(
        self,
        before_metrics: dict[str, Any],
        after_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute simple difference and percent change where mathematically valid.

        Never fabricates values. If either before or after is None, delta is None.
        Percent change is None if before is 0 or any operand is None.
        """
        deltas: dict[str, Any] = {}
        for key in ["tool_calls", "tokens", "latency_ms"]:
            b_val = before_metrics.get(key)
            a_val = after_metrics.get(key)

            if (
                b_val is not None
                and a_val is not None
                and isinstance(b_val, (int, float))
                and isinstance(a_val, (int, float))
                and not isinstance(b_val, bool)
                and not isinstance(a_val, bool)
            ):
                delta = a_val - b_val
                deltas[f"{key}_delta"] = delta
                if b_val != 0:
                    pct = round(((a_val - b_val) / float(b_val)) * 100.0, 2)
                    deltas[f"{key}_pct_change"] = pct
                else:
                    deltas[f"{key}_pct_change"] = None
            else:
                deltas[f"{key}_delta"] = None
                deltas[f"{key}_pct_change"] = None

        return deltas

    def evaluate_task_result(
        self,
        after_run: Any,
        expected_behavior: Optional[Union[ExpectedBehavior, dict[str, Any], str]] = None,
    ) -> str:
        """Derive task result (PASS/FAIL) strictly from defined expected behavior.

        Rule: PASS/FAIL is based on expected behavior fulfillment, NOT whether
        every numeric metric decreased.
        Deterministically evaluates actual execution evidence against structured assertions
        (expected_outcome, fallback_required, max_retries, forbidden_failures) without
        fragile free-text keyword matching or LLMs.
        """
        outcome = _extract_outcome(after_run)
        response = _extract_response(after_run)
        errors = _extract_errors(after_run)

        # 1. If after run failed or crashed with unhandled exception, task fails
        if outcome == "FAILED":
            return "FAIL"

        eb = ExpectedBehavior.from_val(expected_behavior)

        # 2. Check forbidden failures assertion
        if eb.forbidden_failures:
            for err in errors:
                err_str = str(err).lower()
                for forbidden in eb.forbidden_failures:
                    if str(forbidden).lower() in err_str:
                        return "FAIL"

        # 3. Check max_retries assertion if specified
        if eb.max_retries is not None:
            tc_count: Optional[int] = None
            target = getattr(after_run, "telemetry", after_run)
            raw_tc = None
            if isinstance(target, dict):
                raw_tc = target.get("tool_calls")
            elif hasattr(target, "tool_calls"):
                raw_tc = getattr(target, "tool_calls")

            if isinstance(raw_tc, list):
                tc_count = len(raw_tc)
            elif isinstance(raw_tc, (int, float)) and not isinstance(raw_tc, bool):
                tc_count = int(raw_tc)

            if tc_count is None:
                events = target.get("events") if isinstance(target, dict) else getattr(target, "events", None)
                if isinstance(events, list):
                    tc_count = sum(1 for e in events if isinstance(e, dict) and e.get("type") in ("tool_call", "tool_call_start"))

            if tc_count is not None:
                retries = max(0, tc_count - 1)
                if retries > eb.max_retries:
                    return "FAIL"

        # 4. Check expected_outcome assertion if specified
        if eb.expected_outcome is not None:
            if outcome != eb.expected_outcome.strip().upper():
                return "FAIL"

        # 5. Check fallback_required assertion if specified
        if eb.fallback_required is True:
            if outcome != "FALLBACK":
                return "FAIL"
            if response is not None and isinstance(response, dict) and response.get("fallback_triggered") is False:
                return "FAIL"
        elif eb.fallback_required is False:
            if outcome == "FALLBACK":
                return "FAIL"

        # 6. Fallback or Success outcome verification (when no structured assertions failed)
        if outcome in ("SUCCESS", "FALLBACK"):
            return "PASS"

        return "FAIL"

    def evaluate_regression_result(
        self,
        regression_result: Optional[Any] = None,
        after_run: Optional[Any] = None,
        after_run_id: Optional[str] = None,
    ) -> str:
        """Derive regression status strictly from actual regression evidence.

        Validates that regression evidence originates from a genuine RegressionResult
        or stored regression record, and belongs to the relevant after_run.
        Raw caller strings like 'PASS' or 'FAIL' are NEVER trusted as authoritative evidence.
        If no real regression evidence exists or evidence is mismatched, returns 'NOT_EVALUATED'.
        """
        expected_run_id = after_run_id or (_extract_run_id(after_run) if after_run is not None else None)

        # 1. Reject raw caller strings like "PASS" or "FAIL"
        if isinstance(regression_result, str):
            clean_str = regression_result.strip().upper()
            if clean_str in ("PASS", "FAIL"):
                # Untrusted raw string -> cannot become trusted evidence
                return "NOT_EVALUATED"

            # Check if string is a storage key / regression_result_id
            resolved_evidence = self.storage.get(regression_result)
            if resolved_evidence is None:
                resolved_evidence = self.storage.get(f"reg-{regression_result}")
            if resolved_evidence is not None:
                regression_result = resolved_evidence
            else:
                return "NOT_EVALUATED"

        # 2. Accept genuine RegressionResult contract
        if isinstance(regression_result, RegressionResult):
            # Validate evidence belongs to relevant after_run
            if expected_run_id and regression_result.run_id != expected_run_id:
                return "NOT_EVALUATED"
            status = str(regression_result.status).strip().upper()
            return status if status in ("PASS", "FAIL") else "NOT_EVALUATED"

        # 3. Accept stored dict representation of RegressionResult
        if isinstance(regression_result, dict):
            status = regression_result.get("status")
            rec_run_id = regression_result.get("run_id")
            if not status or str(status).strip().upper() not in ("PASS", "FAIL"):
                return "NOT_EVALUATED"
            if expected_run_id and rec_run_id and str(rec_run_id) != expected_run_id:
                return "NOT_EVALUATED"
            if "test_id" in regression_result or "measured_evidence" in regression_result or rec_run_id:
                return str(status).strip().upper()
            return "NOT_EVALUATED"

        # 4. Check if after_run has embedded regression evidence
        if after_run is not None:
            embedded = getattr(after_run, "regression_result", None)
            if embedded is None and isinstance(after_run, dict):
                embedded = after_run.get("regression_result")
            if embedded is not None and not (isinstance(embedded, str) and embedded.strip().upper() in ("PASS", "FAIL")):
                return self.evaluate_regression_result(embedded, after_run_id=expected_run_id)

        return "NOT_EVALUATED"

    def evaluate(
        self,
        before_run: Any,
        after_run: Any,
        expected_behavior: Optional[Union[ExpectedBehavior, dict[str, Any], str]] = None,
        expected_prompt: Optional[str] = None,
        expected_failure_mode: Optional[str] = None,
        regression_result: Optional[Any] = None,
    ) -> EvaluationPair:
        """Perform before/after evaluation and construct an EvaluationPair domain contract.

        Args:
            before_run: Run representation (or ID) for failing execution.
            after_run: Run representation (or ID) for candidate fixed execution.
            expected_behavior: Statement or structured assertions of expected behavior.
            expected_prompt: Optional expected prompt to enforce pairing.
            expected_failure_mode: Optional expected failure mode (e.g. 'timeout').
            regression_result: Optional regression test evidence.

        Returns:
            Populated EvaluationPair contract.
        """
        resolved_before = self.resolve_run(before_run)
        resolved_after = self.resolve_run(after_run)

        # 1. Validate pairing semantics
        before_id, after_id = self.validate_pair(
            resolved_before,
            resolved_after,
            expected_prompt=expected_prompt,
            expected_failure_mode=expected_failure_mode,
        )

        # 2. Extract metrics from actual runs (zero fabrication)
        before_metrics = self.extract_metrics(resolved_before)
        after_metrics = self.extract_metrics(resolved_after)

        # 3. Derive task result and regression result
        task_res = self.evaluate_task_result(resolved_after, expected_behavior=expected_behavior)
        reg_res = self.evaluate_regression_result(
            regression_result,
            after_run=resolved_after,
            after_run_id=after_id,
        )

        # 4. Construct EvaluationPair contract with unique evaluation_id
        eval_pair = EvaluationPair(
            before_run_id=before_id,
            after_run_id=after_id,
            before_metrics=before_metrics,
            after_metrics=after_metrics,
            task_result=task_res,
            regression_result=reg_res,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
        )

        # Persist to storage using unique evaluation_id to prevent overwriting
        self.storage.save(eval_pair.evaluation_id, eval_pair)

        return eval_pair


def evaluate_pair(
    before_run: Any,
    after_run: Any,
    expected_behavior: Optional[Union[ExpectedBehavior, dict[str, Any], str]] = None,
    expected_prompt: Optional[str] = None,
    expected_failure_mode: Optional[str] = None,
    regression_result: Optional[Any] = None,
    storage: Optional[Storage] = None,
) -> EvaluationPair:
    """Convenience function to evaluate a before/after run pair."""
    evaluator = BeforeAfterEvaluator(storage=storage)
    return evaluator.evaluate(
        before_run=before_run,
        after_run=after_run,
        expected_behavior=expected_behavior,
        expected_prompt=expected_prompt,
        expected_failure_mode=expected_failure_mode,
        regression_result=regression_result,
    )


def execute_evaluation(
    payload: dict[str, Any],
    storage: Optional[Storage] = None,
) -> dict[str, Any]:
    """Callable service interface for Member 4 POST /evaluations API Gateway / Lambda.

    Args:
        payload: Request payload containing run references and expected behavior.
        storage: Optional Storage instance.

    Returns:
        JSON-serializable evaluation report with measured evidence, deltas, and outcomes.
    """
    evaluator = BeforeAfterEvaluator(storage=storage)

    try:
        before_ref = payload.get("before_run") or payload.get("before_run_id")
        after_ref = payload.get("after_run") or payload.get("after_run_id")

        if not before_ref or not after_ref:
            return {
                "status": "ERROR",
                "error": "Both 'before_run' (or 'before_run_id') and 'after_run' (or 'after_run_id') are required.",
            }

        raw_eb = payload.get("expected_behavior")
        eb = ExpectedBehavior.from_val(raw_eb)
        if "expected_outcome" in payload and eb.expected_outcome is None:
            eb.expected_outcome = payload.get("expected_outcome")
        if "fallback_required" in payload and eb.fallback_required is None:
            eb.fallback_required = payload.get("fallback_required")
        if "max_retries" in payload and eb.max_retries is None:
            eb.max_retries = payload.get("max_retries")
        if "forbidden_failures" in payload and not eb.forbidden_failures:
            eb.forbidden_failures = list(payload.get("forbidden_failures") or [])

        expected_prompt = payload.get("prompt")
        expected_failure_mode = payload.get("failure_mode")
        regression_res = payload.get("regression_result_id") or payload.get("regression_result")

        eval_pair = evaluator.evaluate(
            before_run=before_ref,
            after_run=after_ref,
            expected_behavior=eb,
            expected_prompt=expected_prompt,
            expected_failure_mode=expected_failure_mode,
            regression_result=regression_res,
        )

        deltas = evaluator.compute_deltas(eval_pair.before_metrics, eval_pair.after_metrics)

        # Scenario description for reporting
        scenario_eb: Any = eb.description
        if scenario_eb is None:
            scenario_eb = raw_eb if isinstance(raw_eb, str) else asdict(eb)

        # Construct JSON-serializable output for Member 4
        result: dict[str, Any] = {
            "status": "EVALUATED",
            "evaluation_id": eval_pair.evaluation_id,
            "before_run_id": eval_pair.before_run_id,
            "after_run_id": eval_pair.after_run_id,
            "scenario": {
                "prompt": expected_prompt or _extract_prompt(evaluator.resolve_run(before_ref)),
                "failure_mode": expected_failure_mode or _extract_failure_mode(evaluator.resolve_run(before_ref)),
                "expected_behavior": scenario_eb,
            },
            "metrics": {
                "before": eval_pair.before_metrics,
                "after": eval_pair.after_metrics,
                "deltas": deltas,
            },
            "task_result": eval_pair.task_result,
            "regression_result": eval_pair.regression_result,
            "evaluated_at": eval_pair.evaluated_at,
        }

        # Verify JSON serializability before returning
        json.dumps(result)
        return result

    except Exception as exc:
        return {
            "status": "ERROR",
            "error": str(exc),
        }
