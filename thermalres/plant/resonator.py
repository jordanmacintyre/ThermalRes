from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResonatorParams:
    """
    Parameters for the photonic resonator model.

    The resonator wavelength shifts with temperature due to the thermo-optic effect.
    The device is considered "locked" when its resonance is within a tolerance window
    of the target laser wavelength.
    """
    lambda0_nm: float              # Nominal resonance wavelength at ambient (nm)
    thermo_optic_nm_per_c: float   # Thermo-optic coefficient (nm/°C)
    lock_window_nm: float          # Lock tolerance (±nm around target)
    target_lambda_nm: float        # Target laser wavelength (nm)
    ambient_c: float               # Ambient temperature (°C)


@dataclass(frozen=True, slots=True)
class ResonatorOutputs:
    """
    Outputs from the resonator model.
    """
    resonance_nm: float            # Current resonance wavelength (nm)
    detune_nm: float               # Detuning: target - resonance (signed, nm)
    locked: bool                   # True if |detune| <= lock_window


def eval_resonator(temp_c: float, p: ResonatorParams) -> ResonatorOutputs:
    """
    Evaluate the resonator model at a given temperature.

    The resonance wavelength shifts linearly with temperature:
        λ_res = λ0 + α * (T - T_ambient)

    The system is locked when:
        |λ_target - λ_res| <= lock_window

    Args:
        temp_c: Current temperature (°C)
        p: Resonator parameters

    Returns:
        ResonatorOutputs with resonance, detuning, and lock status
    """
    # Calculate temperature-dependent resonance shift
    temp_delta = temp_c - p.ambient_c
    resonance_nm = p.lambda0_nm + p.thermo_optic_nm_per_c * temp_delta

    # Calculate detuning (signed: positive means laser is above resonance)
    detune_nm = p.target_lambda_nm - resonance_nm

    # Check if locked (within tolerance window)
    locked = abs(detune_nm) <= p.lock_window_nm

    return ResonatorOutputs(
        resonance_nm=resonance_nm,
        detune_nm=detune_nm,
        locked=locked,
    )
