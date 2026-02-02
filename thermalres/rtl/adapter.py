"""
RTL adapter for link_monitor.

Provides a Python interface to run the link_monitor RTL through Verilator
and cocotb. This enables equivalence testing between the Python reference
model (LinkMonitorRef) and the actual SystemVerilog implementation.

Integration Strategy:
1. Generate pattern file (valid, crc_fail per cycle) and sample cycle list
2. Generate cocotb test script with embedded parameters
3. Generate Makefile with Verilator flags (-G for parameter override)
4. Run make in temp directory → Verilator compiles RTL → cocotb drives simulation
5. Parse output file with sampled RTL state
6. Return RtlLinkSample objects for comparison with Python samples

The adapter handles the complexity of temp directories, environment variables,
Makefile generation, and output parsing so callers can simply pass a pattern
and receive samples.

Key Design Decisions:
- Parameters (FAILS_TO_DOWN, PASSES_TO_UP) are passed via Verilator's -G option
  at compile time, enabling testing with different threshold configurations.
- A 1ns Timer delay after RisingEdge ensures non-blocking assignments (NBA)
  have completed before sampling outputs (standard cocotb pattern for registers).
- Paths to RTL sources are computed dynamically from __file__ location,
  avoiding hardcoded absolute paths.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RtlLinkSample:
    """
    Link monitor sample from RTL.

    Matches LinkMonitorState but frozen for immutability.
    """

    cycle: int
    link_up: bool
    total_frames: int
    total_crc_fails: int
    consec_fails: int
    consec_passes: int


def check_verilator_available() -> bool:
    """Check if Verilator is available on PATH."""
    try:
        result = subprocess.run(
            ["verilator", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _get_rtl_dir() -> Path:
    """
    Get the absolute path to the RTL source directory.

    Returns:
        Path to the rtl/ directory containing link_monitor.sv and top.sv.
    """
    # This file is at thermalres/rtl/adapter.py
    # RTL sources are at rtl/ (two levels up from this file's directory)
    this_file = Path(__file__).resolve()
    package_root = this_file.parent.parent.parent  # Up to ThermalRes/
    rtl_dir = package_root / "rtl"
    return rtl_dir


def run_link_monitor_rtl(
    pattern: list[tuple[bool, bool]],
    fails_to_down: int = 4,
    passes_to_up: int = 8,
    sample_cycles: list[int] | None = None,
) -> list[RtlLinkSample]:
    """
    Run link_monitor RTL with given CRC fail pattern.

    Args:
        pattern: List of (valid, crc_fail) tuples, one per cycle
        fails_to_down: FAILS_TO_DOWN parameter
        passes_to_up: PASSES_TO_UP parameter
        sample_cycles: Cycles to sample (default: all cycles)

    Returns:
        List of RtlLinkSample at requested cycles

    Raises:
        RuntimeError: If Verilator or cocotb not available
    """
    # Check dependencies
    if not check_verilator_available():
        raise RuntimeError(
            "Verilator not found. Install with: "
            "conda install -c conda-forge verilator (or apt/brew)"
        )

    try:
        import cocotb  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "cocotb not installed. Install with: pip install cocotb"
        )

    # Default: sample all cycles
    if sample_cycles is None:
        sample_cycles = list(range(len(pattern)))

    # Create temporary directory for simulation
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Write pattern to file for test to read
        pattern_file = tmppath / "pattern.txt"
        with pattern_file.open("w") as f:
            for valid, crc_fail in pattern:
                f.write(f"{int(valid)} {int(crc_fail)}\n")

        # Write sample cycles
        sample_file = tmppath / "samples.txt"
        with sample_file.open("w") as f:
            for cycle in sample_cycles:
                f.write(f"{cycle}\n")

        # Write test script
        test_script = tmppath / "test_adapter.py"
        test_script.write_text(_generate_adapter_test(fails_to_down, passes_to_up))

        # Write Makefile with absolute paths to RTL sources and parameters
        makefile = tmppath / "Makefile"
        makefile.write_text(
            _generate_makefile(_get_rtl_dir(), fails_to_down, passes_to_up)
        )

        # Run simulation
        env = os.environ.copy()
        env["PATTERN_FILE"] = str(pattern_file)
        env["SAMPLE_FILE"] = str(sample_file)
        env["OUTPUT_FILE"] = str(tmppath / "output.txt")

        result = subprocess.run(
            ["make", "-f", str(makefile)],
            cwd=tmppath,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"RTL simulation failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )

        # Read results
        output_file = tmppath / "output.txt"
        if not output_file.exists():
            raise RuntimeError("RTL simulation did not produce output file")

        samples = []
        with output_file.open() as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 6:
                    samples.append(
                        RtlLinkSample(
                            cycle=int(parts[0]),
                            link_up=bool(int(parts[1])),
                            total_frames=int(parts[2]),
                            total_crc_fails=int(parts[3]),
                            consec_fails=int(parts[4]),
                            consec_passes=int(parts[5]),
                        )
                    )

        return samples


def _generate_adapter_test(fails_to_down: int, passes_to_up: int) -> str:
    """
    Generate cocotb test script for adapter.

    This generates a Python test script that cocotb will run to drive
    the RTL simulation. The test:
    1. Resets the DUT
    2. Applies the input pattern (valid, crc_fail) cycle by cycle
    3. Samples outputs at requested cycles
    4. Writes samples to output file

    Note on timing:
        RTL uses registered outputs (always_ff). After await RisingEdge(),
        we add a small Timer delay to let non-blocking assignments (NBA)
        complete before sampling outputs. Without this delay, we would
        sample stale values from the previous cycle.

    Args:
        fails_to_down: FAILS_TO_DOWN parameter (passed via Makefile -G option).
        passes_to_up: PASSES_TO_UP parameter (passed via Makefile -G option).

    Returns:
        Complete cocotb test script as a string.
    """
    return f'''"""Adapter test for link_monitor."""
import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

@cocotb.test()
async def test_adapter(dut):
    """Run pattern and capture samples.

    Parameters FAILS_TO_DOWN={fails_to_down} and PASSES_TO_UP={passes_to_up}
    are passed via Verilator's -G option at compile time.
    """

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst_n.value = 0
    dut.valid.value = 0
    dut.crc_fail.value = 0
    await Timer(20, units="ns")
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # Read pattern
    pattern_file = os.environ.get("PATTERN_FILE", "pattern.txt")
    pattern = []
    with open(pattern_file) as f:
        for line in f:
            valid, crc_fail = map(int, line.split())
            pattern.append((valid, crc_fail))

    # Read sample cycles
    sample_file = os.environ.get("SAMPLE_FILE", "samples.txt")
    sample_cycles = set()
    with open(sample_file) as f:
        for line in f:
            sample_cycles.add(int(line.strip()))

    # Open output file
    output_file = os.environ.get("OUTPUT_FILE", "output.txt")
    with open(output_file, "w") as out:
        # Run pattern
        for cycle, (valid, crc_fail) in enumerate(pattern):
            # Apply inputs before clock edge
            dut.valid.value = valid
            dut.crc_fail.value = crc_fail

            # Wait for rising edge - RTL processes inputs on this edge
            await RisingEdge(dut.clk)

            # CRITICAL: Wait for non-blocking assignments (NBA) to complete
            # RTL registers update on the clock edge, but in simulation the
            # new values aren't visible until the NBA phase completes.
            # A small delay (1ns) ensures we sample the updated values.
            await Timer(1, units="ns")

            # Sample outputs if this cycle is requested
            # Outputs now reflect the result of processing this cycle's inputs
            if cycle in sample_cycles:
                out.write(f"{{cycle}} {{int(dut.link_up.value)}} ")
                out.write(f"{{int(dut.total_frames.value)}} ")
                out.write(f"{{int(dut.total_crc_fails.value)}} ")
                out.write(f"{{int(dut.consec_fails.value)}} ")
                out.write(f"{{int(dut.consec_passes.value)}}\\n")
'''


def _generate_makefile(
    rtl_dir: Path,
    fails_to_down: int = 4,
    passes_to_up: int = 8,
) -> str:
    """
    Generate Makefile for adapter simulation.

    Args:
        rtl_dir: Absolute path to the RTL source directory.
        fails_to_down: FAILS_TO_DOWN parameter for the RTL module.
        passes_to_up: PASSES_TO_UP parameter for the RTL module.

    Returns:
        Makefile content as a string.
    """
    # Use absolute paths to RTL sources for robustness
    link_monitor_sv = rtl_dir / "link_monitor.sv"
    top_sv = rtl_dir / "top.sv"

    # Use Verilator's -G option to override parameters at compile time
    # This allows testing with different threshold configurations
    return f"""SIM ?= verilator
TOPLEVEL = top
VERILOG_SOURCES = {link_monitor_sv} {top_sv}
MODULE = test_adapter
EXTRA_ARGS += --trace --trace-structs
EXTRA_ARGS += -GFAILS_TO_DOWN={fails_to_down} -GPASSES_TO_UP={passes_to_up}
COCOTB_REDUCED_LOG_FMT = 1

include $(shell cocotb-config --makefiles)/Makefile.sim
"""
