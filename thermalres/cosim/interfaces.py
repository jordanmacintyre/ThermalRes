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


# Plant model interfaces

@dataclass(frozen=True, slots=True)
class PlantInputs:
    """
    Inputs to the plant model chain.
    """
    heater_duty: float      # Heater duty cycle [0, 1]
    workload_frac: float    # Workload fraction [0, 1]
    dt_s: float             # Time step (seconds)


@dataclass(frozen=True, slots=True)
class PlantOutputs:
    """
    Outputs from the plant model chain.
    """
    temp_c: float           # Temperature (°C)
    resonance_nm: float     # Resonance wavelength (nm)
    detune_nm: float        # Detuning (nm, signed)
    locked: bool            # Lock status
    crc_fail_prob: float    # CRC failure probability [0, 1]


# Time-series recording

@dataclass(frozen=True, slots=True)
class TimeSeriesSample:
    """
    A single time-series sample recording plant state and inputs.

    These samples are recorded at each chunk boundary and written to
    timeseries.json for offline analysis and regression testing.
    """
    cycle: int              # Cycle number
    temp_c: float           # Temperature (°C)
    detune_nm: float        # Detuning (nm, signed)
    locked: bool            # Lock status
    crc_fail_prob: float    # CRC failure probability [0, 1]
    heater_duty: float      # Heater duty cycle [0, 1]
    workload_frac: float    # Workload fraction [0, 1]
    # Controller outputs (optional, for closed-loop mode)
    controller_error: float | None = None    # Control error (e.g., detune error)
    controller_active: bool = False          # Whether controller was active


# Event recording

@dataclass(frozen=True, slots=True)
class CrcEvent:
    """
    A CRC failure event realized from impairment probability.

    Events are deterministically sampled using the simulation seed.
    These events are consumed by the link monitor to track link state.
    """
    cycle: int              # Cycle number
    chunk_idx: int          # Chunk index
    crc_fail: bool          # Whether CRC failure occurred
    crc_fail_prob: float    # Probability that generated this event


# Link monitor interfaces
# These dataclasses support the integration of RTL link_monitor with the
# Python simulation. The link monitor tracks CRC failures and maintains
# a link up/down state based on consecutive failure/pass thresholds.

@dataclass(frozen=True, slots=True)
class LinkMonitorConfig:
    """
    Configuration for the link monitor state machine.

    These parameters control the hysteresis thresholds for link state
    transitions. The defaults match the RTL link_monitor.sv parameters.

    Attributes:
        fails_to_down: Number of consecutive CRC failures required to
                       transition from link_up=True to link_up=False.
        passes_to_up: Number of consecutive CRC passes required to
                      transition from link_up=False to link_up=True.
        use_rtl: If True, validate Python reference against RTL simulation
                 using cocotb/Verilator after the run completes.
    """
    fails_to_down: int = 4   # Consecutive fails to trigger link down
    passes_to_up: int = 8    # Consecutive passes to trigger link up
    use_rtl: bool = False    # Enable post-run RTL validation


@dataclass(frozen=True, slots=True)
class LinkStateSample:
    """
    Link monitor state sample at a simulation cycle.

    Captures the digital link state machine outputs for recording and
    analysis. This dataclass is compatible with both the Python reference
    model (LinkMonitorRef) and the RTL simulation (link_monitor.sv).

    The link monitor implements a hysteresis-based state machine:
    - Link starts UP after reset
    - Link transitions DOWN after `fails_to_down` consecutive CRC failures
    - Link transitions UP after `passes_to_up` consecutive CRC passes

    Attributes:
        cycle: The simulation cycle number when this sample was taken.
        link_up: Current link state (True=up/healthy, False=down/degraded).
        total_frames: Total number of frames processed since reset.
        total_crc_fails: Total number of CRC failures observed since reset.
        consec_fails: Current count of consecutive failures (resets on pass).
        consec_passes: Current count of consecutive passes (resets on fail).
    """
    cycle: int              # Simulation cycle number
    link_up: bool           # Link state (True=up, False=down)
    total_frames: int       # Total frames processed
    total_crc_fails: int    # Total CRC failures observed
    consec_fails: int       # Consecutive failures (resets on pass)
    consec_passes: int      # Consecutive passes (resets on fail)


# Run results

@dataclass(frozen=True, slots=True)
class RunResult:
    """
    Complete results from a simulation run.

    This consolidates all outputs to avoid expanding return tuples.

    Attributes:
        metrics: Run-level metadata (timing, scenario name, counts).
        chunks: Per-chunk summaries with cycle ranges.
        timeseries: Per-chunk plant state and input samples.
        events: Per-cycle CRC failure events (realized from probabilities).
        link_states: Per-cycle link monitor state samples.
                     None if link monitor was not configured.
    """
    metrics: RunMetrics
    chunks: list[ChunkSummary]
    timeseries: list[TimeSeriesSample]
    events: list[CrcEvent]
    # Optional link monitor state tracking
    # When LinkRunner is configured, this contains the link state at each
    # cycle. When not configured (backward compatibility), this is None.
    link_states: list[LinkStateSample] | None = None
