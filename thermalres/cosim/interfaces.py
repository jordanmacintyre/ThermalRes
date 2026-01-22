from __future__ import annotations

from dataclasses import dataclass

# slots are used to enfore good interface hygiene, disables dynamic attribute creation.
@dataclass(frozen=True, slots=True)
class ChunkSummary:
    chunk_idx: int
    start_cycle: int
    end_cycle: int  # exclusive; [start_cycle, end_cycle)

@dataclass(frozen=True, slots=True)
class RunMetrics:
    total_cycles: int
    total_chunks: int
    start_time: str
    finish_time: str
    scenario_name: str
