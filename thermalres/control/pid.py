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
    Incremental PID controller for detune regulation.

    Control law:
        Δu = kp*e + ki*∫e + kd*de/dt
        u(t) = u(t-1) + Δu

    Where e = detune_error = (detune_nm - target_nm)

    The controller is incremental to maintain operating point at steady-state.
    This allows the controller to track nonzero setpoints with sustained
    disturbances (e.g., workload power).

    Features:
    - Incremental output (maintains baseline duty)
    - Anti-windup on integrator
    - Directional unlock boost
    - Output clamping
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
        self._duty: float = 0.0

    def reset(self) -> None:
        """Reset controller state."""
        self._integrator = 0.0
        self._last_error = 0.0
        self._duty = 0.0

    def step(self, inputs: ControlInputs) -> ControlOutputs:
        """
        Compute PID control output.

        Args:
            inputs: Current observations and targets

        Returns:
            ControlOutputs with commanded heater duty
        """
        # Calculate error (detune - target)
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

        # Compute incremental change (delta)
        delta = p_term + i_term + d_term

        # Update internal duty state
        self._duty += delta

        # Add directional unlock boost if needed
        if not inputs.locked:
            # Boost in the direction that corrects the error
            # If error > 0: detune is too positive (resonance too high), need more heat
            # If error < 0: detune is too negative (resonance too low), need less heat
            boost_direction = 1.0 if error > 0 else -1.0
            self._duty += self.params.unlock_boost * boost_direction

        # Clamp to valid range
        self._duty = max(self.params.min_duty,
                        min(self.params.max_duty, self._duty))

        # Store for next iteration
        self._last_error = error

        return ControlOutputs(
            heater_duty=self._duty,
            error=error,
        )
