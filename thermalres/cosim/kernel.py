from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from ..config import SimConfig
from .interfaces import ChunkSummary, RunMetrics


class CoSimKernel:
    def __init__(self, config: SimConfig) -> None:
        self._cfg = config

    def run(self) -> tuple[RunMetrics, list[ChunkSummary]]:
        start_time = datetime.now(timezone.utc).isoformat()

        cycles = self._cfg.cycles
        step = self._cfg.cycle_chunks

        chunks = []
        cur = 0
        idx = 0
        
        # Simulation loop
        while cur < cycles:
            nxt = min(cur + step, cycles)
            chunks.append(ChunkSummary(chunk_idx=idx, start_cycle=cur, end_cycle=nxt))
            cur = nxt
            idx += 1

        finish_time = datetime.now(timezone.utc).isoformat()
        metrics = RunMetrics(
            total_cycles=cycles,
            total_chunks=len(chunks),
            start_time=start_time,
            finish_time=finish_time,
            scenario_name=self._cfg.name,
        )
        # Ensure dataclasses remain trivially serializable later (fails fast if not).
        _ = asdict(metrics)

        return metrics, chunks
