"""
cocotb tests for link_monitor RTL.

Tests the SystemVerilog link_monitor module using Verilator.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


@cocotb.test()
async def test_reset(dut):
    """Test that reset brings link_up=1 and counters=0."""
    # Create clock
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    # Assert reset
    dut.rst_n.value = 0
    dut.valid.value = 0
    dut.crc_fail.value = 0
    await Timer(20, unit="ns")

    # Deassert reset
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # Check initial state
    assert dut.link_up.value == 1, f"link_up should be 1 after reset, got {dut.link_up.value}"
    assert dut.total_frames.value == 0, "total_frames should be 0 after reset"
    assert dut.total_crc_fails.value == 0, "total_crc_fails should be 0 after reset"
    assert dut.consec_fails.value == 0, "consec_fails should be 0 after reset"
    assert dut.consec_passes.value == 0, "consec_passes should be 0 after reset"


@cocotb.test()
async def test_link_down_on_consecutive_fails(dut):
    """Test that link goes down after FAILS_TO_DOWN consecutive failures."""
    # Create clock
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst_n.value = 0
    dut.valid.value = 0
    dut.crc_fail.value = 0
    await Timer(20, unit="ns")
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # Get FAILS_TO_DOWN parameter (default 4)
    fails_to_down = 4

    # Send consecutive failures
    for i in range(fails_to_down):
        dut.valid.value = 1
        dut.crc_fail.value = 1
        await RisingEdge(dut.clk)
        # Wait for outputs to update (need one more edge to see registered outputs)
        await RisingEdge(dut.clk)

        # Link should still be up until we hit the threshold
        if i < fails_to_down - 1:
            assert dut.link_up.value == 1, f"link_up should still be 1 at fail {i+1}"
        else:
            # At threshold, link should go down
            assert dut.link_up.value == 0, f"link_up should be 0 after {fails_to_down} fails"

    # Check counters
    assert dut.total_frames.value == fails_to_down
    assert dut.total_crc_fails.value == fails_to_down
    assert dut.consec_fails.value == fails_to_down


@cocotb.test()
async def test_link_up_on_consecutive_passes(dut):
    """Test that link comes up after PASSES_TO_UP consecutive passes."""
    # Create clock
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst_n.value = 0
    dut.valid.value = 0
    dut.crc_fail.value = 0
    await Timer(20, unit="ns")
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    fails_to_down = 4
    passes_to_up = 8

    # First, take link down with consecutive failures
    for _ in range(fails_to_down):
        dut.valid.value = 1
        dut.crc_fail.value = 1
        await RisingEdge(dut.clk)

    # Wait one more edge to see link_down
    await RisingEdge(dut.clk)
    assert dut.link_up.value == 0, "Link should be down"

    # Now send consecutive passes
    for i in range(passes_to_up):
        dut.valid.value = 1
        dut.crc_fail.value = 0
        await RisingEdge(dut.clk)
        # Wait for outputs
        await RisingEdge(dut.clk)

        # Link should still be down until we hit the threshold
        if i < passes_to_up - 1:
            assert dut.link_up.value == 0, f"link_up should still be 0 at pass {i+1}"
        else:
            # At threshold, link should come up
            assert dut.link_up.value == 1, f"link_up should be 1 after {passes_to_up} passes"

    # Check counters
    assert dut.consec_passes.value == passes_to_up
    assert dut.consec_fails.value == 0


@cocotb.test()
async def test_counters_update(dut):
    """Test that counters update correctly."""
    # Create clock
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst_n.value = 0
    dut.valid.value = 0
    dut.crc_fail.value = 0
    await Timer(20, unit="ns")
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # Send mix of passes and fails
    pattern = [False, False, True, False, True, True, False]

    expected_frames = 0
    expected_fails = 0

    for crc_fail in pattern:
        dut.valid.value = 1
        dut.crc_fail.value = int(crc_fail)
        await RisingEdge(dut.clk)

        expected_frames += 1
        if crc_fail:
            expected_fails += 1

    # Wait one more edge to see final counter values
    await RisingEdge(dut.clk)

    # Check total counters
    assert dut.total_frames.value == expected_frames
    assert dut.total_crc_fails.value == expected_fails


@cocotb.test()
async def test_no_update_when_not_valid(dut):
    """Test that counters don't update when valid=0."""
    # Create clock
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst_n.value = 0
    dut.valid.value = 0
    dut.crc_fail.value = 0
    await Timer(20, unit="ns")
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # Send some valid frames
    for _ in range(3):
        dut.valid.value = 1
        dut.crc_fail.value = 0
        await RisingEdge(dut.clk)

    # Wait to see updated counters
    await RisingEdge(dut.clk)
    initial_frames = int(dut.total_frames.value)

    # Now send cycles with valid=0
    for _ in range(5):
        dut.valid.value = 0
        dut.crc_fail.value = 1  # Should be ignored
        await RisingEdge(dut.clk)

    # Counters should not have changed
    assert dut.total_frames.value == initial_frames
    assert dut.total_crc_fails.value == 0
