from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from thermalres.config import PlantConfig, SimConfig
from thermalres.cosim.kernel import CoSimKernel
from thermalres.cosim.metrics import write_run_artifacts
from thermalres.cosim.plant_runner import PlantRunner
from thermalres.plant import ImpairmentParams, ResonatorParams, ThermalParams
from thermalres.scenarios import constant_heater, step_workload


def test_open_loop_constant_heater():
    """
    Test open-loop simulation with constant heater duty.

    Validates that temperature increases monotonically with sustained heater.
    """
    cfg = SimConfig.from_args(
        name="constant_heater",
        cycles=100,
        cycle_chunks=10,
        seed=42,
        out_dir=None,
    )

    # Create plant parameters
    plant_cfg = PlantConfig()
    thermal_params = ThermalParams(
        ambient_c=plant_cfg.ambient_c,
        r_th_c_per_w=plant_cfg.r_th_c_per_w,
        c_th_j_per_c=plant_cfg.c_th_j_per_c,
        heater_w_max=plant_cfg.heater_w_max,
        workload_w_max=plant_cfg.workload_w_max,
    )
    resonator_params = ResonatorParams(
        lambda0_nm=plant_cfg.lambda0_nm,
        thermo_optic_nm_per_c=plant_cfg.thermo_optic_nm_per_c,
        lock_window_nm=plant_cfg.lock_window_nm,
        target_lambda_nm=plant_cfg.target_lambda_nm,
        ambient_c=plant_cfg.ambient_c,
    )
    impairment_params = ImpairmentParams(
        detune_50_nm=plant_cfg.detune_50_nm,
        detune_floor_nm=plant_cfg.detune_floor_nm,
        detune_ceil_nm=plant_cfg.detune_ceil_nm,
    )

    # Create plant runner
    plant_runner = PlantRunner(
        thermal_params=thermal_params,
        resonator_params=resonator_params,
        impairment_params=impairment_params,
        initial_temp_c=plant_cfg.ambient_c,
    )

    # Create open-loop schedule: 50% heater, no workload
    schedule = constant_heater(heater=0.5, workload=0.0)

    # Run kernel with plant integration
    kernel = CoSimKernel(cfg, plant_runner=plant_runner, schedule=schedule)
    metrics, chunks, timeseries = kernel.run()

    # Basic assertions
    assert metrics.total_cycles == 100
    assert metrics.total_chunks == 10
    assert len(chunks) == 10
    assert len(timeseries) == 10  # One sample per chunk

    # Temperature should increase monotonically
    temps = [s.temp_c for s in timeseries]
    for i in range(len(temps) - 1):
        assert temps[i] <= temps[i + 1], f"Temperature not monotonic at index {i}"

    # First temperature should be near ambient
    assert abs(temps[0] - plant_cfg.ambient_c) < 5.0

    # Last temperature should be above ambient
    assert temps[-1] > plant_cfg.ambient_c

    # Resonance should shift with temperature
    resonances = [s.temp_c * plant_cfg.thermo_optic_nm_per_c + plant_cfg.lambda0_nm
                  for s in timeseries]
    # Check that resonance increases
    assert resonances[-1] > resonances[0]


