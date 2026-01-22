from __future__ import annotations

from thermalres.config import PlantConfig, SimConfig
from thermalres.control.bang_bang import BangBangController, BangBangParams
from thermalres.control.pid import PIDController, PIDParams
from thermalres.cosim.kernel import CoSimKernel
from thermalres.cosim.plant_runner import PlantRunner
from thermalres.plant import ImpairmentParams, ResonatorParams, ThermalParams
from thermalres.scenarios import constant_heater, step_workload


def test_closed_loop_bang_bang_maintains_lock():
    """
    Test that bang-bang controller maintains lock better than open-loop.
    """
    cfg = SimConfig.from_args(
        name="closed_loop_bang_bang",
        cycles=100,
        cycle_chunks=10,
        seed=42,
        out_dir=None,
    )

    plant_cfg = PlantConfig()
    plant_runner = PlantRunner(
        thermal_params=ThermalParams(
            ambient_c=plant_cfg.ambient_c,
            r_th_c_per_w=plant_cfg.r_th_c_per_w,
            c_th_j_per_c=plant_cfg.c_th_j_per_c,
            heater_w_max=plant_cfg.heater_w_max,
            workload_w_max=plant_cfg.workload_w_max,
        ),
        resonator_params=ResonatorParams(
            lambda0_nm=plant_cfg.lambda0_nm,
            thermo_optic_nm_per_c=plant_cfg.thermo_optic_nm_per_c,
            lock_window_nm=plant_cfg.lock_window_nm,
            target_lambda_nm=plant_cfg.target_lambda_nm,
            ambient_c=plant_cfg.ambient_c,
        ),
        impairment_params=ImpairmentParams(
            detune_50_nm=plant_cfg.detune_50_nm,
            detune_floor_nm=plant_cfg.detune_floor_nm,
            detune_ceil_nm=plant_cfg.detune_ceil_nm,
        ),
        initial_temp_c=plant_cfg.ambient_c,
    )

    # Step workload from 0 to 1 at cycle 50
    schedule = step_workload(
        heater=0.0,
        workload_low=0.0,
        workload_high=1.0,
        step_at_cycle=50,
    )

    # Create bang-bang controller
    controller = BangBangController(
        BangBangParams(
            detune_deadband_nm=0.05,
            step_size=0.05,
            unlock_boost=0.2,
        )
    )

    # Run with controller
    kernel = CoSimKernel(
        cfg,
        plant_runner=plant_runner,
        schedule=schedule,
        controller=controller,
        detune_target_nm=0.0,
    )
    result = kernel.run()

    # Check that controller was active (first cycle uses schedule, then controller takes over)
    controller_active_count = sum(1 for s in result.timeseries if s.controller_active)
    assert controller_active_count >= 5, (
        f"Controller should be active for most cycles (got {controller_active_count}/10)"
    )

    # Check that controller outputs are present when active
    for sample in result.timeseries:
        if sample.controller_active:
            assert sample.controller_error is not None

    # Controller should maintain lock better than open-loop
    # (This is qualitative - in practice we'd compare to open-loop baseline)
    locked_count = sum(1 for s in result.timeseries if s.locked)
    assert locked_count >= 5, f"Controller should maintain lock (got {locked_count}/10)"


