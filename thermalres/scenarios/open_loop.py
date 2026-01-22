from __future__ import annotations

from typing import Callable

from thermalres.cosim.interfaces import PlantInputs

# Default timestep for plant evaluation (seconds)
DEFAULT_DT = 0.1

# Type alias for schedule functions
Schedule = Callable[[int], PlantInputs]


def constant_heater(heater: float, workload: float = 0.0) -> Schedule:
    """
    Constant heater duty and workload schedule.

    Args:
        heater: Fixed heater duty cycle [0, 1]
        workload: Fixed workload fraction [0, 1]

    Returns:
        Schedule function: cycle -> PlantInputs
    """
    def schedule(cycle: int) -> PlantInputs:
        return PlantInputs(
            heater_duty=heater,
            workload_frac=workload,
            dt_s=DEFAULT_DT,
        )
    return schedule


def step_workload(
    heater: float = 0.0,
    workload_low: float = 0.0,
    workload_high: float = 1.0,
    step_at_cycle: int = 50,
) -> Schedule:
    """
    Step workload from low to high at a specific cycle.

    Useful for testing transient response.

    Args:
        heater: Fixed heater duty cycle [0, 1]
        workload_low: Initial workload fraction [0, 1]
        workload_high: Final workload fraction [0, 1]
        step_at_cycle: Cycle at which to step

    Returns:
        Schedule function: cycle -> PlantInputs
    """
    def schedule(cycle: int) -> PlantInputs:
        workload = workload_low if cycle < step_at_cycle else workload_high
        return PlantInputs(
            heater_duty=heater,
            workload_frac=workload,
            dt_s=DEFAULT_DT,
        )
    return schedule


def ramp_workload(
    heater: float = 0.0,
    workload_start: float = 0.0,
    workload_end: float = 1.0,
    ramp_cycles: int = 100,
) -> Schedule:
    """
    Linear ramp of workload over specified cycles.

    Args:
        heater: Fixed heater duty cycle [0, 1]
        workload_start: Initial workload fraction [0, 1]
        workload_end: Final workload fraction [0, 1]
        ramp_cycles: Number of cycles over which to ramp

    Returns:
        Schedule function: cycle -> PlantInputs
    """
    def schedule(cycle: int) -> PlantInputs:
        if cycle >= ramp_cycles:
            workload = workload_end
        else:
            # Linear interpolation
            t = cycle / ramp_cycles
            workload = workload_start + t * (workload_end - workload_start)

        return PlantInputs(
            heater_duty=heater,
            workload_frac=workload,
            dt_s=DEFAULT_DT,
        )
    return schedule


def heater_off_workload_on(
    workload: float = 0.5,
) -> Schedule:
    """
    Heater off, constant workload on.

    Useful for testing cooling behavior with fixed heat source.

    Args:
        workload: Fixed workload fraction [0, 1]

    Returns:
        Schedule function: cycle -> PlantInputs
    """
    def schedule(cycle: int) -> PlantInputs:
        return PlantInputs(
            heater_duty=0.0,
            workload_frac=workload,
            dt_s=DEFAULT_DT,
        )
    return schedule
