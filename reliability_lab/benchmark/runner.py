"""Member 3 Repeatability Benchmark Runner for AgentLens.

Executes controlled scenarios across repeated iterations to mathematically prove
deterministic execution and reproducibility without metric fabrication.
Does not invent precision, recall, F1, or percentage improvement unless actually
measured from a defined benchmark run matrix.
"""

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Optional
import uuid

from reliability_lab.chaos.service import ChaosService
from reliability_lab.contracts import FailureMode, ReplayRecord, Storage
from reliability_lab.fixtures.replay_fixtures import CANONICAL_TIMEOUT_FIXTURE, ControlledScenarioFixture
from reliability_lab.mocks.mock_storage import MockStorage
from reliability_lab.replay.engine import ReplayEngine, ReplayExecutionResult


@dataclass
class BenchmarkIterationResult:
    """Captured metrics and outcomes from a single benchmark iteration."""
    iteration: int
    run_id: str
    outcome: str
    tool_calls_count: int
    errors_count: int
    latency_ms: int
    tokens: int
    errors: list[str] = field(default_factory=list)


@dataclass
class RepeatabilityBenchmarkReport:
    """Aggregated empirical repeatability proof across repeated iterations."""
    scenario_name: str
    failure_mode: str
    iterations: int
    agent_version: str
    outcomes: list[str]
    deterministic_outcome_rate: float
    tool_calls_counts: list[int]
    tool_calls_consistent: bool
    unique_run_ids: bool
    pass_rate: float
    pass_rate_pct: float
    is_deterministic: bool
    runs: list[BenchmarkIterationResult] = field(default_factory=list)
    measured_improvement_pct: Optional[float] = None
    benchmarked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RepeatabilityBenchmark:
    """Executes repeated scenario runs to establish deterministic baseline evidence."""

    def __init__(
        self,
        storage: Optional[Storage] = None,
        chaos_service: Optional[ChaosService] = None,
    ) -> None:
        self.storage = storage or MockStorage()
        self.chaos_service = chaos_service or ChaosService()
        self.replay_engine = ReplayEngine(
            storage=self.storage,
            chaos_service=self.chaos_service,
        )

    def _resolve_record(self, target: Any) -> ReplayRecord:
        """Resolve a ControlledScenarioFixture or ReplayRecord to an executable ReplayRecord."""
        if isinstance(target, ReplayRecord):
            return target
        if isinstance(target, ControlledScenarioFixture):
            return ReplayRecord(
                run_id=f"run-bench-{uuid.uuid4().hex[:8]}",
                prompt=target.prompt,
                agent_version=target.agent_version,
                prompt_version=target.prompt_version,
                failure_mode=target.failure_mode,
                tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
                mocked_responses=target.mocked_responses,
                expected_behavior=target.expected_behavior,
                original_incident_id=f"inc-bench-{target.name}",
            )
        # Default to canonical timeout
        return ReplayRecord(
            run_id=f"run-bench-{uuid.uuid4().hex[:8]}",
            prompt=CANONICAL_TIMEOUT_FIXTURE.prompt,
            agent_version=CANONICAL_TIMEOUT_FIXTURE.agent_version,
            prompt_version=CANONICAL_TIMEOUT_FIXTURE.prompt_version,
            failure_mode=CANONICAL_TIMEOUT_FIXTURE.failure_mode,
            tool_calls=[{"tool": "get_order", "args": {"order_id": "8271"}}],
            mocked_responses=CANONICAL_TIMEOUT_FIXTURE.mocked_responses,
            expected_behavior=CANONICAL_TIMEOUT_FIXTURE.expected_behavior,
            original_incident_id="inc-bench-canonical",
        )

    def run_scenario(
        self,
        scenario: Optional[Any] = None,
        iterations: int = 10,
        agent_version: str = "v1.0.1-fixed",
    ) -> RepeatabilityBenchmarkReport:
        """Execute a controlled scenario N times and calculate empirical determinism.

        Args:
            scenario: ControlledScenarioFixture, ReplayRecord, or None (canonical timeout).
            iterations: Number of consecutive executions (default 10).
            agent_version: Agent version under test.

        Returns:
            Populated RepeatabilityBenchmarkReport.
        """
        if iterations < 1:
            raise ValueError(f"Iterations must be >= 1, got {iterations}")

        record = self._resolve_record(scenario)
        scen_name = getattr(scenario, "name", "canonical_order_timeout") if scenario else "canonical_order_timeout"
        fm_val = record.failure_mode.value if hasattr(record.failure_mode, "value") else str(record.failure_mode)

        iteration_results: list[BenchmarkIterationResult] = []

        for i in range(1, iterations + 1):
            replay_res: ReplayExecutionResult = self.replay_engine.replay(
                record,
                agent_version_override=agent_version,
            )
            tel = replay_res.telemetry
            raw_tc = getattr(tel, "tool_calls", 0)
            tc_count = len(raw_tc) if isinstance(raw_tc, list) else int(raw_tc or 0)
            outcome = str(getattr(tel, "outcome", "UNKNOWN")).upper()
            errors = list(getattr(tel, "errors", []))

            iteration_results.append(
                BenchmarkIterationResult(
                    iteration=i,
                    run_id=replay_res.replay_run_id,
                    outcome=outcome,
                    tool_calls_count=tc_count,
                    errors_count=len(errors),
                    latency_ms=int(getattr(tel, "latency_ms", 0) or 0),
                    tokens=int(getattr(tel, "tokens", 0) or 0),
                    errors=errors,
                )
            )

        # Compute empirical statistics strictly from actual run measurements
        outcomes = [r.outcome for r in iteration_results]
        tool_calls_counts = [r.tool_calls_count for r in iteration_results]
        run_ids = [r.run_id for r in iteration_results]

        # Deterministic outcome consistency
        outcome_counter = Counter(outcomes)
        dominant_outcome, dominant_count = outcome_counter.most_common(1)[0]
        deterministic_outcome_rate = round(dominant_count / float(iterations), 4)

        # Tool calls consistency (variance == 0)
        tool_calls_consistent = len(set(tool_calls_counts)) == 1

        # Unique run IDs (no ID reuse)
        unique_run_ids = len(set(run_ids)) == iterations

        # Pass rate based on valid graceful handling (SUCCESS or FALLBACK)
        passed_count = sum(1 for r in iteration_results if r.outcome in ("SUCCESS", "FALLBACK"))
        pass_rate = round(passed_count / float(iterations), 4)
        pass_rate_pct = round(pass_rate * 100.0, 2)

        is_deterministic = (
            deterministic_outcome_rate == 1.0
            and tool_calls_consistent
            and unique_run_ids
        )

        return RepeatabilityBenchmarkReport(
            scenario_name=scen_name,
            failure_mode=fm_val,
            iterations=iterations,
            agent_version=agent_version,
            outcomes=outcomes,
            deterministic_outcome_rate=deterministic_outcome_rate,
            tool_calls_counts=tool_calls_counts,
            tool_calls_consistent=tool_calls_consistent,
            unique_run_ids=unique_run_ids,
            pass_rate=pass_rate,
            pass_rate_pct=pass_rate_pct,
            is_deterministic=is_deterministic,
            runs=iteration_results,
        )

    def run_comparative_benchmark(
        self,
        scenario: Optional[Any] = None,
        iterations: int = 10,
    ) -> dict[str, Any]:
        """Execute comparative benchmark between failing and fixed agents.

        Measures actual baseline failure rate vs fixed pass rate.
        Does NOT invent precision/recall/F1. Only outputs percentage improvement
        if derived directly from measured test outcomes.
        """
        baseline_report = self.run_scenario(
            scenario=scenario,
            iterations=iterations,
            agent_version="v1.0.0-failing",
        )
        fixed_report = self.run_scenario(
            scenario=scenario,
            iterations=iterations,
            agent_version="v1.0.1-fixed",
        )

        # Empirical improvement derived from measured pass rates
        measured_improvement = round(fixed_report.pass_rate_pct - baseline_report.pass_rate_pct, 2)
        fixed_report.measured_improvement_pct = measured_improvement

        return {
            "scenario": baseline_report.scenario_name,
            "failure_mode": baseline_report.failure_mode,
            "iterations_per_version": iterations,
            "baseline": {
                "agent_version": baseline_report.agent_version,
                "pass_rate_pct": baseline_report.pass_rate_pct,
                "is_deterministic": baseline_report.is_deterministic,
                "dominant_outcome": baseline_report.outcomes[0] if baseline_report.outcomes else None,
                "tool_calls_per_run": baseline_report.tool_calls_counts[0] if baseline_report.tool_calls_consistent else None,
            },
            "fixed": {
                "agent_version": fixed_report.agent_version,
                "pass_rate_pct": fixed_report.pass_rate_pct,
                "is_deterministic": fixed_report.is_deterministic,
                "dominant_outcome": fixed_report.outcomes[0] if fixed_report.outcomes else None,
                "tool_calls_per_run": fixed_report.tool_calls_counts[0] if fixed_report.tool_calls_consistent else None,
            },
            "measured_improvement_pct": measured_improvement,
            "deterministic_repeatability_proven": baseline_report.is_deterministic and fixed_report.is_deterministic,
        }


