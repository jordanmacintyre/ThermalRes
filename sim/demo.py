#!/usr/bin/env python3
"""
ThermalRes Demonstration Script.

Demonstrates the full ThermalRes mixed-domain co-simulation with RTL
link monitor integration. Showcases:

1. Mixed Analog-Digital Simulation
   - Thermal model (RC network with passive cooling)
   - Resonator model (thermo-optic wavelength shift)
   - Impairment model (CRC failure probability)
   - Link monitor state machine (Python reference)

2. Closed-Loop Thermal Control
   - PID controller adjusts heater duty to maintain resonance alignment
   - Heat-only control (can't actively cool, only add heat)
   - Designed for resonator to run cold at ambient, heater brings to target
   - Workload disturbances compensated by reducing heater duty

3. Link State Tracking
   - Hysteresis-based state machine
   - Consecutive failure/pass counting
   - Link up/down transitions

4. RTL Validation (Optional)
   - Python reference vs RTL equivalence checking
   - Requires Verilator and cocotb

5. Artifact Generation
   - metrics.json: Run-level metrics
   - timeseries.json: Plant state over time
   - events.json: CRC failure events
   - link_state.json: Link monitor state history
   - plot.png: Visualization of simulation results (optional)

Usage:
    # Run with closed-loop control (default):
    python sim/demo.py --cycles 300 --plot

    # Run open-loop (no controller, temperature rises with workload):
    python sim/demo.py --cycles 300 --open-loop --plot

    # Run with RTL validation (requires Verilator):
    python sim/demo.py --validate-rtl

    # Run with custom workload schedule:
    python sim/demo.py --warmup-cycles 50 --warmup-workload 0.3 --disturbance-workload 0.8

Output:
    Artifacts are written to artifacts/runs/<timestamp>_demo/
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Callable

# ─────────────────────────────────────────────────────────────────────────────
# Ensure the package is importable when running from sim/ directory
# ─────────────────────────────────────────────────────────────────────────────
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from thermalres.config import SimConfig
from thermalres.control.pid import PIDController, PIDParams
from thermalres.cosim.interfaces import LinkMonitorConfig, PlantInputs
from thermalres.cosim.kernel import CoSimKernel
from thermalres.cosim.link_runner import LinkRunner
from thermalres.cosim.metrics import write_run_artifacts
from thermalres.cosim.plant_runner import PlantRunner
from thermalres.plant import ImpairmentParams, ResonatorParams, ThermalParams


def check_verilator_available() -> bool:
    """Check if Verilator is available on PATH."""
    return shutil.which("verilator") is not None


def create_workload_schedule(
    warmup_workload: float,
    disturbance_workload: float,
    warmup_cycles: int,
    dt_s: float = 0.1,
    pulsed: bool = False,
    pulse_period: int = 40,
    pulse_duty: float = 0.5,
    noise_std: float = 0.05,
    seed: int = 42,
) -> Callable[[int], PlantInputs]:
    """
    Create a workload schedule for the demo.

    Supports two modes:
    1. Step mode (pulsed=False): Simple step from warmup to disturbance workload
    2. Pulsed mode (pulsed=True): AI/ML batch-style pulsed workload with noise

    In pulsed mode, workload alternates between low and high states with
    stochastic noise, simulating batch inference/training jobs.

    Args:
        warmup_workload: Workload fraction during warmup phase [0, 1]
        disturbance_workload: Peak workload fraction after warmup [0, 1]
        warmup_cycles: Number of cycles in warmup phase
        dt_s: Time step per cycle (seconds)
        pulsed: If True, use pulsed workload pattern after warmup
        pulse_period: Period of workload pulses in cycles
        pulse_duty: Duty cycle of pulses (fraction of period at high workload)
        noise_std: Standard deviation of Gaussian noise on workload
        seed: Random seed for reproducible noise

    Returns:
        Schedule function: (cycle: int) -> PlantInputs
    """
    import random
    rng = random.Random(seed)

    def schedule(cycle: int) -> PlantInputs:
        if cycle < warmup_cycles:
            # Warmup phase: constant low workload
            workload = warmup_workload
        elif not pulsed:
            # Step mode: constant high workload after warmup
            workload = disturbance_workload
        else:
            # Pulsed mode: alternating workload simulating batch jobs
            cycle_in_period = (cycle - warmup_cycles) % pulse_period
            pulse_on_cycles = int(pulse_period * pulse_duty)

            if cycle_in_period < pulse_on_cycles:
                # High workload phase (batch job running)
                base_workload = disturbance_workload
            else:
                # Low workload phase (idle between batches)
                base_workload = warmup_workload

            # Add stochastic noise (clamp to valid range)
            noise = rng.gauss(0, noise_std)
            workload = max(0.0, min(1.0, base_workload + noise))

        # heater_duty=0.0 will be overridden by controller in closed-loop mode
        return PlantInputs(heater_duty=0.0, workload_frac=workload, dt_s=dt_s)

    return schedule


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="ThermalRes Demo: Mixed-domain co-simulation with thermal control",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sim/demo.py --cycles 300 --plot
      Run with step workload and closed-loop PID control

  python sim/demo.py --pulsed --cycles 300 --plot
      Run with pulsed AI/ML batch workload (recommended)

  python sim/demo.py --open-loop --pulsed --cycles 300 --plot
      Run pulsed workload without controller (shows need for control)

  python sim/demo.py --validate-rtl
      Run with RTL validation (requires Verilator)

  python sim/demo.py --pulsed --pulse-period 60 --pulse-duty 0.4
      Custom pulse timing (60-cycle period, 40% duty cycle)
""",
    )

    # Simulation parameters
    parser.add_argument(
        "--cycles",
        type=int,
        default=300,
        help="Total simulation cycles (default: %(default)s)",
    )
    parser.add_argument(
        "--chunk-cycles",
        type=int,
        default=1,
        help="Cycles per chunk (default: %(default)s for demo)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic simulation (default: %(default)s)",
    )

    # Link monitor parameters
    parser.add_argument(
        "--fails-to-down",
        type=int,
        default=4,
        help="Consecutive CRC failures to trigger link down (default: %(default)s)",
    )
    parser.add_argument(
        "--passes-to-up",
        type=int,
        default=8,
        help="Consecutive CRC passes to trigger link up (default: %(default)s)",
    )

    # Control mode
    parser.add_argument(
        "--open-loop",
        action="store_true",
        help="Run without controller (heater_duty=0, temperature rises with workload)",
    )

    # Workload schedule parameters
    parser.add_argument(
        "--warmup-cycles",
        type=int,
        default=50,
        help="Cycles in warmup phase before workload disturbance (default: %(default)s)",
    )
    parser.add_argument(
        "--warmup-workload",
        type=float,
        default=0.3,
        help="Workload fraction during warmup/idle [0-1] (default: %(default)s)",
    )
    parser.add_argument(
        "--disturbance-workload",
        type=float,
        default=0.7,
        help="Peak workload fraction during active phase [0-1] (default: %(default)s)",
    )

    # Pulsed workload (AI/ML batch simulation)
    parser.add_argument(
        "--pulsed",
        action="store_true",
        help="Use pulsed workload pattern (simulates AI/ML batch jobs)",
    )
    parser.add_argument(
        "--pulse-period",
        type=int,
        default=40,
        help="Period of workload pulses in cycles (default: %(default)s)",
    )
    parser.add_argument(
        "--pulse-duty",
        type=float,
        default=0.5,
        help="Duty cycle of pulses [0-1] (default: %(default)s)",
    )
    parser.add_argument(
        "--noise",
        type=float,
        default=0.05,
        help="Workload noise std deviation [0-1] (default: %(default)s)",
    )

    # RTL validation
    parser.add_argument(
        "--validate-rtl",
        action="store_true",
        help="Validate link monitor against RTL simulation (requires Verilator)",
    )

    # Output options
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print detailed simulation progress",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Generate visualization plot (requires matplotlib)",
    )
    parser.add_argument(
        "--show-plot",
        action="store_true",
        help="Display plot interactively (implies --plot)",
    )

    return parser.parse_args()


