from __future__ import annotations

from thermalres.cosim.interfaces import PlantInputs, PlantOutputs
from thermalres.plant import (
    ThermalParams,
    ThermalState,
    ResonatorParams,
    ImpairmentParams,
    eval_plant_chain,
)


class PlantRunner:
    """
    Encapsulates plant state evolution and evaluation.

    The PlantRunner is the glue between the kernel and the plant models.
    It maintains the thermal state and delegates evaluation to the plant chain.

    The kernel calls step() each cycle; PlantRunner:
    - Updates thermal state
    - Evaluates resonator
    - Evaluates impairment
    - Returns combined outputs

    This preserves clean separation: kernel doesn't know about plant internals.
    """

    def __init__(
        self,
        thermal_params: ThermalParams,
        resonator_params: ResonatorParams,
        impairment_params: ImpairmentParams,
        initial_temp_c: float,
    ):
        """
        Initialize the plant runner.

        Args:
            thermal_params: Thermal model parameters
            resonator_params: Resonator model parameters
            impairment_params: Impairment model parameters
            initial_temp_c: Initial temperature (°C)
        """
        self.thermal_params = thermal_params
        self.resonator_params = resonator_params
        self.impairment_params = impairment_params

        # Initialize thermal state
        self.thermal_state = ThermalState(temp_c=initial_temp_c)

    def step(self, inputs: PlantInputs) -> PlantOutputs:
        """
        Step the plant models forward by one timestep.

        Args:
            inputs: Plant inputs (heater_duty, workload_frac, dt_s)

        Returns:
            PlantOutputs with updated state and computed metrics
        """
        # Evaluate the plant chain
        self.thermal_state, outputs = eval_plant_chain(
            thermal_state=self.thermal_state,
            inputs=inputs,
            thermal_params=self.thermal_params,
            resonator_params=self.resonator_params,
            impairment_params=self.impairment_params,
        )

        return outputs

    def get_thermal_state(self) -> ThermalState:
        """Get the current thermal state (for inspection/testing)."""
        return self.thermal_state
