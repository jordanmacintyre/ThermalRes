from __future__ import annotations

from dataclasses import dataclass

from thermalres.control.interfaces import ControlInputs, ControlOutputs


@dataclass
class PIDParams:
    """
    Parameters for PID controller.
    """
    kp: float = 0.05                # Proportional gain
    ki: float = 0.001               # Integral gain
    kd: float = 0.01                # Derivative gain
    min_duty: float = 0.0           # Minimum heater duty
    max_duty: float = 1.0           # Maximum heater duty
    integrator_min: float = -10.0   # Anti-windup: min integrator value
    integrator_max: float = 10.0    # Anti-windup: max integrator value
    unlock_boost: float = 0.1       # Extra boost when unlocked


class PIDController:
    """
    Positional PID controller for detune regulation.

    Control law:
        u = bias + kp*e + ki*∫e + kd*de/dt

    Where e = detune_error = (detune_nm - target_nm)

    Sign convention for heat-only control:
    - Positive detune: target > resonance → resonator cold → need MORE heat
    - Negative detune: target < resonance → resonator hot → need LESS heat

    Features:
    - Positional output (direct response to error)
    - Anti-windup on integrator
    - Configurable bias for operating point
    - Output clamping to [0, 1]
    """

    def __init__(self, params: PIDParams | None = None):
        """
        Initialize PID controller.

        Args:
            params: Controller parameters (uses defaults if None)
        """
        self.params = params or PIDParams()
        self._integrator: float = 0.0
        self._last_error: float = 0.0

    def reset(self) -> None:
        """Reset controller state."""
        self._integrator = 0.0
        self._last_error = 0.0

    def step(self, inputs: ControlInputs) -> ControlOutputs:
        """
        Compute PID control output.

        Args:
            inputs: Current observations and targets

        Returns:
            ControlOutputs with commanded heater duty
        """
        # Calculate error: positive means resonator is cold, need more heat
        # detune = target - resonance (from resonator model)
        # error = detune - target_detune = detune when target_detune = 0
        error = inputs.detune_nm - inputs.detune_target_nm

        # Proportional term
        p_term = self.params.kp * error

        # Integral term with anti-windup
        self._integrator += error * inputs.dt_s
        self._integrator = max(self.params.integrator_min,
                              min(self.params.integrator_max, self._integrator))
        i_term = self.params.ki * self._integrator

        # Derivative term
        if inputs.dt_s > 0:
            d_error = (error - self._last_error) / inputs.dt_s
        else:
            d_error = 0.0
        d_term = self.params.kd * d_error

        # Compute output directly (positional form)
        # Bias provides a baseline operating point
        duty = self.params.unlock_boost + p_term + i_term + d_term

        # Clamp to valid range [0, 1]
        duty = max(self.params.min_duty, min(self.params.max_duty, duty))

        # Store for next iteration
        self._last_error = error

        return ControlOutputs(
            heater_duty=duty,
            error=error,
        )
