#!/usr/bin/env python3
"""
Simple demo of Milestone 2 plant models.

Shows a single-step evaluation of the plant chain.
"""

from thermalres.config import PlantConfig
from thermalres.cosim.interfaces import PlantInputs
from thermalres.plant import (
    ThermalParams,
    ThermalState,
    ResonatorParams,
    ImpairmentParams,
    eval_plant_chain,
)


def main():
    print("=" * 60)
    print("ThermalRes Milestone 2 — Plant Model Demo")
    print("=" * 60)
    print()

    # Load default configuration
    cfg = PlantConfig()

    # Create model parameters from config
    thermal_params = ThermalParams(
        ambient_c=cfg.ambient_c,
        r_th_c_per_w=cfg.r_th_c_per_w,
        c_th_j_per_c=cfg.c_th_j_per_c,
        heater_w_max=cfg.heater_w_max,
        workload_w_max=cfg.workload_w_max,
    )

    resonator_params = ResonatorParams(
        lambda0_nm=cfg.lambda0_nm,
        thermo_optic_nm_per_c=cfg.thermo_optic_nm_per_c,
        lock_window_nm=cfg.lock_window_nm,
        target_lambda_nm=cfg.target_lambda_nm,
        ambient_c=cfg.ambient_c,
    )

    impairment_params = ImpairmentParams(
        detune_50_nm=cfg.detune_50_nm,
        detune_floor_nm=cfg.detune_floor_nm,
        detune_ceil_nm=cfg.detune_ceil_nm,
    )

    # Initial state: start at ambient temperature
    thermal_state = ThermalState(temp_c=cfg.ambient_c)

    print("Initial State:")
    print(f"  Temperature: {thermal_state.temp_c:.2f} °C")
    print()

    # Simulate with 50% heater duty
    inputs = PlantInputs(
        heater_duty=0.5,
        workload_frac=0.0,
        dt_s=0.1,
    )

    print("Applying inputs:")
    print(f"  Heater duty: {inputs.heater_duty * 100:.0f}%")
    print(f"  Workload: {inputs.workload_frac * 100:.0f}%")
    print(f"  Time step: {inputs.dt_s} s")
    print()

    # Step the plant chain 100 times
    print("Simulating 100 steps (10 seconds)...")
    for i in range(100):
        thermal_state, outputs = eval_plant_chain(
            thermal_state=thermal_state,
            inputs=inputs,
            thermal_params=thermal_params,
            resonator_params=resonator_params,
            impairment_params=impairment_params,
        )

        if i % 20 == 0:
            print(f"  Step {i:3d}: T={outputs.temp_c:.2f}°C, "
                  f"λ={outputs.resonance_nm:.3f}nm, "
                  f"detune={outputs.detune_nm:+.3f}nm, "
                  f"locked={outputs.locked}, "
                  f"p_fail={outputs.crc_fail_prob:.3f}")

    print()
    print("Final State:")
    print(f"  Temperature: {outputs.temp_c:.2f} °C")
    print(f"  Resonance: {outputs.resonance_nm:.3f} nm")
    print(f"  Detuning: {outputs.detune_nm:+.3f} nm")
    print(f"  Locked: {outputs.locked}")
    print(f"  CRC Fail Probability: {outputs.crc_fail_prob:.3f}")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