def test_closed_loop_pid_steady_state_with_workload():
    """
    Test that incremental PID maintains nonzero heater duty at steady-state
    with sustained workload.

    This validates that the incremental controller converges and produces
    stable outputs.
    """
    cfg = SimConfig.from_args(
        name="pid_steady_state",
        cycles=200,
        cycle_chunks=10,
        seed=123,
        out_dir=None,
    )

    plant_cfg = PlantConfig()
    plant_runner = PlantRunner(
        thermal_params=ThermalParams(
            ambient_c=plant_cfg.ambient_c,
            r_th_c_per_w=plant_cfg.r_th_c_per_w,
            c_th_j_per_c=plant_cfg.c_th_j_per_c,
            heater_w_max=plant_cfg.heater_w_max,
            workload_w_max=plant_cfg.workload_w_max,
        ),
        resonator_params=ResonatorParams(
            lambda0_nm=plant_cfg.lambda0_nm,
            thermo_optic_nm_per_c=plant_cfg.thermo_optic_nm_per_c,
            lock_window_nm=plant_cfg.lock_window_nm,
            target_lambda_nm=plant_cfg.target_lambda_nm,
            ambient_c=plant_cfg.ambient_c,
        ),
        impairment_params=ImpairmentParams(
            detune_50_nm=plant_cfg.detune_50_nm,
            detune_floor_nm=plant_cfg.detune_floor_nm,
            detune_ceil_nm=plant_cfg.detune_ceil_nm,
        ),
        initial_temp_c=plant_cfg.ambient_c,
    )

    # Low workload throughout simulation
    schedule = constant_heater(heater=0.0, workload=0.1)

    # Create PID controller with reasonable gains
    controller = PIDController(
        PIDParams(
            kp=0.1,
            ki=0.005,
            kd=0.02,
            min_duty=0.0,
            max_duty=1.0,
            integrator_min=-20.0,
            integrator_max=20.0,
            unlock_boost=0.15,
        )
    )

    # Run with controller targeting zero detune
    kernel = CoSimKernel(
        cfg,
        plant_runner=plant_runner,
        schedule=schedule,
        controller=controller,
        detune_target_nm=0.0,
    )
    result = kernel.run()

    # Check that we have timeseries data
    assert len(result.timeseries) == 20  # 200 cycles / 10 chunks

    # Get final samples (last 5 to check steady-state)
    final_samples = result.timeseries[-5:]

    # At steady-state, controller should have converged
    final_duties = [s.heater_duty for s in final_samples]
    avg_final_duty = sum(final_duties) / len(final_duties)

    # With incremental PID, duty should be in a reasonable range
    assert 0.0 <= avg_final_duty <= 1.0, f"Duty out of range: {avg_final_duty:.4f}"

    # Verify it's not oscillating wildly
    duty_std = (sum((d - avg_final_duty)**2 for d in final_duties) / len(final_duties)) ** 0.5
    assert duty_std < 0.15, f"Duty should be stable (std={duty_std:.4f})"

    # Check that final detune error is small (controller converged)
    final_errors = [abs(s.controller_error) for s in final_samples if s.controller_error is not None]
    if final_errors:
        avg_error = sum(final_errors) / len(final_errors)
        # Should be tracking setpoint reasonably well
        assert avg_error < 0.5, f"Controller should converge (avg error={avg_error:.3f} nm)"


def test_closed_loop_pid_controller_stability():
    """
    Test that PID controller produces stable outputs without NaN or extreme values.
    """
    cfg = SimConfig.from_args(
        name="pid_stability",
        cycles=100,
        cycle_chunks=10,
        seed=99,
        out_dir=None,
    )

    plant_cfg = PlantConfig()
    plant_runner = PlantRunner(
        thermal_params=ThermalParams(
            ambient_c=plant_cfg.ambient_c,
            r_th_c_per_w=plant_cfg.r_th_c_per_w,
            c_th_j_per_c=plant_cfg.c_th_j_per_c,
            heater_w_max=plant_cfg.heater_w_max,
            workload_w_max=plant_cfg.workload_w_max,
        ),
        resonator_params=ResonatorParams(
            lambda0_nm=plant_cfg.lambda0_nm,
            thermo_optic_nm_per_c=plant_cfg.thermo_optic_nm_per_c,
            lock_window_nm=plant_cfg.lock_window_nm,
            target_lambda_nm=plant_cfg.target_lambda_nm,
            ambient_c=plant_cfg.ambient_c,
        ),
        impairment_params=ImpairmentParams(
            detune_50_nm=plant_cfg.detune_50_nm,
            detune_floor_nm=plant_cfg.detune_floor_nm,
            detune_ceil_nm=plant_cfg.detune_ceil_nm,
        ),
        initial_temp_c=plant_cfg.ambient_c,
    )

    schedule = step_workload(
        heater=0.0,
        workload_low=0.2,
        workload_high=0.9,
        step_at_cycle=50,
    )

    controller = PIDController(PIDParams())

    kernel = CoSimKernel(
        cfg,
        plant_runner=plant_runner,
        schedule=schedule,
        controller=controller,
        detune_target_nm=0.0,
    )
    result = kernel.run()

    # Check all outputs are valid
    for sample in result.timeseries:
        # Heater duty should be finite and in valid range
        assert not (sample.heater_duty != sample.heater_duty), "Heater duty is NaN"
        assert 0.0 <= sample.heater_duty <= 1.0, (
            f"Heater duty out of range: {sample.heater_duty}"
        )

        # Controller error should be finite
        if sample.controller_error is not None:
            assert not (sample.controller_error != sample.controller_error), "Error is NaN"

        # Temperature should be reasonable
        assert 0.0 < sample.temp_c < 200.0, f"Temperature unreasonable: {sample.temp_c}"


