from __future__ import annotations

import pytest

from thermalres.plant.thermal import ThermalParams, ThermalState, step_thermal


@pytest.fixture
def default_params() -> ThermalParams:
    """Default thermal parameters for testing."""
    return ThermalParams(
        ambient_c=25.0,
        r_th_c_per_w=10.0,
        c_th_j_per_c=0.1,
        heater_w_max=1.0,
        workload_w_max=0.5,
    )


def test_thermal_state_initialization():
    """Test that thermal state can be initialized."""
    state = ThermalState(temp_c=25.0)
    assert state.temp_c == 25.0


def test_thermal_params_initialization():
    """Test that thermal params can be initialized."""
    params = ThermalParams(
        ambient_c=25.0,
        r_th_c_per_w=10.0,
        c_th_j_per_c=0.1,
        heater_w_max=1.0,
        workload_w_max=0.5,
    )
    assert params.ambient_c == 25.0
    assert params.r_th_c_per_w == 10.0


def test_thermal_no_power_moves_toward_ambient(default_params):
    """
    With no power input and temp above ambient, temperature should decrease
    toward ambient.
    """
    state = ThermalState(temp_c=35.0)  # 10°C above ambient
    dt_s = 0.01

    # Step forward with no power
    new_state = step_thermal(
        state,
        dt_s=dt_s,
        heater_duty=0.0,
        workload_frac=0.0,
        p=default_params,
    )

    # Temperature should decrease toward ambient
    assert new_state.temp_c < state.temp_c
    assert new_state.temp_c > default_params.ambient_c


def test_thermal_repeated_steps_toward_ambient(default_params):
    """
    Repeated steps with no power should monotonically approach ambient.
    """
    state = ThermalState(temp_c=40.0)
    dt_s = 0.01

    temps = [state.temp_c]
    for _ in range(500):  # More steps to reach closer to ambient
        state = step_thermal(
            state,
            dt_s=dt_s,
            heater_duty=0.0,
            workload_frac=0.0,
            p=default_params,
        )
        temps.append(state.temp_c)

    # Should be monotonically decreasing
    for i in range(len(temps) - 1):
        assert temps[i] >= temps[i + 1]

    # Should approach ambient (within 10% of initial delta)
    assert abs(state.temp_c - default_params.ambient_c) < 3.0


def test_thermal_heater_increases_temperature(default_params):
    """
    Applying heater power should increase temperature above baseline.
    """
    state_ambient = ThermalState(temp_c=default_params.ambient_c)
    dt_s = 0.01
    n_steps = 50

    # Run with no heater
    state_no_heater = state_ambient
    for _ in range(n_steps):
        state_no_heater = step_thermal(
            state_no_heater,
            dt_s=dt_s,
            heater_duty=0.0,
            workload_frac=0.0,
            p=default_params,
        )

    # Run with heater at 50%
    state_with_heater = state_ambient
    for _ in range(n_steps):
        state_with_heater = step_thermal(
            state_with_heater,
            dt_s=dt_s,
            heater_duty=0.5,
            workload_frac=0.0,
            p=default_params,
        )

    # With heater should be warmer
    assert state_with_heater.temp_c > state_no_heater.temp_c
    assert state_with_heater.temp_c > default_params.ambient_c


def test_thermal_workload_increases_temperature(default_params):
    """
    Applying workload power should increase temperature.
    """
    state = ThermalState(temp_c=default_params.ambient_c)
    dt_s = 0.01
    n_steps = 50

    # Run with workload
    for _ in range(n_steps):
        state = step_thermal(
            state,
            dt_s=dt_s,
            heater_duty=0.0,
            workload_frac=1.0,
            p=default_params,
        )

    # Should be above ambient
    assert state.temp_c > default_params.ambient_c


def test_thermal_steady_state_approximation(default_params):
    """
    At steady state with constant power, temperature should approximately
    equal ambient + P * R_th.
    """
    state = ThermalState(temp_c=default_params.ambient_c)
    dt_s = 0.001  # Small timestep for accuracy
    heater_duty = 0.5
    n_steps = 5000  # Many steps to reach steady state

    for _ in range(n_steps):
        state = step_thermal(
            state,
            dt_s=dt_s,
            heater_duty=heater_duty,
            workload_frac=0.0,
            p=default_params,
        )

    # Expected steady-state temperature
    p_in = heater_duty * default_params.heater_w_max
    expected_temp = default_params.ambient_c + p_in * default_params.r_th_c_per_w

    # Should be within 5% of expected
    assert abs(state.temp_c - expected_temp) < 0.05 * expected_temp


