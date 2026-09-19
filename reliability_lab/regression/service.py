"""Member 3 Regression Library Service and Execution Runner.

Converts discovered reliability failures into reusable engineering quality gates.
Provides test creation, listing, execution (single & batch), deterministic PASS/FAIL evaluation,
execution history tracking, and transparent pass-rate scorecards.
"""

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
from typing import Any, Optional, Union
import uuid

from reliability_lab.adapters.member1_adapter import MockMember1Agent
from reliability_lab.chaos.service import ChaosService
from reliability_lab.contracts import (
    ChaosConfig,
    ExpectedBehavior,
    FailureMode,
    RegressionResult,
    RegressionTest,
    ReplayRecord,
    Storage,
)
from reliability_lab.evaluation.evaluator import BeforeAfterEvaluator
from reliability_lab.fixtures.replay_fixtures import (
    CANONICAL_TIMEOUT_FIXTURE,
    CONTROLLED_GROUNDING_FIXTURE,
    EMPTY_RESULT_FIXTURE,
    RATE_LIMIT_FIXTURE,
    SLOW_RESPONSE_FIXTURE,
    WRONG_TOOL_FIXTURE,
)
from reliability_lab.mocks.mock_storage import MockStorage
from reliability_lab.replay.engine import ReplayEngine, ReplayExecutionResult


