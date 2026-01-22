from __future__ import annotations

import pytest

from thermalres.plant.impairment import ImpairmentParams, eval_impairment


@pytest.fixture
def default_params() -> ImpairmentParams:
    """Default impairment parameters for testing."""
    return ImpairmentParams(
        detune_50_nm=0.3,
        detune_floor_nm=0.0,
        detune_ceil_nm=1.0,
    )


def test_impairment_params_initialization():
    """Test that impairment params can be initialized."""
    params = ImpairmentParams(
        detune_50_nm=0.3,
        detune_floor_nm=0.0,
        detune_ceil_nm=1.0,
    )
    assert params.detune_50_nm == 0.3
    assert params.detune_floor_nm == 0.0


def test_impairment_unlocked_always_fails(default_params):
    """
    When not locked, CRC failure probability should always be 1.0.
    """
    # Test various detuning values when unlocked
    test_detunes = [0.0, 0.1, 0.5, 1.0, 10.0]

    for detune in test_detunes:
        outputs = eval_impairment(
            detune_nm=detune,
            locked=False,
            p=default_params,
        )
        assert outputs.crc_fail_prob == 1.0


def test_impairment_locked_zero_detune_no_fail(default_params):
    """
    When locked with zero detuning, failure probability should be near zero.
    """
    outputs = eval_impairment(
        detune_nm=0.0,
        locked=True,
        p=default_params,
    )
    assert outputs.crc_fail_prob == 0.0


def test_impairment_at_floor_no_fail(default_params):
    """
    At or below detune_floor, failure probability should be 0.
    """
    outputs = eval_impairment(
        detune_nm=default_params.detune_floor_nm,
        locked=True,
        p=default_params,
    )
    assert outputs.crc_fail_prob == 0.0


def test_impairment_at_ceil_always_fails(default_params):
    """
    At or above detune_ceil, failure probability should be 1.0.
    """
    outputs = eval_impairment(
        detune_nm=default_params.detune_ceil_nm,
        locked=True,
        p=default_params,
    )
    assert outputs.crc_fail_prob == 1.0

    # Test above ceiling
    outputs_above = eval_impairment(
        detune_nm=default_params.detune_ceil_nm + 0.5,
        locked=True,
        p=default_params,
    )
    assert outputs_above.crc_fail_prob == 1.0


def test_impairment_at_50_point_approximately_half(default_params):
    """
    At detune_50_nm, failure probability should be approximately 0.5.
    """
    outputs = eval_impairment(
        detune_nm=default_params.detune_50_nm,
        locked=True,
        p=default_params,
    )

    # Should be close to 0.5 (within 10%)
    assert 0.4 < outputs.crc_fail_prob < 0.6


def test_impairment_monotonic_increase(default_params):
    """
    As |detune| increases, failure probability should be non-decreasing.
    """
    # Sample many points from floor to ceil
    detune_values = [i * 0.05 for i in range(21)]  # 0.0 to 1.0 in steps of 0.05
    probs = []

    for detune in detune_values:
        outputs = eval_impairment(
            detune_nm=detune,
            locked=True,
            p=default_params,
        )
        probs.append(outputs.crc_fail_prob)

    # Check monotonic non-decreasing
    for i in range(len(probs) - 1):
        assert probs[i] <= probs[i + 1], f"Non-monotonic at index {i}: {probs[i]} > {probs[i+1]}"


def test_impairment_symmetric_detune(default_params):
    """
    Positive and negative detuning of same magnitude should give same probability.
    """
    detune_positive = 0.5
    detune_negative = -0.5

    outputs_pos = eval_impairment(
        detune_nm=detune_positive,
        locked=True,
        p=default_params,
    )

    outputs_neg = eval_impairment(
        detune_nm=detune_negative,
        locked=True,
        p=default_params,
    )

    assert abs(outputs_pos.crc_fail_prob - outputs_neg.crc_fail_prob) < 1e-9


