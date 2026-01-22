from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ControlInputs:
    """
    Inputs to a controller.

    Controllers receive observations from the plant and a desired target.
    They do not know about cycles, chunks, or kernel mechanics.
    """
    dt_s: float                     # Time step (seconds)
    # Observations
    temp_c: float                   # Current temperature (°C)
    detune_nm: float                # Current detuning (nm, signed)
    locked: bool                    # Current lock status
    crc_fail_prob: float            # Current CRC failure probability [0, 1]
    # References/targets
    detune_target_nm: float = 0.0   # Desired detuning (nm), default 0 = on resonance


@dataclass(frozen=True, slots=True)
class ControlOutputs:
    """
    Outputs from a controller.

    Controllers produce a heater duty cycle command.
    """
    heater_duty: float              # Commanded heater duty cycle [0, 1]
    error: float = 0.0              # Control error for logging/debugging


class Controller(Protocol):
    """
    Protocol for controllers.

    Controllers implement a control law that maps plant observations
    to heater duty commands. They maintain internal state (e.g., integrator)
    but are deterministic and resettable.
    """

    def reset(self) -> None:
        """Reset controller internal state."""
        ...

    def step(self, inputs: ControlInputs) -> ControlOutputs:
        """
        Compute control output for current inputs.

        Args:
            inputs: Current observations and targets

        Returns:
            ControlOutputs with commanded heater duty and error
        """
        ...