class RegressionRunner:
    """Executes controlled scenarios for RegressionTests and captures measured evidence."""

    def __init__(
        self,
        storage: Optional[Storage] = None,
        replay_engine: Optional[ReplayEngine] = None,
        chaos_service: Optional[ChaosService] = None,
    ) -> None:
        self.storage = storage or MockStorage()
        self.chaos_service = chaos_service or ChaosService()
        self.replay_engine = replay_engine or ReplayEngine(
            storage=self.storage,
            chaos_service=self.chaos_service,
        )
        self.evaluator = BeforeAfterEvaluator(storage=self.storage)

    def _resolve_scenario_record(self, test: RegressionTest) -> ReplayRecord:
        """Resolve or construct the ReplayRecord scenario for a RegressionTest."""
        # 1. Direct replay_record_id reference
        if test.replay_record_id:
            rec = self.storage.get(test.replay_record_id)
            if rec is None:
                rec = self.storage.get(f"replay-{test.replay_record_id}")
            if rec is not None and isinstance(rec, ReplayRecord):
                return rec

        # 2. Look up by test_id
        rec_by_test = self.storage.get(test.test_id) or self.storage.get(f"replay-{test.test_id}")
        if rec_by_test is not None and isinstance(rec_by_test, ReplayRecord):
            return rec_by_test

        # 3. Look up by scenario text if it acts as a key
        rec_by_scen = self.storage.get(test.scenario) or self.storage.get(f"replay-{test.scenario}")
        if rec_by_scen is not None and isinstance(rec_by_scen, ReplayRecord):
            return rec_by_scen

        # 4. Canonical scenario default construction
        scen_lower = f"{test.scenario} {test.expected_behavior}".lower()
        if "rate_limit" in scen_lower or "429" in scen_lower:
            mode = FailureMode.RATE_LIMIT
            mocked = RATE_LIMIT_FIXTURE.mocked_responses
        elif "empty" in scen_lower:
            mode = FailureMode.EMPTY_RESULT
            mocked = EMPTY_RESULT_FIXTURE.mocked_responses
        elif "slow" in scen_lower:
            mode = FailureMode.SLOW_RESPONSE
            mocked = SLOW_RESPONSE_FIXTURE.mocked_responses
        elif "wrong_tool" in scen_lower:
            mode = FailureMode.WRONG_TOOL
            mocked = WRONG_TOOL_FIXTURE.mocked_responses
        elif "grounding" in scen_lower:
            mode = FailureMode.NORMAL
            mocked = CONTROLLED_GROUNDING_FIXTURE.mocked_responses
        elif "timeout" in scen_lower:
            mode = FailureMode.TIMEOUT
            mocked = CANONICAL_TIMEOUT_FIXTURE.mocked_responses
        else:
            mode = FailureMode.NORMAL
            mocked = {}

        # Build clean ReplayRecord from canonical specification
        record = ReplayRecord(
            run_id=f"run-scenario-{uuid.uuid4().hex[:8]}",
            prompt=CANONICAL_TIMEOUT_FIXTURE.prompt,
            agent_version="v1.0.0-failing",
            prompt_version="p1.0",
            failure_mode=mode,
            tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
            mocked_responses=mocked,
            expected_behavior=test.expected_behavior,
            original_incident_id=f"inc-reg-{test.test_id}",
        )
        # Cache in storage for subsequent replays
        self.storage.save(record.run_id, record)
        self.storage.save(f"replay-{record.run_id}", record)
        test.replay_record_id = record.run_id
        return record

    def run(
        self,
        test: RegressionTest,
        agent_version: Optional[str] = None,
        agent: Optional[Any] = None,
    ) -> RegressionResult:
        """Execute a regression test scenario and append the measured result to history.

        Args:
            test: The RegressionTest to run.
            agent_version: Optional agent version override (defaults to fixed agent).
            agent: Optional agent instance for execution.

        Returns:
            Populated RegressionResult contract.
        """
        record = self._resolve_scenario_record(test)
        target_version = agent_version or "v1.0.1-fixed"

        # Execute through controlled replay engine or direct agent invocation
        if agent is not None:
            fresh_run_id = f"run-replay-{uuid.uuid4().hex[:8]}"
            proxy = self.chaos_service.get_proxy("get_order")
            mode_val = record.failure_mode.value if hasattr(record.failure_mode, "value") else str(record.failure_mode).lower()
            try:
                mode_enum = FailureMode(mode_val)
            except ValueError:
                mode_enum = FailureMode.NORMAL

            proxy.set_config(
                ChaosConfig(
                    failure_mode=mode_enum,
                    target_tool="get_order",
                    error_message=f"Controlled chaos {mode_val} on tool 'get_order'.",
                )
            )
            try:
                telemetry = agent.run(request=record.prompt, run_id=fresh_run_id)
            finally:
                proxy.reset()
        else:
            replay_res: ReplayExecutionResult = self.replay_engine.replay(
                record,
                agent_version_override=target_version,
            )
            telemetry = replay_res.telemetry
            fresh_run_id = replay_res.replay_run_id

        # Measure evidence honestly from actual execution
        raw_tc = getattr(telemetry, "tool_calls", 0)
        tool_calls_count = len(raw_tc) if isinstance(raw_tc, list) else int(raw_tc or 0)
        measured_evidence = {
            "tool_calls": tool_calls_count,
            "tokens": getattr(telemetry, "tokens", None),
            "latency_ms": getattr(telemetry, "latency_ms", None),
            "outcome": getattr(telemetry, "outcome", None),
            "errors": getattr(telemetry, "errors", []),
            "response": getattr(telemetry, "response", None),
        }

        # Deterministic PASS/FAIL evaluation against defined expected behavior
        status = self.evaluator.evaluate_task_result(
            telemetry,
            expected_behavior=test.expected_behavior,
        )

        result = RegressionResult(
            test_id=test.test_id,
            run_id=fresh_run_id,
            status=status,
            measured_evidence=measured_evidence,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Update test state: latest_result and append to history
        test.latest_result = result
        test.history.append(result)

        # Persist updated test and result
        self.storage.save(test.test_id, test)
        self.storage.save(f"reg-test-{test.test_id}", test)
        self.storage.save(f"reg-res-{fresh_run_id}", result)

        return result


class RegressionLibrary:
    """Core domain service for managing the Member 3 Regression Test Quality Gates."""

    def __init__(
        self,
        storage: Optional[Storage] = None,
        chaos_service: Optional[ChaosService] = None,
        replay_engine: Optional[ReplayEngine] = None,
    ) -> None:
        self.storage = storage or MockStorage()
        self.chaos_service = chaos_service or ChaosService()
        self.replay_engine = replay_engine or ReplayEngine(
            storage=self.storage,
            chaos_service=self.chaos_service,
        )
        self.runner = RegressionRunner(
            storage=self.storage,
            replay_engine=self.replay_engine,
            chaos_service=self.chaos_service,
        )

    def save_test(
        self,
        test_or_spec: Union[RegressionTest, dict[str, Any]],
        replay_record: Optional[ReplayRecord] = None,
    ) -> RegressionTest:
        """Persist a new or updated RegressionTest.

        Args:
            test_or_spec: RegressionTest dataclass or specification dictionary.
            replay_record: Optional ReplayRecord to link with this regression test.

        Returns:
            The stored RegressionTest instance.
        """
        if isinstance(test_or_spec, RegressionTest):
            test = test_or_spec
        elif isinstance(test_or_spec, dict):
            test_id = str(test_or_spec.get("test_id") or f"reg-{uuid.uuid4().hex[:8]}")
            scenario = str(test_or_spec.get("scenario") or "Controlled failure scenario")
            raw_eb = test_or_spec.get("expected_behavior", "Agent must handle controlled chaos gracefully")
            expected_behavior = ExpectedBehavior.from_val(raw_eb) if isinstance(raw_eb, (dict, ExpectedBehavior)) else str(raw_eb)
            replay_id = test_or_spec.get("replay_record_id")

            test = RegressionTest(
                test_id=test_id,
                scenario=scenario,
                expected_behavior=expected_behavior,
                replay_record_id=replay_id,
            )
        else:
            raise TypeError(f"Expected RegressionTest or dict, got {type(test_or_spec).__name__}")

        if replay_record is not None:
            self.storage.save(replay_record.run_id, replay_record)
            self.storage.save(f"replay-{replay_record.run_id}", replay_record)
            test.replay_record_id = replay_record.run_id

        # Persist test under test_id and prefixed key
        self.storage.save(test.test_id, test)
        self.storage.save(f"reg-test-{test.test_id}", test)
        return test

    def get_test(self, test_id: str) -> Optional[RegressionTest]:
        """Retrieve a RegressionTest by test_id."""
        item = self.storage.get(test_id)
        if item is None:
            item = self.storage.get(f"reg-test-{test_id}")
        return item if isinstance(item, RegressionTest) else None

    def list_tests(self) -> list[RegressionTest]:
        """List all unique registered RegressionTests."""
        unique_tests: dict[str, RegressionTest] = {}
        for item in self.storage.list():
            if isinstance(item, RegressionTest):
                unique_tests[item.test_id] = item
        return list(unique_tests.values())

    def run_test(
        self,
        test_id: str,
        agent_version: Optional[str] = None,
        agent: Optional[Any] = None,
    ) -> RegressionResult:
        """Execute a single regression test and update its history.

        Args:
            test_id: The identifier of the test to run.
            agent_version: Optional version of the agent to test.
            agent: Optional agent instance to test against.

        Returns:
            The resulting RegressionResult.

        Raises:
            KeyError: If test_id is not found in storage.
        """
        test = self.get_test(test_id)
        if test is None:
            raise KeyError(f"RegressionTest with ID '{test_id}' not found.")
        return self.runner.run(test, agent_version=agent_version, agent=agent)

    def run_all(
        self,
        agent_version: Optional[str] = None,
        agent: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Execute all registered regression tests sequentially.

        Args:
            agent_version: Optional version of the agent to test.
            agent: Optional agent instance to test against.

        Returns:
            Dictionary containing execution results and aggregate scorecard.
        """
        tests = self.list_tests()
        results: list[RegressionResult] = []
        for test in tests:
            res = self.runner.run(test, agent_version=agent_version, agent=agent)
            results.append(res)

        scorecard = self.get_scorecard(results)
        return {
            "status": "COMPLETED",
            "total_executed": len(results),
            "results": results,
            "scorecard": scorecard,
        }

    def _determine_test_category(self, test: Optional[RegressionTest]) -> str:
        """Infer or retrieve category for a regression test."""
        if test is None:
            return "general"
        if hasattr(test, "category") and getattr(test, "category"):
            return str(getattr(test, "category")).lower()
        if test.replay_record_id:
            rec = self.storage.get(test.replay_record_id) or self.storage.get(f"replay-{test.replay_record_id}")
            if rec and hasattr(rec, "failure_mode"):
                fm = getattr(rec, "failure_mode")
                return fm.value if hasattr(fm, "value") else str(fm).lower()
        scen = (test.scenario or "").lower()
        for mode in ("timeout", "rate_limit", "empty_result", "slow_response", "wrong_tool", "grounding", "hallucination", "normal"):
            if mode in scen:
                return "grounding" if mode == "hallucination" else mode
        return "general"

    def get_scorecard(self, results: Optional[list[RegressionResult]] = None) -> dict[str, Any]:
        """Compute transparent mathematical counts and pass rate.

        Strict Scorecard Rule:
        Allowed: 'X / Y tests passed', 'Z% defined test pass rate', category breakdown.
        Forbidden: Subjective AI reliability score claims (e.g. '80% reliable agent').
        """
        tests = self.list_tests()
        test_by_id = {t.test_id: t for t in tests}

        if results is None:
            results = [t.latest_result for t in tests if t.latest_result is not None]

        total = len(results)
        passed = sum(1 for r in results if r.status == "PASS")
        failed = sum(1 for r in results if r.status == "FAIL")
        pass_rate = round(passed / total, 4) if total > 0 else 0.0
        pass_rate_pct = round(pass_rate * 100.0, 2)

        # Transparent category breakdown
        cat_counts: dict[str, dict[str, Any]] = {}
        for r in results:
            t = test_by_id.get(r.test_id)
            cat = self._determine_test_category(t)
            if cat not in cat_counts:
                cat_counts[cat] = {"total": 0, "passed": 0, "failed": 0, "pass_rate_pct": 0.0}
            cat_counts[cat]["total"] += 1
            if r.status == "PASS":
                cat_counts[cat]["passed"] += 1
            elif r.status == "FAIL":
                cat_counts[cat]["failed"] += 1

        for c_data in cat_counts.values():
            c_tot = c_data["total"]
            c_pass = c_data["passed"]
            c_data["pass_rate_pct"] = round((c_pass / c_tot) * 100.0, 2) if c_tot > 0 else 0.0

        return {
            "total": total,
            "total_tests": total,
            "passed": passed,
            "tests_passed": passed,
            "failed": failed,
            "tests_failed": failed,
            "pass_rate": pass_rate,
            "pass_rate_pct": pass_rate_pct,
            "categories": cat_counts,
            "category_results": cat_counts,
            "summary": f"{passed} / {total} tests passed ({pass_rate_pct}% defined test pass rate)",
        }


# ==============================================================================
# MEMBER 4 SERVICE HANDLERS (GET /tests, POST /tests, POST /tests/run)
# ==============================================================================

def _serialize_regression_result(result: Optional[RegressionResult]) -> Optional[dict[str, Any]]:
    """Helper to convert RegressionResult to a JSON-serializable dict."""
    if result is None:
        return None
    return {
        "test_id": result.test_id,
        "run_id": result.run_id,
        "status": result.status,
        "measured_evidence": result.measured_evidence,
        "timestamp": result.timestamp,
    }


def _serialize_regression_test(test: RegressionTest) -> dict[str, Any]:
    """Helper to convert RegressionTest to a JSON-serializable dict."""
    eb_val = test.expected_behavior
    if is_dataclass(eb_val):
        eb_serializable = asdict(eb_val)
    elif isinstance(eb_val, ExpectedBehavior):
        eb_serializable = {
            "description": eb_val.description,
            "expected_outcome": eb_val.expected_outcome,
            "fallback_required": eb_val.fallback_required,
            "max_retries": eb_val.max_retries,
            "forbidden_failures": eb_val.forbidden_failures,
        }
    else:
        eb_serializable = str(eb_val)

    return {
        "test_id": test.test_id,
        "scenario": test.scenario,
        "expected_behavior": eb_serializable,
        "replay_record_id": test.replay_record_id,
        "latest_result": _serialize_regression_result(test.latest_result),
        "history": [_serialize_regression_result(r) for r in test.history],
        "history_count": len(test.history),
        "created_at": test.created_at,
    }



def list_tests_service(storage: Optional[Storage] = None) -> dict[str, Any]:
    """Service handler for Member 4 GET /tests."""
    library = RegressionLibrary(storage=storage)
    try:
        tests = library.list_tests()
        result = {
            "status": "SUCCESS",
            "count": len(tests),
            "tests": [_serialize_regression_test(t) for t in tests],
        }
        json.dumps(result)
        return result
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}


def create_test_service(payload: dict[str, Any], storage: Optional[Storage] = None) -> dict[str, Any]:
    """Service handler for Member 4 POST /tests."""
    library = RegressionLibrary(storage=storage)
    try:
        if not payload.get("test_id") and not payload.get("scenario"):
            return {
                "status": "ERROR",
                "error": "At least 'test_id' or 'scenario' is required in payload.",
            }

        test = library.save_test(payload)
        result = {
            "status": "CREATED",
            "test": _serialize_regression_test(test),
        }
        json.dumps(result)
        return result
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}


def run_tests_service(payload: dict[str, Any], storage: Optional[Storage] = None) -> dict[str, Any]:
    """Service handler for Member 4 POST /tests/run."""
    library = RegressionLibrary(storage=storage)
    try:
        test_id = payload.get("test_id")
        run_all = payload.get("run_all", False) or (test_id is None)
        agent_version = payload.get("agent_version")

        if not run_all and test_id:
            # Single test execution
            res = library.run_test(test_id, agent_version=agent_version)
            scorecard = library.get_scorecard([res])
            result = {
                "status": "COMPLETED",
                "mode": "SINGLE",
                "results": [_serialize_regression_result(res)],
                "scorecard": scorecard,
            }
        else:
            # Batch execution
            batch_res = library.run_all(agent_version=agent_version)
            result = {
                "status": "COMPLETED",
                "mode": "ALL",
                "total_executed": batch_res["total_executed"],
                "results": [_serialize_regression_result(r) for r in batch_res["results"]],
                "scorecard": batch_res["scorecard"],
            }

        json.dumps(result)
        return result
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}
