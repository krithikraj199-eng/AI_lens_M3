"""Controlled Replay Engine for Member 3 Reliability Lab.

Provides deterministic reconstruction and execution of stored test scenarios
through the normal, shared execution path, ensuring fresh run IDs,
measured execution evidence, and zero metric fabrication.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from reliability_lab.adapters.member1_adapter import MockMember1Agent
from reliability_lab.adapters.telemetry_adapter import AgentExecutionResult
from reliability_lab.chaos.service import ChaosService
from reliability_lab.contracts import ChaosConfig, FailureMode, ReplayRecord
from reliability_lab.mocks.mock_storage import MockStorage


@dataclass
class ReplayExecutionResult:
    """Captured execution outcome and evidence from a controlled scenario replay."""
    replay_run_id: str
    original_run_id: str
    original_incident_id: Optional[str]
    failure_mode: str
    agent_version: str
    prompt_version: str
    telemetry: AgentExecutionResult
    replayed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ReplayEngine:
    """Executes controlled scenario replays from stored ReplayRecords."""

    def __init__(
        self,
        storage: Optional[MockStorage] = None,
        chaos_service: Optional[ChaosService] = None,
    ) -> None:
        """Initialize ReplayEngine with storage and chaos management.

        Args:
            storage: MockStorage instance. If None, creates a default instance.
            chaos_service: ChaosService instance. If None, creates a default instance.
        """
        self.storage = storage if storage is not None else MockStorage()
        self.chaos_service = chaos_service if chaos_service is not None else ChaosService()

    def load_record(self, record_or_id: str | ReplayRecord) -> ReplayRecord:
        """Fetch ReplayRecord from storage or return if already a ReplayRecord.

        Args:
            record_or_id: ReplayRecord instance or string ID.

        Returns:
            ReplayRecord instance.

        Raises:
            KeyError: If record cannot be found in storage.
        """
        if isinstance(record_or_id, ReplayRecord):
            return record_or_id

        # Look up in storage by id or with prefix
        record = self.storage.get(record_or_id)
        if record is None:
            record = self.storage.get(f"replay-{record_or_id}")

        if record is None or not isinstance(record, ReplayRecord):
            raise KeyError(f"ReplayRecord with id '{record_or_id}' not found.")

        return record

    def replay(
        self,
        record_or_id: str | ReplayRecord,
        agent_version_override: Optional[str] = None,
    ) -> ReplayExecutionResult:
        """Execute a controlled scenario replay through the shared execution path.

        1. Loads the stored scenario record.
        2. Generates a fresh unique run_id (never reuses original).
        3. Restores ChaosConfig and mock responses on tool proxy.
        4. Instantiates agent with restored version context.
        5. Executes through the normal tool/agent path, measuring all telemetry live.
        6. Preserves linkage to original run_id and original_incident_id.
        7. Persists replay result to storage.
        8. Safely resets chaos state.

        Args:
            record_or_id: ReplayRecord or record ID string.
            agent_version_override: Optional agent version to test (e.g. fixed version).

        Returns:
            Populated ReplayExecutionResult with live measured telemetry.
        """
        record = self.load_record(record_or_id)

        # 1. Generate guaranteed fresh run_id
        replay_run_id = f"run-replay-{uuid.uuid4().hex[:8]}"

        # 2. Resolve FailureMode
        raw_mode = record.failure_mode.value if isinstance(record.failure_mode, FailureMode) else str(record.failure_mode).lower().strip()
        try:
            mode_enum = FailureMode(raw_mode)
        except ValueError:
            mode_enum = FailureMode.NORMAL

        # 3. Extract mocked response specs
        mock_order: dict[str, Any] = {}
        if isinstance(record.mocked_responses, dict):
            order_data = record.mocked_responses.get("get_order", {})
            if isinstance(order_data, dict):
                mock_order = order_data

        error_message = mock_order.get("error")
        status_code = mock_order.get("status_code", 429 if mode_enum == FailureMode.RATE_LIMIT else 200)
        delay_ms = mock_order.get("delay_ms", 0)

        if not error_message:
            if mode_enum == FailureMode.TIMEOUT:
                error_message = "Controlled chaos timeout on tool 'get_order'."
            elif mode_enum == FailureMode.RATE_LIMIT:
                error_message = f"{status_code} Too Many Requests: rate limit exceeded"
        else:
            if mode_enum == FailureMode.RATE_LIMIT:
                if str(status_code) not in error_message and "rate limit" not in error_message.lower():
                    error_message = f"{status_code} Rate Limit: {error_message}"

        chaos_config = ChaosConfig(
            failure_mode=mode_enum,
            target_tool="get_order",
            delay_ms=delay_ms,
            error_message=error_message,
            status_code=status_code,
        )

        # 4. Configure active proxy
        proxy = self.chaos_service.get_proxy("get_order")
        proxy.set_config(chaos_config)

        try:
            # 5. Reconstruct agent context
            agent_version = agent_version_override or record.agent_version
            prompt_version = record.prompt_version

            agent = MockMember1Agent(
                version=agent_version,
                prompt_version=prompt_version,
                order_tool=proxy,
            )

            # 6. Execute through normal shared execution path (telemetry measured dynamically)
            telemetry = agent.run(request=record.prompt, run_id=replay_run_id)

            # 7. Construct result preserving original linkages
            result = ReplayExecutionResult(
                replay_run_id=replay_run_id,
                original_run_id=record.run_id,
                original_incident_id=record.original_incident_id,
                failure_mode=mode_enum.value,
                agent_version=agent_version,
                prompt_version=prompt_version,
                telemetry=telemetry,
            )

            # 8. Persist replay result
            self.storage.save(f"replay-res-{replay_run_id}", result)
            return result
        finally:
            # Guarantee safe chaos reset to avoid cross-scenario pollution
            proxy.reset()


def execute_replay(
    run_id_or_record: str | ReplayRecord,
    storage: Optional[MockStorage] = None,
    agent_version_override: Optional[str] = None,
) -> dict[str, Any]:
    """Callable service interface for Member 4's POST /runs/{run_id}/replay.

    Args:
        run_id_or_record: Run ID string or ReplayRecord object.
        storage: Optional MockStorage instance containing the stored record.
        agent_version_override: Optional agent version override for patch verification.

    Returns:
        JSON-serializable response dictionary with linkage and fresh telemetry.
    """
    engine = ReplayEngine(storage=storage)
    result = engine.replay(run_id_or_record, agent_version_override=agent_version_override)

    return {
        "status": "REPLAYED",
        "replay_run_id": result.replay_run_id,
        "original_run_id": result.original_run_id,
        "original_incident_id": result.original_incident_id,
        "failure_mode": result.failure_mode,
        "agent_version": result.agent_version,
        "prompt_version": result.prompt_version,
        "measured_telemetry": {
            "run_id": result.telemetry.run_id,
            "agent_version": result.telemetry.agent_version,
            "prompt_version": result.telemetry.prompt_version,
            "request": result.telemetry.request,
            "response": result.telemetry.response,
            "outcome": result.telemetry.outcome,
            "latency_ms": result.telemetry.latency_ms,
            "tokens": result.telemetry.tokens,
            "tool_calls": result.telemetry.tool_calls,
            "errors": result.telemetry.errors,
            "events": result.telemetry.events,
            "replayed_at": result.replayed_at,
        },
        "replayed_at": result.replayed_at,
    }
