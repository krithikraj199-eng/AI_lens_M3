"""Evidence Recorder for Reliability Lab.

Binds run_id, ChaosConfig, and measured telemetry results together for retention
and replay validation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from reliability_lab.contracts import ChaosConfig
from reliability_lab.adapters.telemetry_adapter import AgentExecutionResult
from reliability_lab.mocks.mock_storage import MockStorage


@dataclass
class EvidenceRecord:
    """Retained execution evidence binding run_id, failure_mode, and telemetry."""
    run_id: str
    failure_mode: str
    config: ChaosConfig
    result: AgentExecutionResult
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EvidenceRecorder:
    """Manages recording and persistence of Reliability Lab evidence records."""

    def __init__(self, storage: Optional[MockStorage] = None) -> None:
        self.storage = storage or MockStorage()

    def record_execution(
        self,
        run_id: str,
        config: ChaosConfig,
        result: AgentExecutionResult,
    ) -> EvidenceRecord:
        """Capture and persist evidence record for an execution run.

        Args:
            run_id: Unique correlation identifier.
            config: ChaosConfig active during run.
            result: Execution result and telemetry.

        Returns:
            EvidenceRecord.
        """
        failure_mode_val = config.failure_mode.value if hasattr(config.failure_mode, "value") else str(config.failure_mode)
        record = EvidenceRecord(
            run_id=run_id,
            failure_mode=failure_mode_val,
            config=config,
            result=result,
        )
        self.storage.save(run_id, record)
        return record