def test_open_loop_step_workload():
    """
    Test open-loop simulation with step workload change.

    Validates transient response and locked/unlocked transitions.
    """
    cfg = SimConfig.from_args(
        name="step_workload",
        cycles=100,
        cycle_chunks=10,
        seed=42,
        out_dir=None,
    )

    # Create plant parameters
    plant_cfg = PlantConfig()
    thermal_params = ThermalParams(
        ambient_c=plant_cfg.ambient_c,
        r_th_c_per_w=plant_cfg.r_th_c_per_w,
        c_th_j_per_c=plant_cfg.c_th_j_per_c,
        heater_w_max=plant_cfg.heater_w_max,
        workload_w_max=plant_cfg.workload_w_max,
    )
    resonator_params = ResonatorParams(
        lambda0_nm=plant_cfg.lambda0_nm,
        thermo_optic_nm_per_c=plant_cfg.thermo_optic_nm_per_c,
        lock_window_nm=plant_cfg.lock_window_nm,
        target_lambda_nm=plant_cfg.lambda0_nm,  # Target at nominal
        ambient_c=plant_cfg.ambient_c,
    )
    impairment_params = ImpairmentParams(
        detune_50_nm=plant_cfg.detune_50_nm,
        detune_floor_nm=plant_cfg.detune_floor_nm,
        detune_ceil_nm=plant_cfg.detune_ceil_nm,
    )

    # Create plant runner
    plant_runner = PlantRunner(
        thermal_params=thermal_params,
        resonator_params=resonator_params,
        impairment_params=impairment_params,
        initial_temp_c=plant_cfg.ambient_c,
    )

    # Step workload from 0 to 1 at cycle 50
    schedule = step_workload(
        heater=0.0,
        workload_low=0.0,
        workload_high=1.0,
        step_at_cycle=50,
    )

    # Run kernel
    kernel = CoSimKernel(cfg, plant_runner=plant_runner, schedule=schedule)
    metrics, chunks, timeseries = kernel.run()

    # Basic assertions
    assert len(timeseries) == 10

    # CRC fail probability should correlate with detuning
    for sample in timeseries:
        if not sample.locked:
            # If unlocked, must fail
            assert sample.crc_fail_prob == 1.0
        else:
            # If locked, probability depends on detuning
            assert 0.0 <= sample.crc_fail_prob <= 1.0

    # Check that detuning increases after step
    detunes_before = [abs(s.detune_nm) for s in timeseries[:5]]
    detunes_after = [abs(s.detune_nm) for s in timeseries[5:]]

    # After step, detuning should generally be larger
    assert max(detunes_after) >= max(detunes_before)


def test_open_loop_artifacts():
    """
    Test that open-loop simulation produces correct artifacts.
    """
    plant_cfg = PlantConfig()

    # Create plant runner
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

    schedule = constant_heater(heater=0.3, workload=0.0)

    with TemporaryDirectory() as td:
        out_dir = Path(td).joinpath("run")
        cfg = SimConfig.from_args(
            name="artifact_test",
            cycles=50,
            cycle_chunks=10,
            seed=0,
            out_dir=str(out_dir),
        )

        kernel = CoSimKernel(cfg, plant_runner=plant_runner, schedule=schedule)
        metrics, chunks, timeseries = kernel.run()

        write_run_artifacts(
            out_path=out_dir,
            metrics=metrics,
            chunks=chunks,
            timeseries=timeseries,
        )

        # Check metrics.json exists
        metrics_file = out_dir.joinpath("metrics.json")
        assert metrics_file.exists()

        # Check timeseries.json exists
        timeseries_file = out_dir.joinpath("timeseries.json")
        assert timeseries_file.exists()

        # Validate timeseries.json structure
        ts_data = json.loads(timeseries_file.read_text(encoding="utf-8"))
        assert "samples" in ts_data
        assert len(ts_data["samples"]) == 5  # 50 cycles / 10 chunk_cycles = 5 chunks

        # Validate sample structure
        sample = ts_data["samples"][0]
        assert set(sample.keys()) == {
            "cycle",
            "temp_c",
            "detune_nm",
            "locked",
            "crc_fail_prob",
            "heater_duty",
            "workload_frac",
        }


def test_open_loop_determinism():
    """
    Test that identical configurations produce identical results.
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

        schedule = constant_heater(heater=0.4, workload=0.2)

        cfg = SimConfig.from_args(
            name="determinism_test",
            cycles=30,
            cycle_chunks=10,
            seed=12345,
            out_dir=None,
        )

        kernel = CoSimKernel(cfg, plant_runner=plant_runner, schedule=schedule)
        _, _, timeseries = kernel.run()
        return timeseries

    # Run twice
    ts1 = run_simulation()
    ts2 = run_simulation()

    # Should be identical
    assert len(ts1) == len(ts2)
    for s1, s2 in zip(ts1, ts2):
        assert s1.cycle == s2.cycle
        assert s1.temp_c == s2.temp_c
        assert s1.detune_nm == s2.detune_nm
        assert s1.locked == s2.locked
        assert s1.crc_fail_prob == s2.crc_fail_prob
        assert s1.heater_duty == s2.heater_duty
        assert s1.workload_frac == s2.workload_frac