def test_thermal_higher_power_higher_steady_state(default_params):
    """
    Higher power input should lead to higher steady-state temperature.
    """
    dt_s = 0.001
    n_steps = 5000

    # Low power case
    state_low = ThermalState(temp_c=default_params.ambient_c)
    for _ in range(n_steps):
        state_low = step_thermal(
            state_low,
            dt_s=dt_s,
            heater_duty=0.2,
            workload_frac=0.0,
            p=default_params,
        )

    # High power case
    state_high = ThermalState(temp_c=default_params.ambient_c)
    for _ in range(n_steps):
        state_high = step_thermal(
            state_high,
            dt_s=dt_s,
            heater_duty=0.8,
            workload_frac=0.0,
            p=default_params,
        )

    assert state_high.temp_c > state_low.temp_c


def test_thermal_input_clamping():
    """
    Test that heater_duty and workload_frac are clamped to [0, 1].
    """
    params = ThermalParams(
        ambient_c=25.0,
        r_th_c_per_w=10.0,
        c_th_j_per_c=0.1,
        heater_w_max=1.0,
        workload_w_max=1.0,
    )
    state = ThermalState(temp_c=25.0)
    dt_s = 0.01

    # Test with values > 1 (should clamp to 1)
    state_clamped_high = step_thermal(
        state,
        dt_s=dt_s,
        heater_duty=2.0,
        workload_frac=3.0,
        p=params,
    )

    state_normal = step_thermal(
        state,
        dt_s=dt_s,
        heater_duty=1.0,
        workload_frac=1.0,
        p=params,
    )

    # Should produce same result
    assert abs(state_clamped_high.temp_c - state_normal.temp_c) < 1e-9

    # Test with values < 0 (should clamp to 0)
    state_clamped_low = step_thermal(
        state,
        dt_s=dt_s,
        heater_duty=-1.0,
        workload_frac=-2.0,
        p=params,
    )

    state_zero = step_thermal(
        state,
        dt_s=dt_s,
        heater_duty=0.0,
        workload_frac=0.0,
        p=params,
    )

    # Should produce same result
    assert abs(state_clamped_low.temp_c - state_zero.temp_c) < 1e-9


def test_thermal_state_immutability(default_params):
    """
    Test that step_thermal returns a new state without mutating the input.
    """
    original_temp = 25.0  # Start at ambient
    state = ThermalState(temp_c=original_temp)

    new_state = step_thermal(
        state,
        dt_s=1.0,  # Larger timestep to ensure visible change
        heater_duty=0.8,  # High power to ensure temp change
        workload_frac=0.0,
        p=default_params,
    )

    # Original should be unchanged
    assert state.temp_c == original_temp
    # New state should be different
    assert new_state.temp_c != original_temp
    # Should be different objects
    assert new_state is not state


def test_thermal_combined_heater_workload(default_params):
    """
    Test that heater and workload powers combine additively.
    """
    state = ThermalState(temp_c=default_params.ambient_c)
    dt_s = 0.01
    n_steps = 100

    # Only heater
    state_heater = state
    for _ in range(n_steps):
        state_heater = step_thermal(
            state_heater,
            dt_s=dt_s,
            heater_duty=0.5,
            workload_frac=0.0,
            p=default_params,
        )

    # Only workload (scaled to match heater power)
    # heater: 0.5 * 1.0W = 0.5W
    # workload: 1.0 * 0.5W = 0.5W
    state_workload = state
    for _ in range(n_steps):
        state_workload = step_thermal(
            state_workload,
            dt_s=dt_s,
            heater_duty=0.0,
            workload_frac=1.0,
            p=default_params,
        )

    # Should be approximately equal (same total power)
    assert abs(state_heater.temp_c - state_workload.temp_c) < 0.5
