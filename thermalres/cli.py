from __future__ import annotations

import argparse

from .config import SimConfig
from .cosim.kernel import CoSimKernel
from .cosim.metrics import write_run_artifacts


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="thermalres", 
        description="ThermalRes runner (Milestone 1)"
    )
    p.add_argument(
        "--name", 
        type=str, 
        default="default", 
        help="Scenario name"
    )
    p.add_argument(
        "--cycles", 
        type=int, 
        default=100, 
        help="Total cycles to simulate (>= 0)"
    )
    p.add_argument(
        "--cycle-chunks", 
        type=int, 
        default=10, 
        help="Cycles per chunk (> 0)"
    )
    p.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="Optional output directory (default: artifacts/runs/<timestamp>_<name>)",
    )
    p.add_argument(
        "--seed", 
        type=int, 
        default=0, 
        help="Determinism seed (integer)"
    )
    
    return p


def main(argv: list[str] | None = None):
    parser = _build_parser()
    args = parser.parse_args(argv)

    config = SimConfig.from_args(
        name=args.name,
        cycles=args.cycles,
        cycle_chunks=args.cycle_chunks,
        seed=args.seed,
        out_dir=args.out_dir,
    )

    kernel = CoSimKernel(config)
    metrics, chunks, timeseries = kernel.run()

    write_run_artifacts(
        out_path=config.out_dir,
        metrics=metrics,
        chunks=chunks,
        timeseries=timeseries,
    )
    metrics_file = config.out_dir.joinpath("metrics.json")

    print(f"{metrics.scenario_name}: ", end="")
    print(f"cycles={metrics.total_cycles} ", end="")
    print(f"chunks={metrics.total_chunks} -> {metrics_file}")
