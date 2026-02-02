from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ThermalParams:
    """
    Parameters for the thermal RC model.

    The thermal system models heat flow from power sources (heater + workload)
    to ambient temperature through a first-order RC network.
    """
    ambient_c: float           # Ambient temperature (°C)
    r_th_c_per_w: float        # Thermal resistance (°C/W)
    c_th_j_per_c: float        # Thermal capacitance (J/°C) - treat as C in ODE
    heater_w_max: float        # Maximum heater power (W)
    workload_w_max: float      # Maximum workload power (W)


@dataclass(frozen=False, slots=True)
class ThermalState:
    """
    State of the thermal system.

    This is mutable to allow efficient state updates during simulation.
    """
    temp_c: float              # Current temperature (°C)


def step_thermal(
    state: ThermalState,
    *,
    dt_s: float,
    heater_duty: float,
    workload_frac: float,
    p: ThermalParams,
) -> ThermalState:
    """
    Step the thermal model forward by dt_s seconds using Euler integration.

    Physics:
    - Power input: P_in = heater_duty * heater_w_max + workload_frac * workload_w_max
    - First-order RC thermal model to ambient:
      dT/dt = (P_in * R_th - (T - T_ambient)) / (R_th * C_th)

    Args:
        state: Current thermal state
        dt_s: Time step in seconds
        heater_duty: Heater duty cycle [0, 1]
        workload_frac: Workload fraction [0, 1]
        p: Thermal parameters

    Returns:
        New thermal state (does not mutate input)
    """
    # Clamp inputs to valid range [0, 1]
    heater_duty = max(0.0, min(1.0, heater_duty))
    workload_frac = max(0.0, min(1.0, workload_frac))

    # Convert duty cycles to power (Watts)
    heater_w = heater_duty * p.heater_w_max
    workload_w = workload_frac * p.workload_w_max
    p_in = heater_w + workload_w

    # First-order RC thermal dynamics:
    # dT/dt = (P_in * R_th - (T - T_amb)) / (R_th * C_th)
    # This can be rewritten as:
    # dT/dt = (P_in * R_th + T_amb - T) / (R_th * C_th)

    temp_delta_from_ambient = state.temp_c - p.ambient_c
    numerator = p_in * p.r_th_c_per_w - temp_delta_from_ambient
    denominator = p.r_th_c_per_w * p.c_th_j_per_c

    dt_dt = numerator / denominator

    # Euler integration: sufficient for slow thermal dynamics where τ = R*C >> dt_s
    # (typical τ ~ 1-10 seconds, dt_s ~ 0.1 seconds)
    temp_next = state.temp_c + dt_s * dt_dt

    return ThermalState(temp_c=temp_next)
