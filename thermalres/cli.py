"""
Command-line interface for ThermalRes.

This module provides the CLI entry point for running ThermalRes simulations.
It supports both simple baseline runs and advanced configurations including
plant models, controllers, and link monitoring.

Usage:
    # Basic run
    thermalres --name smoke --cycles 100 --chunk-cycles 10 --seed 42

    # With link monitor
    thermalres --name test --cycles 100 --with-link-monitor

    # With RTL validation (requires Verilator)
    thermalres --name rtl_test --cycles 50 --with-link-monitor --validate-rtl

Entry points:
    - thermalres: Direct CLI command (from pyproject.toml)
    - python -m thermalres: Module execution
"""

from __future__ import annotations

import argparse
import sys

from .config import SimConfig
from .cosim.kernel import CoSimKernel
from .cosim.metrics import write_run_artifacts


def _build_parser() -> argparse.ArgumentParser:
    """
    Build the argument parser for the CLI.

    Returns:
        Configured ArgumentParser with all supported options.
    """
    p = argparse.ArgumentParser(
        prog="thermalres",
        description="ThermalRes: Mixed-domain co-simulation framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  thermalres --name smoke --cycles 10
      Run a basic 10-cycle simulation

  thermalres --name test --cycles 100 --with-link-monitor
      Run with link monitor state tracking

  thermalres --name rtl_test --cycles 50 --with-link-monitor --validate-rtl
      Run with RTL validation (requires Verilator)
""",
    )

    # ─────────────────────────────────────────────────────────────────
    # Core simulation parameters
    # ─────────────────────────────────────────────────────────────────
    p.add_argument(
        "--name",
        type=str,
        default="default",
        help="Scenario name for artifact directory (default: %(default)s)",
    )
    p.add_argument(
        "--cycles",
        type=int,
        default=100,
        help="Total cycles to simulate (>= 0) (default: %(default)s)",
    )
    p.add_argument(
        "--cycle-chunks",
        type=int,
        default=10,
        help="Cycles per chunk (> 0) (default: %(default)s)",
    )
    p.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="Output directory (default: artifacts/runs/<timestamp>_<name>)",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed for deterministic event sampling (default: %(default)s)",
    )

    # ─────────────────────────────────────────────────────────────────
    # Link monitor options
    # ─────────────────────────────────────────────────────────────────
    p.add_argument(
        "--with-link-monitor",
        action="store_true",
        help="Enable link monitor state tracking",
    )
    p.add_argument(
        "--no-rtl",
        action="store_true",
        help="Use Python-only simulation (no RTL, no Verilator needed)",
    )
    p.add_argument(
        "--validate-rtl",
        action="store_true",
        help="[Deprecated] Legacy post-run RTL validation. Use --no-rtl instead.",
    )
    p.add_argument(
        "--fails-to-down",
        type=int,
        default=4,
        help="Consecutive CRC fails to trigger link down (default: %(default)s)",
    )
    p.add_argument(
        "--passes-to-up",
        type=int,
        default=8,
        help="Consecutive CRC passes to trigger link up (default: %(default)s)",
    )

    return p


def main(argv: list[str] | None = None) -> int:
    """
    Main CLI entry point.

    Parses arguments, configures the simulation, runs it, and writes
    artifacts to disk.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:])

    Returns:
        Exit code: 0 for success, non-zero for errors
    """
    # ─────────────────────────────────────────────────────────────────
    # Parse command-line arguments
    # ─────────────────────────────────────────────────────────────────
    parser = _build_parser()
    args = parser.parse_args(argv)

    # ─────────────────────────────────────────────────────────────────
    # Create simulation configuration
    # ─────────────────────────────────────────────────────────────────
    config = SimConfig.from_args(
        name=args.name,
        cycles=args.cycles,
        cycle_chunks=args.cycle_chunks,
        seed=args.seed,
        out_dir=args.out_dir,
    )

    # ─────────────────────────────────────────────────────────────────
    # Configure link runner if requested
    # ─────────────────────────────────────────────────────────────────
    link_runner = None
    if args.with_link_monitor:
        # Import here to avoid requiring link_runner when not used
        from .cosim.interfaces import LinkMonitorConfig
        from .cosim.link_runner import LinkRunner

        link_config = LinkMonitorConfig(
            fails_to_down=args.fails_to_down,
            passes_to_up=args.passes_to_up,
            use_rtl=args.validate_rtl,
        )
        link_runner = LinkRunner(link_config)

    # ─────────────────────────────────────────────────────────────────
    # Create and run the simulation kernel
    # Note: Without plant_runner/schedule, the kernel runs in baseline
    # mode and produces only chunk summaries.
    # ─────────────────────────────────────────────────────────────────
    kernel = CoSimKernel(
        config,
        link_runner=link_runner,
    )
    result = kernel.run()

    # ─────────────────────────────────────────────────────────────────
    # Perform RTL validation if requested
    # ─────────────────────────────────────────────────────────────────
    rtl_validation_result = None
    if link_runner is not None and args.validate_rtl:
        try:
            success, message = link_runner.validate_against_rtl()
            rtl_validation_result = (success, message)
            if not success:
                print(f"RTL validation FAILED: {message}", file=sys.stderr)
        except RuntimeError as e:
            print(f"RTL validation error: {e}", file=sys.stderr)
            rtl_validation_result = (False, str(e))

    # ─────────────────────────────────────────────────────────────────
    # Write artifacts to disk
    # ─────────────────────────────────────────────────────────────────
    write_run_artifacts(
        out_path=config.out_dir,
        metrics=result.metrics,
        chunks=result.chunks,
        timeseries=result.timeseries,
        events=result.events,
        link_states=result.link_states,
    )
    metrics_file = config.out_dir / "metrics.json"

    # ─────────────────────────────────────────────────────────────────
    # Print summary to stdout
    # ─────────────────────────────────────────────────────────────────
    print(f"{result.metrics.scenario_name}: ", end="")
    print(f"cycles={result.metrics.total_cycles} ", end="")
    print(f"chunks={result.metrics.total_chunks}", end="")

    # Report link monitor status if enabled
    if result.link_states is not None:
        # Find final link state
        final_link_state = result.link_states[-1] if result.link_states else None
        if final_link_state:
            link_status = "UP" if final_link_state.link_up else "DOWN"
            print(f" link={link_status}", end="")
            print(f" crc_fails={final_link_state.total_crc_fails}", end="")

    print(f" -> {metrics_file}")

    # Report RTL validation result
    if rtl_validation_result is not None:
        success, message = rtl_validation_result
        status = "PASSED" if success else "FAILED"
        print(f"RTL validation: {status} - {message}")

    # Return appropriate exit code
    if rtl_validation_result is not None and not rtl_validation_result[0]:
        return 1

    return 0


# Allow module execution: python -m thermalres
if __name__ == "__main__":
    sys.exit(main())
