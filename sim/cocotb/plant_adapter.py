"""
Plant adapter for cocotb co-simulation.

This module bridges the RTL link_monitor simulation with Python plant models.
Following the CoherentControlMatMul pattern, cocotb drives the simulation loop
and the PlantAdapter is called each cycle to:

1. Read RTL state (if needed)
2. Step the Python plant model
3. Write plant outputs to RTL inputs
4. Record samples for artifact generation

The key insight is that cocotb (RTL clock) drives the loop, and Python
plant models are called as "callbacks" on each clock cycle.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cocotb
from cocotb.triggers import RisingEdge, Timer


# Add project root to path so we can import thermalres
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

from thermalres.config import PlantConfig
from thermalres.control.interfaces import ControlInputs, Controller
from thermalres.cosim.interfaces import (
    LinkStateSample,
    PlantInputs,
    PlantOutputs,
    TimeSeriesSample,
)
from thermalres.cosim.plant_runner import PlantRunner
from thermalres.plant import ImpairmentParams, ResonatorParams, ThermalParams


@dataclass
class CosimConfig:
    """Configuration for cocotb co-simulation."""
    cycles: int = 300
    seed: int = 42
    dt_s: float = 0.1

    # Plant parameters
    ambient_c: float = 25.0
    r_th_c_per_w: float = 2.0
    c_th_j_per_c: float = 5.0
    heater_w_max: float = 3.0
    workload_w_max: float = 5.0

    lambda0_nm: float = 1550.0
    thermo_optic_nm_per_c: float = 0.01
    lock_window_nm: float = 0.02
    target_lambda_nm: float = 1550.08

    detune_50_nm: float = 0.03
    detune_floor_nm: float = 0.01
    detune_ceil_nm: float = 0.05

    # Workload schedule
    warmup_cycles: int = 50
    warmup_workload: float = 0.3
    disturbance_workload: float = 0.7
    pulsed: bool = True
    pulse_period: int = 40
    pulse_duty: float = 0.5

    # Link monitor parameters
    fails_to_down: int = 4
    passes_to_up: int = 8

    @classmethod
    def from_env(cls) -> "CosimConfig":
        """Load configuration from SIM_CONFIG environment variable."""
        config_json = os.environ.get("SIM_CONFIG", "{}")
        config_dict = json.loads(config_json)
        return cls(**{k: v for k, v in config_dict.items() if k in cls.__dataclass_fields__})


class PlantAdapter:
    """
    Bridge between RTL simulation and Python plant models.

    This adapter follows the CoherentControlMatMul pattern:
    - cocotb drives the clock loop
    - On each clock cycle, the adapter:
      1. Steps the plant model with current workload
      2. Writes crc_fail_prob to RTL
      3. Reads link state from RTL
      4. Records samples for artifacts

    The controller (if any) is run in Python, computing heater_duty
    based on plant feedback.
    """

    def __init__(
        self,
        dut,
        plant_runner: PlantRunner,
        controller: Controller | None = None,
        schedule: Callable[[int], PlantInputs] | None = None,
        config: CosimConfig | None = None,
    ):
        """
        Initialize the plant adapter.

        Args:
            dut: cocotb DUT handle (cosim_top)
            plant_runner: Python plant model runner
            controller: Optional feedback controller
            schedule: Workload schedule function (cycle -> PlantInputs)
            config: Co-simulation configuration
        """
        self.dut = dut
        self.plant = plant_runner
        self.controller = controller
        self.schedule = schedule
        self.config = config or CosimConfig()

        self._running = False
        self._cycle = 0

        # Storage for artifacts
        self._timeseries: list[TimeSeriesSample] = []
        self._link_states: list[LinkStateSample] = []

    async def run(self, max_cycles: int | None = None):
        """
        Main simulation loop - called by cocotb test.

        This runs the plant model in lockstep with RTL. On each cycle:
        1. Get workload from schedule
        2. Run controller (if present) to compute heater_duty
        3. Step plant model
        4. Write crc_fail_prob to RTL
        5. Wait for clock edge
        6. Read link state from RTL
        7. Record samples

        Args:
            max_cycles: Maximum cycles to run (default: from config)
        """
        self._running = True
        self._cycle = 0

        max_cycles = max_cycles or self.config.cycles

        while self._running and self._cycle < max_cycles:
            # ─────────────────────────────────────────────────────────────
            # Step 1: Get workload from schedule
            # ─────────────────────────────────────────────────────────────
            if self.schedule:
                plant_inputs = self.schedule(self._cycle)
                workload_frac = plant_inputs.workload_frac
                dt_s = plant_inputs.dt_s
            else:
                workload_frac = self.config.warmup_workload
                dt_s = self.config.dt_s

            # ─────────────────────────────────────────────────────────────
            # Step 2: Run controller (if present)
            # ─────────────────────────────────────────────────────────────
            if self.controller:
                # Get current plant state for feedback
                thermal_state = self.plant.get_thermal_state()
                # Create control inputs from last plant outputs
                ctrl_inputs = ControlInputs(
                    dt_s=dt_s,
                    temp_c=thermal_state.temp_c,
                    detune_nm=self._last_detune if hasattr(self, '_last_detune') else 0.0,
                    locked=self._last_locked if hasattr(self, '_last_locked') else True,
                    crc_fail_prob=self._last_crc_prob if hasattr(self, '_last_crc_prob') else 0.0,
                    detune_target_nm=0.0,
                )
                ctrl_outputs = self.controller.step(ctrl_inputs)
                heater_duty = ctrl_outputs.heater_duty
            else:
                heater_duty = 0.0  # Open-loop mode

            # ─────────────────────────────────────────────────────────────
            # Step 3: Step plant model
            # ─────────────────────────────────────────────────────────────
            plant_inputs = PlantInputs(
                heater_duty=heater_duty,
                workload_frac=workload_frac,
                dt_s=dt_s,
            )
            plant_outputs = self.plant.step(plant_inputs)

            # Cache for next cycle's controller
            self._last_detune = plant_outputs.detune_nm
            self._last_locked = plant_outputs.locked
            self._last_crc_prob = plant_outputs.crc_fail_prob

            # ─────────────────────────────────────────────────────────────
            # Step 4: Write crc_fail_prob to RTL (Q0.16 format)
            # ─────────────────────────────────────────────────────────────
            # Convert probability [0.0, 1.0] to 16-bit unsigned [0, 65535]
            crc_prob_q16 = int(plant_outputs.crc_fail_prob * 65535)
            crc_prob_q16 = max(0, min(65535, crc_prob_q16))  # Clamp

            self.dut.crc_fail_prob.value = crc_prob_q16
            self.dut.valid.value = 1

            # ─────────────────────────────────────────────────────────────
            # Step 5: Wait for clock edge
            # ─────────────────────────────────────────────────────────────
            await RisingEdge(self.dut.clk)

            # Small delay to let NBA settle (standard cocotb pattern)
            await Timer(1, units="ns")

            # ─────────────────────────────────────────────────────────────
            # Step 6: Read link state from RTL
            # ─────────────────────────────────────────────────────────────
            link_up = bool(self.dut.link_up.value)
            total_frames = int(self.dut.total_frames.value)
            total_crc_fails = int(self.dut.total_crc_fails.value)
            consec_fails = int(self.dut.consec_fails.value)
            consec_passes = int(self.dut.consec_passes.value)
            crc_fail = bool(self.dut.crc_fail.value)

            # ─────────────────────────────────────────────────────────────
            # Step 7: Record samples
            # ─────────────────────────────────────────────────────────────
            ts_sample = TimeSeriesSample(
                cycle=self._cycle,
                temp_c=plant_outputs.temp_c,
                detune_nm=plant_outputs.detune_nm,
                locked=plant_outputs.locked,
                crc_fail_prob=plant_outputs.crc_fail_prob,
                heater_duty=heater_duty,
                workload_frac=workload_frac,
            )
            self._timeseries.append(ts_sample)

            ls_sample = LinkStateSample(
                cycle=self._cycle,
                link_up=link_up,
                total_frames=total_frames,
                total_crc_fails=total_crc_fails,
                consec_fails=consec_fails,
                consec_passes=consec_passes,
            )
            self._link_states.append(ls_sample)

            self._cycle += 1

        self._running = False

    def stop(self):
        """Stop the simulation loop."""
        self._running = False

    def get_timeseries(self) -> list[TimeSeriesSample]:
        """Get recorded timeseries samples."""
        return list(self._timeseries)

    def get_link_states(self) -> list[LinkStateSample]:
        """Get recorded link state samples."""
        return list(self._link_states)

    def write_artifacts(self, out_dir: str | Path):
        """
        Write simulation artifacts to disk.

        Args:
            out_dir: Output directory path
        """
        import json
        from dataclasses import asdict

        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        # Write timeseries in format expected by plot_from_artifacts
        timeseries_data = {"samples": [asdict(s) for s in self._timeseries]}
        with open(out_path / "timeseries.json", "w") as f:
            json.dump(timeseries_data, f, indent=2)

        # Write link states in format expected by plot_from_artifacts
        link_data = {"samples": [asdict(s) for s in self._link_states]}
        with open(out_path / "link_state.json", "w") as f:
            json.dump(link_data, f, indent=2)

        # Write summary metrics in format expected by plot_from_artifacts
        metrics = {
            "run": {
                "scenario_name": "cocotb_cosim",
                "total_cycles": self._cycle,
            },
            "final_temp_c": self._timeseries[-1].temp_c if self._timeseries else None,
            "final_detune_nm": self._timeseries[-1].detune_nm if self._timeseries else None,
            "final_link_up": self._link_states[-1].link_up if self._link_states else None,
            "total_crc_fails": self._link_states[-1].total_crc_fails if self._link_states else 0,
        }
        with open(out_path / "metrics.json", "w") as f:
            json.dump(metrics, f, indent=2)

        # Generate plot (always, unless matplotlib unavailable)
        try:
            from thermalres.cosim.plotting import plot_from_artifacts
            plot_from_artifacts(out_path, show=False)
        except ImportError:
            # matplotlib not available, skip plot
            pass
        except Exception as e:
            # Don't fail artifact writing if plotting fails
            print(f"Warning: Could not generate plot: {e}")


def create_plant_runner(config: CosimConfig) -> PlantRunner:
    """Create a PlantRunner from CosimConfig."""
    thermal_params = ThermalParams(
        ambient_c=config.ambient_c,
        c_th_j_per_c=config.c_th_j_per_c,
        r_th_c_per_w=config.r_th_c_per_w,
        heater_w_max=config.heater_w_max,
        workload_w_max=config.workload_w_max,
    )

    resonator_params = ResonatorParams(
        lambda0_nm=config.lambda0_nm,
        thermo_optic_nm_per_c=config.thermo_optic_nm_per_c,
        lock_window_nm=config.lock_window_nm,
        target_lambda_nm=config.target_lambda_nm,
        ambient_c=config.ambient_c,
    )

    impairment_params = ImpairmentParams(
        detune_50_nm=config.detune_50_nm,
        detune_floor_nm=config.detune_floor_nm,
        detune_ceil_nm=config.detune_ceil_nm,
    )

    return PlantRunner(
        thermal_params=thermal_params,
        resonator_params=resonator_params,
        impairment_params=impairment_params,
        initial_temp_c=config.ambient_c,
    )


def create_workload_schedule(config: CosimConfig) -> Callable[[int], PlantInputs]:
    """Create workload schedule from config."""
    import random
    rng = random.Random(config.seed)

    def schedule(cycle: int) -> PlantInputs:
        if cycle < config.warmup_cycles:
            workload = config.warmup_workload
        elif not config.pulsed:
            workload = config.disturbance_workload
        else:
            cycle_in_period = (cycle - config.warmup_cycles) % config.pulse_period
            pulse_on_cycles = int(config.pulse_period * config.pulse_duty)

            if cycle_in_period < pulse_on_cycles:
                workload = config.disturbance_workload
            else:
                workload = config.warmup_workload

        return PlantInputs(heater_duty=0.0, workload_frac=workload, dt_s=config.dt_s)

    return schedule