def test_impairment_always_clamped(default_params):
    """
    Failure probability should always be in [0, 1].
    """
    # Test extreme values
    test_detunes = [-10.0, -1.0, 0.0, 0.5, 1.0, 10.0]

    for detune in test_detunes:
        outputs = eval_impairment(
            detune_nm=detune,
            locked=True,
            p=default_params,
        )
        assert 0.0 <= outputs.crc_fail_prob <= 1.0


def test_impairment_smooth_curve():
    """
    Test that the probability curve is smooth (no sudden jumps).
    """
    params = ImpairmentParams(
        detune_50_nm=0.5,
        detune_floor_nm=0.0,
        detune_ceil_nm=1.0,
    )

    # Sample finely
    detune_values = [i * 0.01 for i in range(101)]  # 0.0 to 1.0 in steps of 0.01
    probs = []

    for detune in detune_values:
        outputs = eval_impairment(
            detune_nm=detune,
            locked=True,
            p=params,
        )
        probs.append(outputs.crc_fail_prob)

    # Check that consecutive differences are small (smooth)
    for i in range(len(probs) - 1):
        diff = abs(probs[i + 1] - probs[i])
        assert diff < 0.1, f"Large jump at index {i}: {diff}"


def test_impairment_below_floor_clamped():
    """
    Test that detuning below floor gives zero probability.
    """
    params = ImpairmentParams(
        detune_50_nm=0.5,
        detune_floor_nm=0.2,
        detune_ceil_nm=1.0,
    )

    outputs = eval_impairment(
        detune_nm=0.1,  # Below floor
        locked=True,
        p=params,
    )
    assert outputs.crc_fail_prob == 0.0


def test_impairment_above_ceil_clamped():
    """
    Test that detuning above ceiling gives probability of 1.0.
    """
    params = ImpairmentParams(
        detune_50_nm=0.5,
        detune_floor_nm=0.0,
        detune_ceil_nm=0.8,
    )

    outputs = eval_impairment(
        detune_nm=1.5,  # Above ceiling
        locked=True,
        p=params,
    )
    assert outputs.crc_fail_prob == 1.0


def test_impairment_gradient_near_50_point():
    """
    Test that the curve has reasonable gradient around the 50% point.
    """
    params = ImpairmentParams(
        detune_50_nm=0.5,
        detune_floor_nm=0.0,
        detune_ceil_nm=1.0,
    )

    # Sample around the 50% point
    outputs_below = eval_impairment(detune_nm=0.4, locked=True, p=params)
    outputs_at = eval_impairment(detune_nm=0.5, locked=True, p=params)
    outputs_above = eval_impairment(detune_nm=0.6, locked=True, p=params)

    # Should be increasing
    assert outputs_below.crc_fail_prob < outputs_at.crc_fail_prob
    assert outputs_at.crc_fail_prob < outputs_above.crc_fail_prob


def test_impairment_outputs_immutability():
    """
    Test that outputs are immutable (frozen dataclass).
    """
    params = ImpairmentParams(
        detune_50_nm=0.3,
        detune_floor_nm=0.0,
        detune_ceil_nm=1.0,
    )

    outputs = eval_impairment(detune_nm=0.5, locked=True, p=params)

    # Should not be able to modify
    with pytest.raises(Exception):  # FrozenInstanceError
        outputs.crc_fail_prob = 0.9  # type: ignore


def test_impairment_full_range_coverage():
    """
    Test that the curve covers the full [0, 1] range.
    """
    params = ImpairmentParams(
        detune_50_nm=0.5,
        detune_floor_nm=0.0,
        detune_ceil_nm=1.0,
    )

    # At floor
    outputs_min = eval_impairment(detune_nm=0.0, locked=True, p=params)
    assert outputs_min.crc_fail_prob == 0.0

    # At ceiling
    outputs_max = eval_impairment(detune_nm=1.0, locked=True, p=params)
    assert outputs_max.crc_fail_prob == 1.0

    # Check that we visit intermediate values
    mid_range_probs = []
    for detune in [0.2, 0.4, 0.6, 0.8]:
        outputs = eval_impairment(detune_nm=detune, locked=True, p=params)
        mid_range_probs.append(outputs.crc_fail_prob)

    # All should be in (0, 1)
    for prob in mid_range_probs:
        assert 0.0 < prob < 1.0
