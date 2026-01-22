from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable, Optional

from ..config import SimConfig
from ..control.interfaces import ControlInputs, Controller
from .events import EventSampler
from .interfaces import (
    ChunkSummary,
    PlantInputs,
    PlantOutputs,
    RunMetrics,
    RunResult,
    TimeSeriesSample,
)
from .plant_runner import PlantRunner


class CoSimKernel:
    def __init__(
        self,
        config: SimConfig,
        plant_runner: Optional[PlantRunner] = None,
        schedule: Optional[Callable[[int], PlantInputs]] = None,
        controller: Optional[Controller] = None,
        detune_target_nm: float = 0.0,
    ) -> None:
        """
        Initialize the Co-Simulation Kernel.

        Args:
            config: Simulation configuration
            plant_runner: Optional plant runner (Milestone 3+)
            schedule: Optional schedule function for open-loop (Milestone 3)
            controller: Optional controller for closed-loop (Milestone 4)
            detune_target_nm: Target detuning for controller (default 0 = on resonance)
        """
        self._cfg = config
        self._plant_runner = plant_runner
        self._schedule = schedule
        self._controller = controller
        self._detune_target_nm = detune_target_nm

        # Initialize event sampler for deterministic event realization
        self._event_sampler = EventSampler(seed=config.seed)

        # Track last plant outputs for controller feedback
        self._last_outputs: Optional[PlantOutputs] = None

    def run(self) -> RunResult:
        """
        Run the simulation.

        Returns:
            RunResult with metrics, chunks, timeseries, and events
        """
        start_time = datetime.now(timezone.utc).isoformat()

        cycles = self._cfg.cycles
        step = self._cfg.cycle_chunks

        chunks = []
        timeseries = []
        events = []
        cur = 0
        idx = 0

        # Reset controller if present
        if self._controller is not None:
            self._controller.reset()

        # Simulation loop
        while cur < cycles:
            nxt = min(cur + step, cycles)
            chunks.append(ChunkSummary(chunk_idx=idx, start_cycle=cur, end_cycle=nxt))

            # If plant runner is configured, step the plant models
            if self._plant_runner is not None:
                # Determine inputs based on mode
                if self._controller is not None and self._last_outputs is not None:
                    # Closed-loop: controller computes heater duty
                    control_inputs = ControlInputs(
                        dt_s=0.1,  # Default timestep (from scenarios)
                        temp_c=self._last_outputs.temp_c,
                        detune_nm=self._last_outputs.detune_nm,
                        locked=self._last_outputs.locked,
                        crc_fail_prob=self._last_outputs.crc_fail_prob,
                        detune_target_nm=self._detune_target_nm,
                    )
                    control_outputs = self._controller.step(control_inputs)
                    heater_duty = control_outputs.heater_duty
                    controller_error = control_outputs.error
                    controller_active = True

                    # Get workload from schedule (if provided)
                    if self._schedule is not None:
                        scheduled_inputs = self._schedule(cur)
                        workload_frac = scheduled_inputs.workload_frac
                        dt_s = scheduled_inputs.dt_s
                    else:
                        workload_frac = 0.0
                        dt_s = 0.1
                elif self._schedule is not None:
                    # Open-loop: schedule provides both heater and workload
                    scheduled_inputs = self._schedule(cur)
                    heater_duty = scheduled_inputs.heater_duty
                    workload_frac = scheduled_inputs.workload_frac
                    dt_s = scheduled_inputs.dt_s
                    controller_error = None
                    controller_active = False
                else:
                    # No inputs configured
                    continue

                # Create plant inputs
                inputs = PlantInputs(
                    heater_duty=heater_duty,
                    workload_frac=workload_frac,
                    dt_s=dt_s,
                )

                # Step plant models
                outputs = self._plant_runner.step(inputs)
                self._last_outputs = outputs

                # Sample CRC event
                event = self._event_sampler.sample_crc_event(
                    cycle=cur,
                    chunk_idx=idx,
                    crc_fail_prob=outputs.crc_fail_prob,
                    locked=outputs.locked,
                )
                events.append(event)

                # Record time-series sample
                sample = TimeSeriesSample(
                    cycle=cur,
                    temp_c=outputs.temp_c,
                    detune_nm=outputs.detune_nm,
                    locked=outputs.locked,
                    crc_fail_prob=outputs.crc_fail_prob,
                    heater_duty=inputs.heater_duty,
                    workload_frac=inputs.workload_frac,
                    controller_error=controller_error,
                    controller_active=controller_active,
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

        return RunResult(
            metrics=metrics,
            chunks=chunks,
            timeseries=timeseries,
            events=events,
        )
