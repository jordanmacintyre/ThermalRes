from __future__ import annotations

from dataclasses import dataclass

from thermalres.control.interfaces import ControlInputs, ControlOutputs


@dataclass
class BangBangParams:
    """
    Parameters for bang-bang controller.
    """
    detune_deadband_nm: float = 0.1      # Deadband around target (nm)
    step_size: float = 0.05              # Duty cycle step per adjustment
    min_duty: float = 0.0                # Minimum heater duty
    max_duty: float = 1.0                # Maximum heater duty
    unlock_boost: float = 0.2            # Extra boost when unlocked


class BangBangController:
    """
    Bang-bang controller for thermal lock maintenance.

    Control law:
    - If unlocked or detune too negative: increase heater (add heat)
    - If detune too positive: decrease heater (reduce heat)
    - Else: hold current duty

    The controller is stateful (remembers last duty) but deterministic.
    """

    def __init__(self, params: BangBangParams | None = None):
        """
        Initialize bang-bang controller.

        Args:
            params: Controller parameters (uses defaults if None)
        """
        self.params = params or BangBangParams()
        self._current_duty: float = 0.0

    def reset(self) -> None:
        """Reset controller state."""
        self._current_duty = 0.0

    def step(self, inputs: ControlInputs) -> ControlOutputs:
        """
        Compute bang-bang control output.

        Args:
            inputs: Current observations and targets

        Returns:
            ControlOutputs with commanded heater duty
        """
        error = inputs.detune_nm - inputs.detune_target_nm

        # If unlocked, aggressively increase heater
        if not inputs.locked:
            self._current_duty += self.params.step_size + self.params.unlock_boost
        # If detune is too negative (resonance > target), increase heater to shift up
        elif error < -self.params.detune_deadband_nm:
            self._current_duty += self.params.step_size
        # If detune is too positive (resonance < target), decrease heater
        elif error > self.params.detune_deadband_nm:
            self._current_duty -= self.params.step_size
        # Else: within deadband, hold current duty

        # Clamp to valid range
        self._current_duty = max(self.params.min_duty,
                                 min(self.params.max_duty, self._current_duty))

        return ControlOutputs(
            heater_duty=self._current_duty,
            error=error,
        )