def serialize_benchmark_report(report: RepeatabilityBenchmarkReport) -> dict[str, Any]:
    """Convert RepeatabilityBenchmarkReport into a JSON-serializable dictionary."""
    runs_serialized = [
        {
            "iteration": r.iteration,
            "run_id": r.run_id,
            "outcome": r.outcome,
            "tool_calls_count": r.tool_calls_count,
            "errors_count": r.errors_count,
            "latency_ms": r.latency_ms,
            "tokens": r.tokens,
            "errors": r.errors,
        }
        for r in report.runs
    ]

    result = {
        "scenario_name": report.scenario_name,
        "failure_mode": report.failure_mode,
        "iterations": report.iterations,
        "agent_version": report.agent_version,
        "outcomes": report.outcomes,
        "deterministic_outcome_rate": report.deterministic_outcome_rate,
        "tool_calls_counts": report.tool_calls_counts,
        "tool_calls_consistent": report.tool_calls_consistent,
        "unique_run_ids": report.unique_run_ids,
        "pass_rate": report.pass_rate,
        "pass_rate_pct": report.pass_rate_pct,
        "is_deterministic": report.is_deterministic,
        "measured_improvement_pct": report.measured_improvement_pct,
        "benchmarked_at": report.benchmarked_at,
        "runs": runs_serialized,
    }

    json.dumps(result)
    return result
