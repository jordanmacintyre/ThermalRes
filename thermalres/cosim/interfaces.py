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


# Plant model interfaces (Milestone 2)

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


# Time-series recording (Milestone 3+)

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
    # Milestone 4: controller outputs
    controller_error: float | None = None    # Control error (e.g., detune error)
    controller_active: bool = False          # Whether controller was active


# Event recording (Milestone 4)

@dataclass(frozen=True, slots=True)
class CrcEvent:
    """
    A CRC failure event realized from impairment probability.

    Events are deterministically sampled using the simulation seed.
    """
    cycle: int              # Cycle number
    chunk_idx: int          # Chunk index
    crc_fail: bool          # Whether CRC failure occurred
    crc_fail_prob: float    # Probability that generated this event


# Run results (Milestone 4)

@dataclass(frozen=True, slots=True)
class RunResult:
    """
    Complete results from a simulation run.

    This consolidates all outputs to avoid expanding return tuples.
    """
    metrics: RunMetrics
    chunks: list[ChunkSummary]
    timeseries: list[TimeSeriesSample]
    events: list[CrcEvent]
