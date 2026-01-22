from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

def _clean_path_name(path_name: str) -> str:
    # Remove unsafe characters from directory name
    cleaned = [c if (c.isalnum() or c in ("-", "_")) else "_" for c in path_name]
    return "".join(cleaned).strip("_")

# slots are used to enfore good interface hygiene, disables dynamic attribute creation.
@dataclass(frozen=True, slots=True)
class SimConfig:
    """
    SimConfig

    Deefinitions and configuration for simulation run

    Params:
    - name (str) : simulation name
    - cycles (int) : total number of cycles to run simulation for
    - cycle_chunks (int) : number of cycles that occur per simulation step
    - seed (int) : random seed for determinisim
    - out_dir (str|None) : output directory for simulation artifacts
                           default: artifacts/runs/<timestamp>_<name>
    """
    name: str
    cycles: int
    cycle_chunks: int
    seed: int
    out_dir: Path

    @staticmethod
    def from_args(
        *,
        name: str,
        cycles: int,
        cycle_chunks: int,
        seed: int,
        out_dir: str | None
    ) -> "SimConfig":
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        if cycles < 0:
            raise ValueError("cycles must be >= 0")
        if cycle_chunks <= 0:
            raise ValueError("cycle_chunks must be > 0")

        if out_dir is not None:
            out_dir = Path(out_dir)
        else:
            """
            Default output location:
            artifacts/runs/<timestamp>_<scenario>
            Timestamp is UTC in YYYYmmdd_HHMMSS format.
            """
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            clean_name = _clean_path_name(name)

            # Check if name is empty after cleaning
            if not clean_name:
                clean_name = "scenario"
            out_dir = Path("artifacts").joinpath(f"runs/{ts}_{clean_name}")

        return SimConfig(
            name=name,
            cycles=int(cycles),
            cycle_chunks=int(cycle_chunks),
            seed=int(seed),
            out_dir=out_dir,
        )


@dataclass(frozen=True, slots=True)
class PlantConfig:
    """
    Defaults for photonic resonator with thermal control.
    """
    # Thermal parameters
    ambient_c: float = 25.0              # Ambient temperature (°C)
    r_th_c_per_w: float = 10.0           # Thermal resistance (°C/W)
    c_th_j_per_c: float = 0.1            # Thermal capacitance (J/°C)
    heater_w_max: float = 1.0            # Maximum heater power (W)
    workload_w_max: float = 0.5          # Maximum workload power (W)

    # Resonator parameters
    lambda0_nm: float = 1550.0           # Nominal resonance at ambient (nm)
    thermo_optic_nm_per_c: float = 0.1   # Thermo-optic coefficient (nm/°C)
    lock_window_nm: float = 0.5          # Lock tolerance (±nm)
    target_lambda_nm: float = 1550.0     # Target laser wavelength (nm)

    # Impairment parameters
    detune_50_nm: float = 0.3            # Detuning for 50% failure probability
    detune_floor_nm: float = 0.0         # Below this, no failures
    detune_ceil_nm: float = 1.0          # Above this, always fails