def run_demo(args: argparse.Namespace) -> int:
    """
    Run the ThermalRes demonstration.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code: 0 for success, non-zero for errors
    """
    print("=" * 70)
    print("ThermalRes Demo: Mixed-Domain Co-Simulation")
    print("=" * 70)
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 1: Check RTL validation prerequisites
    # ─────────────────────────────────────────────────────────────────────────
    if args.validate_rtl:
        if not check_verilator_available():
            print("ERROR: --validate-rtl requires Verilator")
            print("Install with: conda install -c conda-forge verilator")
            return 1
        print("[RTL] Verilator found - RTL validation enabled")
    else:
        print("[RTL] RTL validation disabled (use --validate-rtl to enable)")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 2: Configure simulation
    # ─────────────────────────────────────────────────────────────────────────
    control_mode = "open-loop" if args.open_loop else "closed-loop PID"
    workload_mode = "pulsed (AI/ML batch)" if args.pulsed else "step"
    print("Configuration:")
    print(f"  Control mode:   {control_mode}")
    print(f"  Workload mode:  {workload_mode}")
    print(f"  Cycles:         {args.cycles}")
    print(f"  Chunk size:     {args.chunk_cycles}")
    print(f"  Seed:           {args.seed}")
    print(f"  Warmup cycles:  {args.warmup_cycles}")
    print(f"  Idle load:      {args.warmup_workload:.0%}")
    print(f"  Active load:    {args.disturbance_workload:.0%}")
    if args.pulsed:
        print(f"  Pulse period:   {args.pulse_period} cycles")
        print(f"  Pulse duty:     {args.pulse_duty:.0%}")
        print(f"  Noise σ:        {args.noise:.0%}")
    print(f"  Fails to down:  {args.fails_to_down}")
    print(f"  Passes to up:   {args.passes_to_up}")
    print()

    config = SimConfig.from_args(
        name="demo",
        cycles=args.cycles,
        cycle_chunks=args.chunk_cycles,
        seed=args.seed,
        out_dir=None,  # Use default timestamp-based directory
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Step 3: Create plant runner with parameters designed for heat-only control
    #
    # Key design principle: The resonator runs COLD at ambient temperature
    # (below target wavelength). The heater must add heat to bring it up
    # to the target. This is physically realistic - we can only add heat,
    # not actively cool.
    #
    # Parameter design:
    # - At T_ambient (25°C): λ_res = 1550.00nm (below target)
    # - Target: λ_target = 1550.05nm
    # - Need ΔT = 5°C to reach target (with α = 0.01 nm/°C)
    # - At equilibrium: ΔT = P_in × R_th
    # - Need P_in ≈ 2.5W (with R_th = 2.0 °C/W) from heater to maintain lock
    # ─────────────────────────────────────────────────────────────────────────
    print("Creating plant models...")

    thermal_params = ThermalParams(
        ambient_c=25.0,          # Room temperature
        c_th_j_per_c=5.0,        # Thermal capacitance (J/°C) - determines response time
        r_th_c_per_w=2.0,        # Thermal resistance (°C/W) - passive heat sink
        heater_w_max=3.0,        # Max heater power (W) - control actuator
        workload_w_max=5.0,      # Max workload power (W) - disturbance source
    )

    # Thermal time constant τ = R × C = 2.0 × 5.0 = 10 seconds
    # With dt_s = 0.1s per cycle, ~100 cycles to reach 63% of equilibrium
    tau_s = thermal_params.r_th_c_per_w * thermal_params.c_th_j_per_c
    print(f"  Thermal τ = {tau_s:.1f}s ({tau_s / 0.1:.0f} cycles at 0.1s/cycle)")

    resonator_params = ResonatorParams(
        lambda0_nm=1550.0,               # Nominal resonance at T_ambient
        thermo_optic_nm_per_c=0.01,      # 10pm/°C shift (typical silicon)
        lock_window_nm=0.02,             # Lock tolerance ±20pm
        target_lambda_nm=1550.08,        # Target is ABOVE ambient resonance
        ambient_c=25.0,                  # Reference temperature
    )
    # Target at 1550.08nm requires ΔT = 8°C from ambient
    # At 50% workload: 0.5 × 5W = 2.5W → ΔT = 5°C
    # Heater needs to provide remaining 3°C → ~1.5W → 50% duty

    # Calculate required temperature rise to reach target
    delta_lambda = resonator_params.target_lambda_nm - resonator_params.lambda0_nm
    delta_t_required = delta_lambda / resonator_params.thermo_optic_nm_per_c
    power_required = delta_t_required / thermal_params.r_th_c_per_w
    print(f"  Δλ to target = {delta_lambda * 1000:.1f}pm, need ΔT = {delta_t_required:.1f}°C ({power_required:.1f}W)")

    impairment_params = ImpairmentParams(
        detune_50_nm=0.03,               # 50% failure at 30pm detuning
        detune_floor_nm=0.01,            # Below 10pm: no failures
        detune_ceil_nm=0.05,             # Above 50pm: always fails
    )

    plant_runner = PlantRunner(
        thermal_params=thermal_params,
        resonator_params=resonator_params,
        impairment_params=impairment_params,
        initial_temp_c=25.0,  # Start at ambient
    )

    print(f"  - Thermal model: RC network (τ = {tau_s:.1f}s)")
    print(f"  - Resonator: 1550nm, {resonator_params.thermo_optic_nm_per_c * 1000:.0f}pm/°C")
    print(f"  - Impairment: Sigmoid CRC probability")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 4: Create workload schedule
    # ─────────────────────────────────────────────────────────────────────────
    print("Creating workload schedule...")
    schedule = create_workload_schedule(
        warmup_workload=args.warmup_workload,
        disturbance_workload=args.disturbance_workload,
        warmup_cycles=args.warmup_cycles,
        pulsed=args.pulsed,
        pulse_period=args.pulse_period,
        pulse_duty=args.pulse_duty,
        noise_std=args.noise,
        seed=args.seed,
    )

    print(f"  - Warmup (cycles 0-{args.warmup_cycles}): {args.warmup_workload:.0%} workload")
    if args.pulsed:
        print(f"  - Pulsed mode: period={args.pulse_period} cycles, duty={args.pulse_duty:.0%}")
        print(f"  - Workload: {args.warmup_workload:.0%} (idle) ↔ {args.disturbance_workload:.0%} (active)")
        print(f"  - Noise: σ={args.noise:.0%}")
    else:
        print(f"  - Step mode: {args.disturbance_workload:.0%} workload after warmup")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 5: Create controller (unless open-loop mode)
    # ─────────────────────────────────────────────────────────────────────────
    controller = None
    if not args.open_loop:
        print("Creating PID controller...")

        # PID gains tuned for the thermal system
        # The controller operates around a bias point (unlock_boost)
        # and adjusts based on detuning error
        pid_params = PIDParams(
            kp=5.0,                     # Proportional gain (duty per nm detuning)
            ki=0.5,                     # Integral gain (eliminate steady-state error)
            kd=0.1,                     # Derivative gain (damping)
            min_duty=0.0,               # Minimum heater duty (can't cool!)
            max_duty=1.0,               # Maximum heater duty
            integrator_min=-1.0,        # Anti-windup limits
            integrator_max=1.0,
            unlock_boost=0.5,           # Bias point: 50% duty as starting point
        )
        controller = PIDController(pid_params)

        print(f"  - Gains: Kp={pid_params.kp}, Ki={pid_params.ki}, Kd={pid_params.kd}")
        print(f"  - Duty range: [{pid_params.min_duty}, {pid_params.max_duty}]")
        print(f"  - Target: detune = 0nm (on resonance)")
        print()
    else:
        print("Open-loop mode: No controller (heater_duty = 0)")
        print("  - Temperature will rise with workload")
        print("  - No compensation for thermal disturbances")
        print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 6: Create link runner
    # ─────────────────────────────────────────────────────────────────────────
    print("Creating link monitor...")

    link_config = LinkMonitorConfig(
        fails_to_down=args.fails_to_down,
        passes_to_up=args.passes_to_up,
        use_rtl=args.validate_rtl,
    )
    link_runner = LinkRunner(link_config)

    print(f"  - Mode: {'RTL validation' if args.validate_rtl else 'Python reference'}")
    print(f"  - Hysteresis: {args.fails_to_down} fails → DOWN, {args.passes_to_up} passes → UP")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 7: Create and run the simulation kernel
    # ─────────────────────────────────────────────────────────────────────────
    print("Running simulation...")

    kernel = CoSimKernel(
        config=config,
        plant_runner=plant_runner,
        schedule=schedule,
        controller=controller,
        detune_target_nm=0.0,  # Target: on resonance
        link_runner=link_runner,
    )

    result = kernel.run()

    print(f"  Simulated {result.metrics.total_cycles} cycles in "
          f"{result.metrics.total_chunks} chunks")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 8: Analyze results
    # ─────────────────────────────────────────────────────────────────────────
    print("Results Summary:")

    if result.timeseries:
        # Temperature analysis
        temps = [s.temp_c for s in result.timeseries]
        max_temp = max(temps)
        final_temp = temps[-1]
        print(f"  Temperature: max={max_temp:.2f}°C, final={final_temp:.2f}°C")

        # Detuning analysis
        detunes = [abs(s.detune_nm) for s in result.timeseries]
        max_detune = max(detunes)
        final_detune = result.timeseries[-1].detune_nm
        print(f"  Detuning: max={max_detune * 1000:.1f}pm, final={final_detune * 1000:.1f}pm")

        # Heater duty analysis
        heater_duties = [s.heater_duty for s in result.timeseries]
        avg_heater = sum(heater_duties) / len(heater_duties)
        final_heater = heater_duties[-1]
        print(f"  Heater duty: avg={avg_heater:.1%}, final={final_heater:.1%}")

        # Lock status
        locked_cycles = sum(1 for s in result.timeseries if s.locked)
        lock_pct = locked_cycles / len(result.timeseries) * 100
        print(f"  Lock status: {lock_pct:.1f}% of cycles locked")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 9: Analyze link state transitions
    # ─────────────────────────────────────────────────────────────────────────
    print("Link State Analysis:")

    if result.link_states:
        # Find state transitions
        transitions = []
        prev_up = True
        for sample in result.link_states:
            if sample.link_up != prev_up:
                direction = "UP → DOWN" if prev_up else "DOWN → UP"
                transitions.append((sample.cycle, direction))
                prev_up = sample.link_up

        # Final state
        final = result.link_states[-1]
        print(f"  Final state:      {'UP' if final.link_up else 'DOWN'}")
        print(f"  Total frames:     {final.total_frames}")
        print(f"  Total CRC fails:  {final.total_crc_fails}")
        print(f"  Consec fails:     {final.consec_fails}")
        print(f"  Consec passes:    {final.consec_passes}")
        print()

        if transitions:
            print("  Transitions:")
            for cycle, direction in transitions:
                print(f"    Cycle {cycle:3d}: {direction}")
        else:
            print("  No link transitions during simulation")
        print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 10: RTL validation (if enabled)
    # ─────────────────────────────────────────────────────────────────────────
    rtl_success = True
    if args.validate_rtl:
        print("RTL Validation:")
        try:
            success, message = link_runner.validate_against_rtl()
            rtl_success = success
            if success:
                print(f"  PASSED: {message}")
            else:
                print(f"  FAILED: {message}")
        except RuntimeError as e:
            print(f"  ERROR: {e}")
            rtl_success = False
        print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 11: Write artifacts
    # ─────────────────────────────────────────────────────────────────────────
    print("Writing artifacts...")

    write_run_artifacts(
        out_path=config.out_dir,
        metrics=result.metrics,
        chunks=result.chunks,
        timeseries=result.timeseries,
        events=result.events,
        link_states=result.link_states,
    )

    print(f"  Output directory: {config.out_dir}")
    print()
    print("Generated files:")
    print("  - metrics.json:    Run-level metrics (timing, cycle counts)")
    print("  - chunks.json:     Per-chunk summaries")
    print("  - timeseries.json: Plant state over time (temp, detune, CRC prob)")
    print("  - events.json:     CRC failure events")
    print("  - link_state.json: Link monitor state history")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 12: Generate plot (if requested)
    # ─────────────────────────────────────────────────────────────────────────
    generate_plot = args.plot or args.show_plot
    if generate_plot:
        try:
            from thermalres.cosim.plotting import plot_simulation_results

            # Calculate target temperature for the plot reference lines
            # Target temp = ambient + (target_lambda - lambda0) / thermo_optic_coeff
            target_temp = (
                resonator_params.ambient_c +
                (resonator_params.target_lambda_nm - resonator_params.lambda0_nm) /
                resonator_params.thermo_optic_nm_per_c
            )
            # Lock window in temperature = lock_window_nm / thermo_optic_coeff
            lock_window_temp = (
                resonator_params.lock_window_nm /
                resonator_params.thermo_optic_nm_per_c
            )

            plot_path = config.out_dir / "plot.png"
            plot_simulation_results(
                result=result,
                output_path=plot_path,
                show=args.show_plot,
                target_temp_c=target_temp,
                lock_window_c=lock_window_temp,
            )
            print(f"  - plot.png:        Simulation visualization")
        except RuntimeError as e:
            print(f"  [WARN] Could not generate plot: {e}")

    print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 13: Summary
    # ─────────────────────────────────────────────────────────────────────────
    print("=" * 70)
    if args.open_loop:
        print("Demo Complete! (Open-loop mode)")
        print()
        print("Note: Without a controller, temperature rises with workload.")
        print("Run without --open-loop to see closed-loop thermal control.")
    else:
        print("Demo Complete! (Closed-loop PID control)")
        print()
        print("The PID controller adjusts heater duty to maintain resonance")
        print("alignment despite workload disturbances. Heat-only control:")
        print("  - Resonator runs cold at ambient (below target wavelength)")
        print("  - Heater adds heat to reach target temperature")
        print("  - When workload increases, controller reduces heater duty")
    print("=" * 70)

    if args.verbose:
        print()
        print("Detailed Plant Behavior:")
        if result.timeseries:
            # Sample some key points
            warmup_end = min(args.warmup_cycles, len(result.timeseries) - 1)
            final_idx = len(result.timeseries) - 1

            s_start = result.timeseries[0]
            s_warmup = result.timeseries[warmup_end]
            s_final = result.timeseries[final_idx]

            print(f"  Start  (cycle 0):   T={s_start.temp_c:.2f}°C, "
                  f"detune={s_start.detune_nm * 1000:.1f}pm, "
                  f"heater={s_start.heater_duty:.1%}")
            print(f"  Warmup (cycle {warmup_end}):  T={s_warmup.temp_c:.2f}°C, "
                  f"detune={s_warmup.detune_nm * 1000:.1f}pm, "
                  f"heater={s_warmup.heater_duty:.1%}")
            print(f"  Final  (cycle {final_idx}): T={s_final.temp_c:.2f}°C, "
                  f"detune={s_final.detune_nm * 1000:.1f}pm, "
                  f"heater={s_final.heater_duty:.1%}")

    return 0 if rtl_success else 1


def main() -> int:
    """Entry point for the demo script."""
    args = parse_args()
    return run_demo(args)


if __name__ == "__main__":
    sys.exit(main())
