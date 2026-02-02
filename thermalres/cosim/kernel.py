"""
Co-Simulation Kernel for ThermalRes.

This module provides the CoSimKernel class, which is the central orchestrator
for the mixed-domain co-simulation. It manages:
- Time advancement in discrete chunks
- Plant model stepping (thermal, resonator, impairment)
- Controller feedback loops (PID, bang-bang)
- CRC event sampling and realization
- Link monitor state tracking

The kernel is the authoritative timebase for the simulation. All other
components (plant, controller, link monitor) are driven by the kernel's
time advancement.

Architecture:
```
    CoSimKernel (Time Authority)
        |
        +-- PlantRunner
        |   |-- ThermalState
        |   |-- eval_plant_chain()
        |
        +-- Controller (optional)
        |   |-- PIDController or BangBangController
        |   |-- Computes heater_duty from plant feedback
        |
        +-- EventSampler
        |   |-- Bernoulli sampling of CRC events
        |   |-- Deterministic via simulation seed
        |
        +-- LinkRunner (optional)
        |   |-- LinkMonitorRef (Python reference)
        |   |-- RTL validation (optional)
        |
        v
    RunResult:
        |-- RunMetrics (timing, scenario)
        |-- ChunkSummary[] (cycle ranges)
        |-- TimeSeriesSample[] (plant state)
        |-- CrcEvent[] (realized events)
        |-- LinkStateSample[] (link state, optional)
```

Example usage:
    >>> from thermalres.config import SimConfig
    >>> from thermalres.cosim.kernel import CoSimKernel
    >>> from thermalres.cosim.plant_runner import PlantRunner
    >>> from thermalres.cosim.link_runner import LinkRunner
    >>> from thermalres.scenarios.open_loop import constant_heater
    >>>
    >>> config = SimConfig.from_args(
    ...     name="example", cycles=100, cycle_chunks=10, seed=42
    ... )
    >>> plant_runner = PlantRunner(...)  # With default params
    >>> schedule = constant_heater(heater=0.5, workload=0.3)
    >>> link_runner = LinkRunner()  # Optional
    >>>
    >>> kernel = CoSimKernel(
    ...     config=config,
    ...     plant_runner=plant_runner,
    ...     schedule=schedule,
    ...     link_runner=link_runner,
    ... )
    >>> result = kernel.run()
    >>> print(f"Simulated {result.metrics.total_cycles} cycles")
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Optional

from ..config import SimConfig
from ..control.interfaces import ControlInputs, Controller
from .events import EventSampler
from .interfaces import (
    ChunkSummary,
    LinkStateSample,
    PlantInputs,
    PlantOutputs,
    RunMetrics,
    RunResult,
    TimeSeriesSample,
)
from .plant_runner import PlantRunner

# Import LinkRunner with TYPE_CHECKING to avoid issues if used without
# the link_runner module being needed
if TYPE_CHECKING:
    from .link_runner import LinkRunner


class CoSimKernel:
    """
    Co-Simulation Kernel - the central orchestrator for ThermalRes.

    The kernel manages time advancement and coordinates all simulation
    components. It is the authoritative timebase: other components do
    not track time independently.

    Time is advanced in discrete "chunks" - contiguous ranges of cycles
    processed atomically. This chunked approach enables:
    - Efficient batched computation
    - Clean synchronization points between domains
    - Flexible trade-off between fidelity and performance

    Attributes:
        _cfg: Simulation configuration (name, cycles, chunk size, seed).
        _plant_runner: Optional plant model runner.
        _schedule: Optional input schedule function (open-loop).
        _controller: Optional feedback controller.
        _link_runner: Optional link monitor runner.
    """

    def __init__(
        self,
        config: SimConfig,
        plant_runner: Optional[PlantRunner] = None,
        schedule: Optional[Callable[[int], PlantInputs]] = None,
        controller: Optional[Controller] = None,
        detune_target_nm: float = 0.0,
        link_runner: Optional["LinkRunner"] = None,
    ) -> None:
        """
        Initialize the Co-Simulation Kernel.

        Creates a kernel configured with the specified components. All
        components except `config` are optional to support incremental
        feature development and backward compatibility.

        Args:
            config: Simulation configuration specifying:
                    - name: Scenario name for artifacts
                    - cycles: Total simulation cycles
                    - cycle_chunks: Cycles per chunk
                    - seed: Random seed for determinism
            plant_runner: Optional plant runner for thermal/resonator/
                          impairment models. When None, the kernel runs
                          without plant physics.
            schedule: Optional schedule function that returns PlantInputs
                      for a given cycle number. Used for open-loop control.
                      Signature: `(cycle: int) -> PlantInputs`
            controller: Optional feedback controller for closed-loop
                        operation. When provided with plant_runner, the
                        controller computes heater_duty based on plant outputs.
            detune_target_nm: Target detuning for controller feedback
                              (default 0 = on resonance). Passed to
                              controller as the setpoint.
            link_runner: Optional link monitor runner for tracking
                         link state from CRC events. When provided, CRC
                         events are processed through the link state machine
                         and recorded.
        """
        # ─────────────────────────────────────────────────────────────
        # Store configuration and components
        # ─────────────────────────────────────────────────────────────
        self._cfg = config
        self._plant_runner = plant_runner
        self._schedule = schedule
        self._controller = controller
        self._detune_target_nm = detune_target_nm
        self._link_runner = link_runner

        # ─────────────────────────────────────────────────────────────
        # Initialize event sampler for deterministic CRC event realization
        # The sampler uses the simulation seed for reproducibility
        # ─────────────────────────────────────────────────────────────
        self._event_sampler = EventSampler(seed=config.seed)

        # ─────────────────────────────────────────────────────────────
        # Track last plant outputs for controller feedback
        # This is None until the first plant step completes
        # ─────────────────────────────────────────────────────────────
        self._last_outputs: Optional[PlantOutputs] = None

    def run(self) -> RunResult:
        """
        Run the simulation.

        Executes the full simulation from cycle 0 to `config.cycles`,
        advancing time in chunks of `config.cycle_chunks`. For each
        chunk boundary:
        1. Determine inputs (from schedule or controller)
        2. Step the plant models (if configured)
        3. Sample CRC event (deterministic Bernoulli)
        4. Step link monitor (if configured)
        5. Record time-series sample

        Returns:
            RunResult containing:
            - metrics: Run-level metadata (timing, cycle counts)
            - chunks: Per-chunk summaries with cycle ranges
            - timeseries: Per-chunk plant state samples
            - events: Per-cycle CRC failure events
            - link_states: Per-cycle link monitor states (if configured)

        Note:
            The simulation is fully deterministic when using the same
            config.seed value. This enables reproducible runs for
            testing and debugging.
        """
        # ─────────────────────────────────────────────────────────────
        # Record simulation start time (wall clock)
        # ─────────────────────────────────────────────────────────────
        start_time = datetime.now(timezone.utc).isoformat()

        # Extract frequently-used config values
        cycles = self._cfg.cycles
        step = self._cfg.cycle_chunks

        # ─────────────────────────────────────────────────────────────
        # Initialize result containers
        # ─────────────────────────────────────────────────────────────
        chunks: list[ChunkSummary] = []
        timeseries: list[TimeSeriesSample] = []
        events: list = []
        link_states: list[LinkStateSample] = []

        # Current cycle and chunk index
        cur = 0
        idx = 0

        # ─────────────────────────────────────────────────────────────
        # Reset stateful components before simulation
        # This ensures clean state for each run
        # ─────────────────────────────────────────────────────────────
        if self._controller is not None:
            self._controller.reset()

        if self._link_runner is not None:
            self._link_runner.reset()

        # ─────────────────────────────────────────────────────────────
        # Main simulation loop
        # Advances time in chunks from cycle 0 to `cycles`
        # ─────────────────────────────────────────────────────────────
        while cur < cycles:
            # Calculate chunk boundaries
            # nxt is exclusive: chunk covers [cur, nxt)
            nxt = min(cur + step, cycles)
            chunks.append(ChunkSummary(chunk_idx=idx, start_cycle=cur, end_cycle=nxt))

            # ─────────────────────────────────────────────────────────
            # Step plant models if configured
            # ─────────────────────────────────────────────────────────
            if self._plant_runner is not None:
                # Determine inputs based on operating mode:
                # 1. Closed-loop: controller computes heater_duty
                # 2. Open-loop: schedule provides all inputs

                if self._controller is not None and self._last_outputs is not None:
                    # ─────────────────────────────────────────────────
                    # CLOSED-LOOP MODE
                    # Controller computes heater_duty from plant feedback
                    # ─────────────────────────────────────────────────
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
                    # Controller only computes heater_duty; workload comes
                    # from the schedule (e.g., external disturbance)
                    if self._schedule is not None:
                        scheduled_inputs = self._schedule(cur)
                        workload_frac = scheduled_inputs.workload_frac
                        dt_s = scheduled_inputs.dt_s
                    else:
                        workload_frac = 0.0
                        dt_s = 0.1

                elif self._schedule is not None:
                    # ─────────────────────────────────────────────────
                    # OPEN-LOOP MODE
                    # Schedule provides both heater_duty and workload
                    # ─────────────────────────────────────────────────
                    scheduled_inputs = self._schedule(cur)
                    heater_duty = scheduled_inputs.heater_duty
                    workload_frac = scheduled_inputs.workload_frac
                    dt_s = scheduled_inputs.dt_s
                    controller_error = None
                    controller_active = False

                else:
                    # No inputs configured - skip this chunk
                    # This shouldn't happen in normal use but provides
                    # graceful handling
                    cur = nxt
                    idx += 1
                    continue

                # ─────────────────────────────────────────────────────
                # Create plant inputs and step plant models
                # ─────────────────────────────────────────────────────
                inputs = PlantInputs(
                    heater_duty=heater_duty,
                    workload_frac=workload_frac,
                    dt_s=dt_s,
                )

                # Step plant models (thermal -> resonator -> impairment)
                outputs = self._plant_runner.step(inputs)
                self._last_outputs = outputs

                # ─────────────────────────────────────────────────────
                # Sample CRC event from impairment probability
                # Uses deterministic Bernoulli sampling
                # ─────────────────────────────────────────────────────
                event = self._event_sampler.sample_crc_event(
                    cycle=cur,
                    chunk_idx=idx,
                    crc_fail_prob=outputs.crc_fail_prob,
                    locked=outputs.locked,
                )
                events.append(event)

                # ─────────────────────────────────────────────────────
                # Step link monitor if configured
                # Processes the CRC event and tracks link state
                # ─────────────────────────────────────────────────────
                if self._link_runner is not None:
                    link_sample = self._link_runner.step(event)
                    link_states.append(link_sample)

                # ─────────────────────────────────────────────────────
                # Record time-series sample for artifact output
                # ─────────────────────────────────────────────────────
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

            # Advance to next chunk
            cur = nxt
            idx += 1

        # ─────────────────────────────────────────────────────────────
        # Record simulation end time and create metrics
        # ─────────────────────────────────────────────────────────────
        finish_time = datetime.now(timezone.utc).isoformat()
        metrics = RunMetrics(
            total_cycles=cycles,
            total_chunks=len(chunks),
            start_time=start_time,
            finish_time=finish_time,
            scenario_name=self._cfg.name,
        )

        # Validate that metrics are serializable (fail-fast check)
        _ = asdict(metrics)

        # ─────────────────────────────────────────────────────────────
        # Construct and return RunResult
        # link_states is None if link_runner was not configured
        # ─────────────────────────────────────────────────────────────
        return RunResult(
            metrics=metrics,
            chunks=chunks,
            timeseries=timeseries,
            events=events,
            link_states=link_states if link_states else None,
        )
