from __future__ import annotations

from thermalres.cosim.interfaces import PlantInputs, PlantOutputs
from thermalres.plant.impairment import ImpairmentParams, eval_impairment
from thermalres.plant.resonator import ResonatorParams, eval_resonator
from thermalres.plant.thermal import ThermalParams, ThermalState, step_thermal

__all__ = [
    "ThermalParams",
    "ThermalState",
    "ResonatorParams",
    "ImpairmentParams",
    "step_thermal",
    "eval_resonator",
    "eval_impairment",
    "eval_plant_chain",
]


def eval_plant_chain(
    thermal_state: ThermalState,
    inputs: PlantInputs,
    thermal_params: ThermalParams,
    resonator_params: ResonatorParams,
    impairment_params: ImpairmentParams,
) -> tuple[ThermalState, PlantOutputs]:
    """
    Evaluate the complete plant model chain.

    This function chains together the thermal, resonator, and impairment models
    to produce a complete plant output. The thermal state is evolved forward by
    one time step.

    Args:
        thermal_state: Current thermal state
        inputs: Plant inputs (heater, workload, dt)
        thermal_params: Thermal model parameters
        resonator_params: Resonator model parameters
        impairment_params: Impairment model parameters

    Returns:
        Tuple of (new_thermal_state, plant_outputs)
    """
    # Step 1: Update thermal state
    new_thermal_state = step_thermal(
        thermal_state,
        dt_s=inputs.dt_s,
        heater_duty=inputs.heater_duty,
        workload_frac=inputs.workload_frac,
        p=thermal_params,
    )

    # Step 2: Evaluate resonator at new temperature
    resonator_outputs = eval_resonator(
        temp_c=new_thermal_state.temp_c,
        p=resonator_params,
    )

    # Step 3: Evaluate impairment based on resonator state
    impairment_outputs = eval_impairment(
        detune_nm=resonator_outputs.detune_nm,
        locked=resonator_outputs.locked,
        p=impairment_params,
    )

    # Combine outputs
    plant_outputs = PlantOutputs(
        temp_c=new_thermal_state.temp_c,
        resonance_nm=resonator_outputs.resonance_nm,
        detune_nm=resonator_outputs.detune_nm,
        locked=resonator_outputs.locked,
        crc_fail_prob=impairment_outputs.crc_fail_prob,
    )

    return new_thermal_state, plant_outputs
