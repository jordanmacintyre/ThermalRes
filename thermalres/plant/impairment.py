from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ImpairmentParams:
    """
    Parameters for the link impairment model.

    Maps detuning magnitude to CRC failure probability using a smooth curve.
    When not locked, the failure probability is always 1.0.
    """
    detune_50_nm: float        # Detuning magnitude where p_fail ≈ 0.5
    detune_floor_nm: float     # Below this, p_fail ≈ 0
    detune_ceil_nm: float      # Above this, p_fail ≈ 1


@dataclass(frozen=True, slots=True)
class ImpairmentOutputs:
    """
    Outputs from the impairment model.
    """
    crc_fail_prob: float       # CRC failure probability [0, 1]


def eval_impairment(
    detune_nm: float,
    locked: bool,
    p: ImpairmentParams,
) -> ImpairmentOutputs:
    """
    Evaluate the impairment model given detuning and lock status.

    When not locked, CRC failure probability is 1.0.
    When locked, the failure probability is a smooth function of |detune|:
    - Near zero detuning: p_fail ≈ 0
    - At detune_50_nm: p_fail ≈ 0.5
    - At large detuning: p_fail → 1

    The mapping uses a cubic smoothstep function centered around detune_50_nm.

    Args:
        detune_nm: Detuning (signed, nm)
        locked: Whether resonator is locked
        p: Impairment parameters

    Returns:
        ImpairmentOutputs with CRC failure probability
    """
    if not locked:
        return ImpairmentOutputs(crc_fail_prob=1.0)

    # Work with absolute detuning
    abs_detune = abs(detune_nm)

    # Map detuning to normalized coordinate
    # We want detune_floor -> 0, detune_ceil -> 1
    # But we also want detune_50 to map to 0.5
    # Simple approach: normalize to [floor, ceil] range, then adjust

    if abs_detune <= p.detune_floor_nm:
        return ImpairmentOutputs(crc_fail_prob=0.0)

    if abs_detune >= p.detune_ceil_nm:
        return ImpairmentOutputs(crc_fail_prob=1.0)

    # Normalize to [0, 1] based on floor/ceil range
    x = (abs_detune - p.detune_floor_nm) / (p.detune_ceil_nm - p.detune_floor_nm)
    x = max(0.0, min(1.0, x))

    # To center around detune_50, we need to adjust the mapping
    # Calculate where detune_50 falls in the normalized range
    x_50 = (p.detune_50_nm - p.detune_floor_nm) / (p.detune_ceil_nm - p.detune_floor_nm)
    x_50 = max(0.0, min(1.0, x_50))

    # Piecewise linear remapping to use 50% exactly.
    # Without this, a detune_50_nm that's not centered in [floor, ceil] would
    # not produce 0.5 probability. This ensures detune_50_nm always maps to 0.5.
    #
    # Example: floor=0.0, ceil=0.1, detune_50=0.03
    #   Input 0.03nm → x=0.3 → x_50=0.3 → rescaled to x_norm=0.5 → smoothstep(0.5)=0.5
    if x_50 > 0.0 and x_50 < 1.0:
        # Piecewise rescaling:
        # - [0, x_50] maps to [0, 0.5]
        # - [x_50, 1] maps to [0.5, 1]
        if x <= x_50:
            x_norm = 0.5 * (x / x_50) if x_50 > 0 else 0.0
        else:
            x_norm = 0.5 + 0.5 * ((x - x_50) / (1.0 - x_50)) if x_50 < 1 else 1.0
    else:
        x_norm = x

    # Apply cubic smoothstep: s(t) = t^2 * (3 - 2*t)
    s = x_norm * x_norm * (3.0 - 2.0 * x_norm)

    # Clamp to [0, 1] for safety
    crc_fail_prob = max(0.0, min(1.0, s))

    return ImpairmentOutputs(crc_fail_prob=crc_fail_prob)
