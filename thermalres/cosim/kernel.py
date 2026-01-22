from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable, Optional

from ..config import SimConfig
from .interfaces import ChunkSummary, PlantInputs, RunMetrics, TimeSeriesSample
from .plant_runner import PlantRunner


class CoSimKernel:
    def __init__(
        self,
        config: SimConfig,
        plant_runner: Optional[PlantRunner] = None,
        schedule: Optional[Callable[[int], PlantInputs]] = None,
    ) -> None:
        """
        Initialize the Co-Simulation Kernel.

        Args:
            config: Simulation configuration
            plant_runner: Optional plant runner for Milestone 3+ (integrates plant models)
            schedule: Optional schedule function (cycle -> PlantInputs) for open-loop operation
        """
        self._cfg = config
        self._plant_runner = plant_runner
        self._schedule = schedule

    def run(self) -> tuple[RunMetrics, list[ChunkSummary], list[TimeSeriesSample]]:
        """
        Run the simulation.

        Returns:
            Tuple of (RunMetrics, ChunkSummaries, TimeSeriesSamples)
        """
        start_time = datetime.now(timezone.utc).isoformat()

        cycles = self._cfg.cycles
        step = self._cfg.cycle_chunks

        chunks = []
        timeseries = []
        cur = 0
        idx = 0

        # Simulation loop
        while cur < cycles:
            nxt = min(cur + step, cycles)
            chunks.append(ChunkSummary(chunk_idx=idx, start_cycle=cur, end_cycle=nxt))

            # If plant runner is configured, step the plant models
            if self._plant_runner is not None and self._schedule is not None:
                # Get inputs from schedule
                inputs = self._schedule(cur)

                # Step plant models
                outputs = self._plant_runner.step(inputs)

                # Record time-series sample
                sample = TimeSeriesSample(
                    cycle=cur,
                    temp_c=outputs.temp_c,
                    detune_nm=outputs.detune_nm,
                    locked=outputs.locked,
                    crc_fail_prob=outputs.crc_fail_prob,
                    heater_duty=inputs.heater_duty,
                    workload_frac=inputs.workload_frac,
                )
                timeseries.append(sample)

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

        return metrics, chunks, timeseries
