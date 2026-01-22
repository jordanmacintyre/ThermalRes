from __future__ import annotations

import pytest

from thermalres.plant.resonator import ResonatorParams, eval_resonator


@pytest.fixture
def default_params() -> ResonatorParams:
    """Default resonator parameters for testing."""
    return ResonatorParams(
        lambda0_nm=1550.0,
        thermo_optic_nm_per_c=0.1,
        lock_window_nm=0.5,
        target_lambda_nm=1550.0,
        ambient_c=25.0,
    )


def test_resonator_params_initialization():
    """Test that resonator params can be initialized."""
    params = ResonatorParams(
        lambda0_nm=1550.0,
        thermo_optic_nm_per_c=0.1,
        lock_window_nm=0.5,
        target_lambda_nm=1550.0,
        ambient_c=25.0,
    )
    assert params.lambda0_nm == 1550.0
    assert params.thermo_optic_nm_per_c == 0.1


def test_resonator_at_ambient_matches_lambda0(default_params):
    """
    At ambient temperature, resonance should equal nominal wavelength.
    """
    outputs = eval_resonator(temp_c=default_params.ambient_c, p=default_params)

    assert outputs.resonance_nm == default_params.lambda0_nm


def test_resonator_temp_increase_shifts_resonance(default_params):
    """
    Increasing temperature should shift resonance according to thermo-optic coefficient.
    """
    temp_delta = 10.0  # 10°C above ambient
    temp_c = default_params.ambient_c + temp_delta

    outputs = eval_resonator(temp_c=temp_c, p=default_params)

    expected_shift = default_params.thermo_optic_nm_per_c * temp_delta
    expected_resonance = default_params.lambda0_nm + expected_shift

    assert abs(outputs.resonance_nm - expected_resonance) < 1e-9


def test_resonator_temp_decrease_shifts_resonance(default_params):
    """
    Decreasing temperature should shift resonance in opposite direction.
    """
    temp_delta = -5.0  # 5°C below ambient
    temp_c = default_params.ambient_c + temp_delta

    outputs = eval_resonator(temp_c=temp_c, p=default_params)

    expected_shift = default_params.thermo_optic_nm_per_c * temp_delta
    expected_resonance = default_params.lambda0_nm + expected_shift

    assert abs(outputs.resonance_nm - expected_resonance) < 1e-9


def test_resonator_locked_at_target(default_params):
    """
    When resonance equals target, device should be locked.
    """
    # At ambient, resonance = lambda0 = target
    outputs = eval_resonator(temp_c=default_params.ambient_c, p=default_params)

    assert outputs.locked is True
    assert outputs.detune_nm == 0.0


def test_resonator_locked_within_window(default_params):
    """
    Device should remain locked as long as detuning is within lock window.
    """
    # Shift temperature slightly to create small detuning
    # detune = 0.3 nm, lock_window = 0.5 nm -> should be locked
    temp_shift = 3.0  # 3°C * 0.1 nm/°C = 0.3 nm shift
    temp_c = default_params.ambient_c + temp_shift

    outputs = eval_resonator(temp_c=temp_c, p=default_params)

    assert abs(outputs.detune_nm) < default_params.lock_window_nm
    assert outputs.locked is True


def test_resonator_unlocked_outside_window(default_params):
    """
    Device should unlock when detuning exceeds lock window.
    """
    # Create large detuning
    # detune = 1.0 nm, lock_window = 0.5 nm -> should be unlocked
    temp_shift = 10.0  # 10°C * 0.1 nm/°C = 1.0 nm shift
    temp_c = default_params.ambient_c + temp_shift

    outputs = eval_resonator(temp_c=temp_c, p=default_params)

    assert abs(outputs.detune_nm) > default_params.lock_window_nm
    assert outputs.locked is False


def test_resonator_detune_sign_convention(default_params):
    """
    Test that detune sign convention is correct: detune = target - resonance.

    If temp increases, resonance increases, so detune becomes negative.
    If temp decreases, resonance decreases, so detune becomes positive.
    """
    # Temp increase -> resonance increases -> target < resonance -> detune < 0
    outputs_hot = eval_resonator(
        temp_c=default_params.ambient_c + 10.0,
        p=default_params,
    )
    assert outputs_hot.detune_nm < 0.0

    # Temp decrease -> resonance decreases -> target > resonance -> detune > 0
    outputs_cold = eval_resonator(
        temp_c=default_params.ambient_c - 10.0,
        p=default_params,
    )
    assert outputs_cold.detune_nm > 0.0


