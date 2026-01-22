#!/usr/bin/env python3
"""
Milestone 3 Demo: Kernel-Plant Integration (Open Loop)

Shows the complete simulation flow with:
- CoSimKernel as the time authority
- PlantRunner managing plant state
- Open-loop schedule (no feedback)
- Time-series artifact generation
"""

from thermalres.config import PlantConfig, SimConfig
from thermalres.cosim.kernel import CoSimKernel
from thermalres.cosim.metrics import write_run_artifacts
from thermalres.cosim.plant_runner import PlantRunner
from thermalres.plant import ImpairmentParams, ResonatorParams, ThermalParams
from thermalres.scenarios import constant_heater


def main():
    print("=" * 70)
    print("ThermalRes Milestone 3 — Kernel-Plant Integration Demo (Open Loop)")
    print("=" * 70)
    print()

    # Simulation configuration
    sim_cfg = SimConfig.from_args(
        name="demo_open_loop",
        cycles=100,
        cycle_chunks=10,  # Record every 10 cycles
        seed=42,
        out_dir=None,
    )

    # Plant parameters
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

    # Initialize plant runner
    plant_runner = PlantRunner(
        thermal_params=thermal_params,
        resonator_params=resonator_params,
        impairment_params=impairment_params,
        initial_temp_c=plant_cfg.ambient_c,
    )

    # Open-loop schedule: 50% heater, no workload
    schedule = constant_heater(heater=0.5, workload=0.0)

    print("Configuration:")
    print(f"  Cycles: {sim_cfg.cycles}")
    print(f"  Chunk size: {sim_cfg.cycle_chunks} cycles")
    print(f"  Heater duty: 50%")
    print(f"  Workload: 0%")
    print(f"  Initial temp: {plant_cfg.ambient_c}°C")
    print()

    # Run kernel-integrated simulation
    print("Running kernel-integrated simulation...")
    kernel = CoSimKernel(sim_cfg, plant_runner=plant_runner, schedule=schedule)
    metrics, chunks, timeseries = kernel.run()

    # Write artifacts
    write_run_artifacts(
        out_path=sim_cfg.out_dir,
        metrics=metrics,
        chunks=chunks,
        timeseries=timeseries,
    )

    print(f"✓ Simulation complete: {metrics.total_cycles} cycles, {metrics.total_chunks} chunks")
    print()

    # Display time-series results
    print("Time-Series Results:")
    print(f"{'Cycle':<8} {'Temp(°C)':<10} {'Detune(nm)':<12} {'Locked':<8} {'p_fail':<8}")
    print("-" * 56)

    for i, sample in enumerate(timeseries):
        if i % 2 == 0:  # Show every other sample
            locked_str = "✓" if sample.locked else "✗"
            print(f"{sample.cycle:<8} {sample.temp_c:<10.2f} {sample.detune_nm:<12.3f} "
                  f"{locked_str:<8} {sample.crc_fail_prob:<8.3f}")

    print()

    # Summary
    final = timeseries[-1]
    print("Final State:")
    print(f"  Temperature: {final.temp_c:.2f}°C (started at {plant_cfg.ambient_c}°C)")
    print(f"  Resonance shift: {final.temp_c - plant_cfg.ambient_c:.2f}°C * {plant_cfg.thermo_optic_nm_per_c} nm/°C")
    print(f"                 = {(final.temp_c - plant_cfg.ambient_c) * plant_cfg.thermo_optic_nm_per_c:.3f} nm")
    print(f"  Detuning: {final.detune_nm:+.3f} nm")
    print(f"  Locked: {'Yes' if final.locked else 'No'}")
    print(f"  CRC failure probability: {final.crc_fail_prob:.3f}")
    print()

    # Artifact info
    print("Artifacts written to:")
    print(f"  {sim_cfg.out_dir}/metrics.json")
    print(f"  {sim_cfg.out_dir}/timeseries.json")
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
