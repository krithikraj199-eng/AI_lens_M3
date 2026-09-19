"""AgentLens Member 3: Reliability Lab.

Provides controlled chaos injection, replay records, scenario replay,
before/after evaluation, regression test quality gates, replay timelines,
evidence bundles, and repeatability benchmarks.
"""

from reliability_lab.adapters.member2_adapter import import_member2_scenario, validate_member2_scenario
from reliability_lab.benchmark.runner import RepeatabilityBenchmark, RepeatabilityBenchmarkReport
from reliability_lab.demo import demo_reset, run_canonical_demo_flow
from reliability_lab.evaluation.evaluator import build_before_after_panel, evaluate_pair, execute_evaluation
from reliability_lab.evidence.bundle import (
    EvidenceBundle,
    build_canonical_evidence_bundle,
    serialize_evidence_bundle,
)
from reliability_lab.timeline import (
    ReplayTimeline,
    TimelineEvent,
    build_replay_timeline,
    serialize_replay_timeline,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "build_replay_timeline",
    "serialize_replay_timeline",
    "ReplayTimeline",
    "TimelineEvent",
    "build_before_after_panel",
    "evaluate_pair",
    "execute_evaluation",
    "EvidenceBundle",
    "build_canonical_evidence_bundle",
    "serialize_evidence_bundle",
    "RepeatabilityBenchmark",
    "RepeatabilityBenchmarkReport",
    "import_member2_scenario",
    "validate_member2_scenario",
    "demo_reset",
    "run_canonical_demo_flow",
]