def test_resonator_lock_boundary_positive():
    """
    Test lock/unlock boundary on positive detune side.
    """
    params = ResonatorParams(
        lambda0_nm=1550.0,
        thermo_optic_nm_per_c=0.1,
        lock_window_nm=0.5,
        target_lambda_nm=1551.0,  # Target above lambda0
        ambient_c=25.0,
    )

    # At ambient: resonance = 1550, target = 1551, detune = +1.0 -> unlocked
    outputs_unlocked = eval_resonator(temp_c=25.0, p=params)
    assert outputs_unlocked.locked is False

    # Heat to bring resonance closer to target
    # resonance = 1550 + 0.1 * 5 = 1550.5, detune = 1551 - 1550.5 = +0.5 -> at boundary
    outputs_boundary = eval_resonator(temp_c=30.0, p=params)
    assert outputs_boundary.locked is True  # Exactly at boundary

    # Heat more to get within window
    # resonance = 1550 + 0.1 * 7 = 1550.7, detune = 1551 - 1550.7 = +0.3 -> locked
    outputs_locked = eval_resonator(temp_c=32.0, p=params)
    assert outputs_locked.locked is True


def test_resonator_lock_boundary_negative():
    """
    Test lock/unlock boundary on negative detune side.
    """
    params = ResonatorParams(
        lambda0_nm=1550.0,
        thermo_optic_nm_per_c=0.1,
        lock_window_nm=0.5,
        target_lambda_nm=1549.0,  # Target below lambda0
        ambient_c=25.0,
    )

    # At ambient: resonance = 1550, target = 1549, detune = -1.0 -> unlocked
    outputs_unlocked = eval_resonator(temp_c=25.0, p=params)
    assert outputs_unlocked.locked is False

    # Cool to bring resonance closer to target
    # resonance = 1550 + 0.1 * (-5) = 1549.5, detune = 1549 - 1549.5 = -0.5 -> at boundary
    outputs_boundary = eval_resonator(temp_c=20.0, p=params)
    assert outputs_boundary.locked is True

    # Cool more to get within window
    # resonance = 1550 + 0.1 * (-7) = 1549.3, detune = 1549 - 1549.3 = -0.3 -> locked
    outputs_locked = eval_resonator(temp_c=18.0, p=params)
    assert outputs_locked.locked is True


def test_resonator_monotonic_shift_with_temperature():
    """
    Resonance should shift monotonically with temperature.
    """
    params = ResonatorParams(
        lambda0_nm=1550.0,
        thermo_optic_nm_per_c=0.1,
        lock_window_nm=0.5,
        target_lambda_nm=1550.0,
        ambient_c=25.0,
    )

    temperatures = [20.0, 25.0, 30.0, 35.0, 40.0]
    resonances = []

    for temp in temperatures:
        outputs = eval_resonator(temp_c=temp, p=params)
        resonances.append(outputs.resonance_nm)

    # Check monotonic increase
    for i in range(len(resonances) - 1):
        assert resonances[i] < resonances[i + 1]


def test_resonator_detune_calculation():
    """
    Verify that detune is always target - resonance.
    """
    params = ResonatorParams(
        lambda0_nm=1550.0,
        thermo_optic_nm_per_c=0.1,
        lock_window_nm=0.5,
        target_lambda_nm=1552.0,
        ambient_c=25.0,
    )

    temp_c = 30.0
    outputs = eval_resonator(temp_c=temp_c, p=params)

    expected_resonance = 1550.0 + 0.1 * (30.0 - 25.0)  # 1550.5
    expected_detune = 1552.0 - expected_resonance  # 1.5

    assert abs(outputs.resonance_nm - expected_resonance) < 1e-9
    assert abs(outputs.detune_nm - expected_detune) < 1e-9


def test_resonator_outputs_immutability():
    """
    Test that outputs are immutable (frozen dataclass).
    """
    params = ResonatorParams(
        lambda0_nm=1550.0,
        thermo_optic_nm_per_c=0.1,
        lock_window_nm=0.5,
        target_lambda_nm=1550.0,
        ambient_c=25.0,
    )

    outputs = eval_resonator(temp_c=25.0, p=params)

    # Should not be able to modify
    with pytest.raises(Exception):  # FrozenInstanceError
        outputs.resonance_nm = 1551.0  # type: ignore