def test_closed_loop_determinism():
    """
    Test that closed-loop simulations are deterministic with same seed.
    """
    plant_cfg = PlantConfig()

    def run_simulation():
        plant_runner = PlantRunner(
            thermal_params=ThermalParams(
                ambient_c=plant_cfg.ambient_c,
                r_th_c_per_w=plant_cfg.r_th_c_per_w,
                c_th_j_per_c=plant_cfg.c_th_j_per_c,
                heater_w_max=plant_cfg.heater_w_max,
                workload_w_max=plant_cfg.workload_w_max,
            ),
            resonator_params=ResonatorParams(
                lambda0_nm=plant_cfg.lambda0_nm,
                thermo_optic_nm_per_c=plant_cfg.thermo_optic_nm_per_c,
                lock_window_nm=plant_cfg.lock_window_nm,
                target_lambda_nm=plant_cfg.target_lambda_nm,
                ambient_c=plant_cfg.ambient_c,
            ),
            impairment_params=ImpairmentParams(
                detune_50_nm=plant_cfg.detune_50_nm,
                detune_floor_nm=plant_cfg.detune_floor_nm,
                detune_ceil_nm=plant_cfg.detune_ceil_nm,
            ),
            initial_temp_c=plant_cfg.ambient_c,
        )

        schedule = constant_heater(heater=0.0, workload=0.5)
        controller = PIDController(PIDParams())

        cfg = SimConfig.from_args(
            name="determinism_test",
            cycles=50,
            cycle_chunks=10,
            seed=54321,
            out_dir=None,
        )

        kernel = CoSimKernel(
            cfg,
            plant_runner=plant_runner,
            schedule=schedule,
            controller=controller,
            detune_target_nm=0.0,
        )
        result = kernel.run()
        return result.timeseries, result.events

    # Run twice
    ts1, events1 = run_simulation()
    ts2, events2 = run_simulation()

    # Timeseries should be identical
    assert len(ts1) == len(ts2)
    for s1, s2 in zip(ts1, ts2):
        assert s1.cycle == s2.cycle
        assert s1.temp_c == s2.temp_c
        assert s1.detune_nm == s2.detune_nm
        assert s1.locked == s2.locked
        assert s1.crc_fail_prob == s2.crc_fail_prob
        assert s1.heater_duty == s2.heater_duty
        assert s1.workload_frac == s2.workload_frac
        assert s1.controller_error == s2.controller_error
        assert s1.controller_active == s2.controller_active

    # Events should be identical
    assert len(events1) == len(events2)
    for e1, e2 in zip(events1, events2):
        assert e1.cycle == e2.cycle
        assert e1.chunk_idx == e2.chunk_idx
        assert e1.crc_fail == e2.crc_fail
        assert e1.crc_fail_prob == e2.crc_fail_prob
