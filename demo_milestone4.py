#!/usr/bin/env python3
"""
Milestone 4 Demo: Closed-Loop Control + Event Realization

Shows:
- Bang-bang controller maintaining lock
- Deterministic CRC event sampling
- Controller feedback loop
- Event stream generation
"""

from thermalres.config import PlantConfig, SimConfig
from thermalres.control import BangBangController
from thermalres.cosim.kernel import CoSimKernel
from thermalres.cosim.metrics import write_run_artifacts
from thermalres.cosim.plant_runner import PlantRunner
from thermalres.plant import ImpairmentParams, ResonatorParams, ThermalParams
from thermalres.scenarios import step_workload


def main():
    print("=" * 70)
    print("ThermalRes Milestone 4 — Closed-Loop Control Demo")
    print("=" * 70)
    print()

    # Configuration
    sim_cfg = SimConfig.from_args(
        name="demo_closed_loop",
        cycles=100,
        cycle_chunks=10,
        seed=42,
        out_dir=None,
    )

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

    # Create bang-bang controller
    controller = BangBangController()

    # Step workload: starts at 0, jumps to 0.5 at cycle 50
    schedule = step_workload(heater=0.0, workload_low=0.0, workload_high=0.5, step_at_cycle=50)

    print("Configuration:")
    print(f"  Cycles: {sim_cfg.cycles}")
    print(f"  Controller: Bang-bang")
    print(f"  Workload: Step from 0 → 0.5 at cycle 50")
    print(f"  Target detune: 0 nm (on resonance)")
    print()

    # Run closed-loop simulation
    print("Running closed-loop simulation...")
    kernel = CoSimKernel(
        sim_cfg,
        plant_runner=plant_runner,
        schedule=schedule,
        controller=controller,
        detune_target_nm=0.0,
    )
    result = kernel.run()

    # Write artifacts
    write_run_artifacts(
        out_path=sim_cfg.out_dir,
        metrics=result.metrics,
        chunks=result.chunks,
        timeseries=result.timeseries,
        events=result.events,
    )

    print(f"✓ Simulation complete: {result.metrics.total_cycles} cycles")
    print()

    # Analyze results
    locked_count = sum(1 for s in result.timeseries if s.locked)
    crc_fails = sum(1 for e in result.events if e.crc_fail)

    print("Results:")
    print(f"  Locked chunks: {locked_count}/{len(result.timeseries)}")
    print(f"  CRC failures: {crc_fails}/{len(result.events)}")
    print()

    # Show sample time-series
    print("Time-Series (selected samples):")
    print(f"{'Cycle':<8} {'Temp(°C)':<10} {'Detune(nm)':<12} {'Heater':<10} {'Locked':<8} {'Error':<10}")
    print("-" * 68)

    for i in [0, 3, 5, 7, 9]:
        s = result.timeseries[i]
        locked_str = "✓" if s.locked else "✗"
        error_str = f"{s.controller_error:.3f}" if s.controller_error is not None else "N/A"
        print(f"{s.cycle:<8} {s.temp_c:<10.2f} {s.detune_nm:<12.3f} "
              f"{s.heater_duty:<10.2f} {locked_str:<8} {error_str:<10}")

    print()
    print("Artifacts written to:")
    print(f"  {sim_cfg.out_dir}/metrics.json")
    print(f"  {sim_cfg.out_dir}/timeseries.json")
    print(f"  {sim_cfg.out_dir}/events.jsonl")
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
