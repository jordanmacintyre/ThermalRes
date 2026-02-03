"""
cocotb tests for ThermalRes co-simulation.

These tests run the full mixed-domain simulation with:
- RTL link_monitor with event sampling (cosim_top.sv)
- Python plant models (thermal, resonator, impairment)
- Optional controller (PID or bang-bang)

The tests verify:
1. Basic reset behavior
2. Open-loop simulation (no controller)
3. Closed-loop simulation with PID control
4. Link state transitions under various conditions
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer

# Add project root to path
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

from sim.cocotb.plant_adapter import (
    CosimConfig,
    PlantAdapter,
    create_plant_runner,
    create_workload_schedule,
)
from thermalres.control.pid import PIDController, PIDParams


async def reset_dut(dut, cycles: int = 10):
    """Reset the DUT."""
    dut.rst_n.value = 0
    dut.valid.value = 0
    dut.crc_fail_prob.value = 0
    dut.lfsr_seed.value = 0

    await ClockCycles(dut.clk, cycles)

    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_reset(dut):
    """Test that reset brings link_up=1 and counters=0."""
    # Create clock
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    await reset_dut(dut)

    # Check initial state after reset
    await Timer(1, units="ns")  # Let NBA settle

    assert dut.link_up.value == 1, f"link_up should be 1 after reset, got {dut.link_up.value}"
    assert dut.total_frames.value == 0, "total_frames should be 0 after reset"
    assert dut.total_crc_fails.value == 0, "total_crc_fails should be 0 after reset"
    assert dut.consec_fails.value == 0, "consec_fails should be 0 after reset"
    assert dut.consec_passes.value == 0, "consec_passes should be 0 after reset"


@cocotb.test()
async def test_open_loop_simulation(dut):
    """
    Test open-loop simulation (no controller).

    Without a controller, heater_duty=0 and temperature rises with workload.
    This should cause link failures as detuning increases.
    """
    # Create clock
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    await reset_dut(dut)

    # Configure simulation
    config = CosimConfig(
        cycles=100,
        seed=42,
        warmup_cycles=20,
        warmup_workload=0.3,
        disturbance_workload=0.8,
        pulsed=False,
    )

    # Create plant and schedule (no controller)
    plant_runner = create_plant_runner(config)
    schedule = create_workload_schedule(config)

    # Create adapter
    adapter = PlantAdapter(
        dut=dut,
        plant_runner=plant_runner,
        controller=None,  # Open-loop
        schedule=schedule,
        config=config,
    )

    # Run simulation
    await adapter.run(max_cycles=config.cycles)

    # Get results
    timeseries = adapter.get_timeseries()
    link_states = adapter.get_link_states()

    # Verify we ran the expected number of cycles
    assert len(timeseries) == config.cycles, f"Expected {config.cycles} samples, got {len(timeseries)}"
    assert len(link_states) == config.cycles, f"Expected {config.cycles} link states, got {len(link_states)}"

    # Verify temperature increased (no control to compensate)
    initial_temp = timeseries[0].temp_c
    final_temp = timeseries[-1].temp_c
    assert final_temp > initial_temp, f"Temperature should rise in open-loop, got {initial_temp} -> {final_temp}"

    # Check link state tracking
    final_link = link_states[-1]
    assert final_link.total_frames > 0, "Should have processed frames"

    cocotb.log.info(f"Open-loop: T={initial_temp:.2f}°C -> {final_temp:.2f}°C")
    cocotb.log.info(f"Link: {final_link.total_frames} frames, {final_link.total_crc_fails} fails")


@cocotb.test()
async def test_closed_loop_simulation(dut):
    """
    Test closed-loop simulation with PID controller.

    The controller should maintain temperature near target, keeping
    detuning small and link stable.
    """
    # Create clock
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    await reset_dut(dut)

    # Configure simulation
    config = CosimConfig(
        cycles=200,
        seed=42,
        warmup_cycles=50,
        warmup_workload=0.3,
        disturbance_workload=0.7,
        pulsed=True,
        pulse_period=40,
        pulse_duty=0.5,
    )

    # Create plant and schedule
    plant_runner = create_plant_runner(config)
    schedule = create_workload_schedule(config)

    # Create PID controller
    pid_params = PIDParams(
        kp=5.0,
        ki=0.5,
        kd=0.1,
        min_duty=0.0,
        max_duty=1.0,
        integrator_min=-1.0,
        integrator_max=1.0,
        unlock_boost=0.5,
    )
    controller = PIDController(pid_params)

    # Create adapter
    adapter = PlantAdapter(
        dut=dut,
        plant_runner=plant_runner,
        controller=controller,
        schedule=schedule,
        config=config,
    )

    # Run simulation
    await adapter.run(max_cycles=config.cycles)

    # Get results
    timeseries = adapter.get_timeseries()
    link_states = adapter.get_link_states()

    # Verify we ran the expected number of cycles
    assert len(timeseries) == config.cycles

    # With control, detuning should stay smaller than open-loop
    # Check detuning at the end of simulation (after settling)
    late_detunes = [abs(s.detune_nm) for s in timeseries[-50:]]
    avg_detune = sum(late_detunes) / len(late_detunes)

    cocotb.log.info(f"Closed-loop: avg late detune = {avg_detune * 1000:.1f}pm")

    # Check heater duty is being used (not stuck at 0 or 1)
    heater_duties = [s.heater_duty for s in timeseries]
    avg_duty = sum(heater_duties) / len(heater_duties)
    assert 0.1 < avg_duty < 0.9, f"Heater duty should be active, got avg={avg_duty:.2f}"

    # Check link state
    final_link = link_states[-1]
    cocotb.log.info(f"Link: {final_link.total_frames} frames, {final_link.total_crc_fails} fails, up={final_link.link_up}")


@cocotb.test()
async def test_link_state_transitions(dut):
    """
    Test that link state transitions correctly with varying impairment.

    We manually drive crc_fail_prob to force state transitions and verify
    the hysteresis behavior matches expected thresholds.
    """
    # Create clock
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    await reset_dut(dut)

    # Defaults: FAILS_TO_DOWN=4, PASSES_TO_UP=8

    # Phase 1: Drive high failure probability (should go DOWN after 4 fails)
    cocotb.log.info("Phase 1: High failure rate")
    dut.crc_fail_prob.value = 65535  # 100% failure prob
    dut.valid.value = 1

    for _ in range(10):
        await RisingEdge(dut.clk)
        await Timer(1, units="ns")

    # Link should be DOWN
    assert dut.link_up.value == 0, f"Link should be DOWN after consecutive fails"
    cocotb.log.info(f"  link_up={dut.link_up.value}, consec_fails={dut.consec_fails.value}")

    # Phase 2: Drive zero failure probability (should go UP after 8 passes)
    cocotb.log.info("Phase 2: Zero failure rate")
    dut.crc_fail_prob.value = 0  # 0% failure prob

    for _ in range(15):
        await RisingEdge(dut.clk)
        await Timer(1, units="ns")

    # Link should be UP
    assert dut.link_up.value == 1, f"Link should be UP after consecutive passes"
    cocotb.log.info(f"  link_up={dut.link_up.value}, consec_passes={dut.consec_passes.value}")


@cocotb.test()
async def test_artifact_generation(dut):
    """Test that artifacts are generated correctly."""
    import tempfile

    # Create clock
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    await reset_dut(dut)

    # Short simulation
    config = CosimConfig(cycles=50, seed=42)
    plant_runner = create_plant_runner(config)
    schedule = create_workload_schedule(config)

    adapter = PlantAdapter(
        dut=dut,
        plant_runner=plant_runner,
        schedule=schedule,
        config=config,
    )

    await adapter.run(max_cycles=config.cycles)

    # Write artifacts to temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter.write_artifacts(tmpdir)

        # Check files were created
        import json
        from pathlib import Path

        out_path = Path(tmpdir)

        assert (out_path / "timeseries.json").exists()
        assert (out_path / "link_state.json").exists()
        assert (out_path / "metrics.json").exists()

        # Check content
        with open(out_path / "metrics.json") as f:
            metrics = json.load(f)
            assert metrics["total_cycles"] == config.cycles

        cocotb.log.info(f"Artifacts written successfully")
