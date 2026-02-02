"""
Plotting utilities for ThermalRes simulation artifacts.

This module provides functions for generating visualizations from simulation
results. Plots can be generated directly from RunResult objects or from
artifact files on disk.

Requires matplotlib: pip install thermalres[plot]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .interfaces import RunResult


def check_matplotlib_available() -> bool:
    """Check if matplotlib is available."""
    try:
        import matplotlib
        return True
    except ImportError:
        return False


def plot_simulation_results(
    result: "RunResult",
    output_path: Path | str | None = None,
    show: bool = False,
    title: str | None = None,
    target_temp_c: float | None = None,
    lock_window_c: float | None = None,
) -> None:
    """
    Generate a multi-panel plot of simulation results.

    Creates a 4-panel figure showing:
    1. Temperature over time (with optional target range)
    2. Detuning and CRC failure probability
    3. Heater duty cycle and workload
    4. Link state (if available)

    Args:
        result: RunResult from a simulation run.
        output_path: Path to save the figure (PNG, PDF, etc.).
                     If None and show=False, saves to 'simulation_plot.png'.
        show: If True, display the plot interactively.
        title: Optional title for the figure.
        target_temp_c: Target temperature for resonance alignment (°C).
                       If provided, draws horizontal reference lines.
        lock_window_c: Temperature tolerance around target (±°C).
                       If provided with target_temp_c, draws upper/lower bounds.

    Raises:
        RuntimeError: If matplotlib is not installed.
    """
    if not check_matplotlib_available():
        raise RuntimeError(
            "matplotlib not installed. Install with: pip install thermalres[plot]"
        )

    import matplotlib.pyplot as plt

    # Extract data from timeseries
    if not result.timeseries:
        raise ValueError("No timeseries data in result")

    cycles = [s.cycle for s in result.timeseries]
    temps = [s.temp_c for s in result.timeseries]
    detunes = [s.detune_nm for s in result.timeseries]
    crc_probs = [s.crc_fail_prob for s in result.timeseries]
    heater_duties = [s.heater_duty for s in result.timeseries]
    workloads = [s.workload_frac for s in result.timeseries]

    # Determine number of panels
    has_link_states = result.link_states is not None and len(result.link_states) > 0
    n_panels = 4 if has_link_states else 3

    # Create figure
    fig, axes = plt.subplots(n_panels, 1, figsize=(10, 2.5 * n_panels), sharex=True)
    if n_panels == 1:
        axes = [axes]

    # Panel 1: Temperature
    ax1 = axes[0]
    ax1.plot(cycles, temps, "r-", linewidth=1.5, label="Temperature")

    # Add target temperature reference lines if provided
    if target_temp_c is not None and lock_window_c is not None:
        upper_bound = target_temp_c + lock_window_c
        lower_bound = target_temp_c - lock_window_c
        ax1.axhline(y=upper_bound, color="black", linestyle=":", linewidth=1.5,
                    label=f"Lock window ({lower_bound:.1f}-{upper_bound:.1f}°C)")
        ax1.axhline(y=lower_bound, color="black", linestyle=":", linewidth=1.5)

    ax1.set_ylabel("Temperature (°C)", color="r")
    ax1.tick_params(axis="y", labelcolor="r")
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="upper left")

    # Panel 2: Detuning and CRC probability
    ax2 = axes[1]
    color_detune = "tab:blue"
    color_crc = "tab:orange"

    ax2.plot(cycles, detunes, color=color_detune, linewidth=1.5, label="Detuning")
    ax2.set_ylabel("Detuning (nm)", color=color_detune)
    ax2.tick_params(axis="y", labelcolor=color_detune)

    ax2_twin = ax2.twinx()
    ax2_twin.plot(cycles, crc_probs, color=color_crc, linewidth=1.5,
                  linestyle="--", label="CRC Fail Prob")
    ax2_twin.set_ylabel("CRC Fail Probability", color=color_crc)
    ax2_twin.tick_params(axis="y", labelcolor=color_crc)
    ax2_twin.set_ylim(-0.05, 1.05)

    ax2.grid(True, alpha=0.3)

    # Combined legend
    lines1, labels1 = ax2.get_legend_handles_labels()
    lines2, labels2 = ax2_twin.get_legend_handles_labels()
    ax2.legend(lines1 + lines2, labels1 + labels2, loc="upper left")

    # Panel 3: Heater duty and workload
    ax3 = axes[2]
    ax3.plot(cycles, heater_duties, "g-", linewidth=1.5, label="Heater Duty")
    ax3.plot(cycles, workloads, "m--", linewidth=1.5, label="Workload")
    ax3.set_ylabel("Duty Cycle / Fraction")
    ax3.set_ylim(-0.05, 1.05)
    ax3.grid(True, alpha=0.3)
    ax3.legend(loc="upper left")

    # Panel 4: Link state (if available)
    if has_link_states:
        ax4 = axes[3]
        link_cycles = [s.cycle for s in result.link_states]
        link_up = [1 if s.link_up else 0 for s in result.link_states]
        consec_fails = [s.consec_fails for s in result.link_states]
        consec_passes = [s.consec_passes for s in result.link_states]

        # Link state as filled area
        ax4.fill_between(link_cycles, link_up, alpha=0.3, color="green",
                         step="post", label="Link UP")
        ax4.step(link_cycles, link_up, where="post", color="green", linewidth=2)

        # Consecutive counters on secondary axis
        ax4_twin = ax4.twinx()
        ax4_twin.plot(link_cycles, consec_fails, "r-", linewidth=1,
                      alpha=0.7, label="Consec Fails")
        ax4_twin.plot(link_cycles, consec_passes, "b-", linewidth=1,
                      alpha=0.7, label="Consec Passes")
        ax4_twin.set_ylabel("Consecutive Count")

        ax4.set_ylabel("Link State")
        ax4.set_yticks([0, 1])
        ax4.set_yticklabels(["DOWN", "UP"])
        ax4.set_ylim(-0.1, 1.1)
        ax4.grid(True, alpha=0.3)

        # Combined legend
        lines1, labels1 = ax4.get_legend_handles_labels()
        lines2, labels2 = ax4_twin.get_legend_handles_labels()
        ax4.legend(lines1 + lines2, labels1 + labels2, loc="upper right")

        ax4.set_xlabel("Cycle")
    else:
        ax3.set_xlabel("Cycle")

    # Title
    if title:
        fig.suptitle(title, fontsize=14, fontweight="bold")
    else:
        scenario = result.metrics.scenario_name
        total_cycles = result.metrics.total_cycles
        fig.suptitle(f"ThermalRes Simulation: {scenario} ({total_cycles} cycles)",
                     fontsize=14, fontweight="bold")

    plt.tight_layout()

    # Save or show
    if output_path:
        output_path = Path(output_path)
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"Plot saved to: {output_path}")
    elif not show:
        plt.savefig("simulation_plot.png", dpi=150, bbox_inches="tight")
        print("Plot saved to: simulation_plot.png")

    if show:
        plt.show()

    plt.close(fig)


def plot_from_artifacts(
    artifact_dir: Path | str,
    output_path: Path | str | None = None,
    show: bool = False,
) -> None:
    """
    Generate a plot from artifact files on disk.

    Loads timeseries.json and optionally link_state.json from the artifact
    directory and generates a visualization.

    Args:
        artifact_dir: Path to the artifact directory containing JSON files.
        output_path: Path to save the figure. If None, saves to artifact_dir/plot.png.
        show: If True, display the plot interactively.

    Raises:
        RuntimeError: If matplotlib is not installed.
        FileNotFoundError: If required artifact files are missing.
    """
    if not check_matplotlib_available():
        raise RuntimeError(
            "matplotlib not installed. Install with: pip install thermalres[plot]"
        )

    import matplotlib.pyplot as plt

    artifact_dir = Path(artifact_dir)

    # Load metrics
    metrics_path = artifact_dir / "metrics.json"
    if not metrics_path.exists():
        raise FileNotFoundError(f"metrics.json not found in {artifact_dir}")

    with metrics_path.open() as f:
        metrics_data = json.load(f)

    # Load timeseries
    timeseries_path = artifact_dir / "timeseries.json"
    if not timeseries_path.exists():
        raise FileNotFoundError(f"timeseries.json not found in {artifact_dir}")

    with timeseries_path.open() as f:
        timeseries_data = json.load(f)

    samples = timeseries_data.get("samples", [])
    if not samples:
        raise ValueError("No samples in timeseries.json")

    # Extract data
    cycles = [s["cycle"] for s in samples]
    temps = [s["temp_c"] for s in samples]
    detunes = [s["detune_nm"] for s in samples]
    crc_probs = [s["crc_fail_prob"] for s in samples]
    heater_duties = [s["heater_duty"] for s in samples]
    workloads = [s["workload_frac"] for s in samples]

    # Try to load link state
    link_state_path = artifact_dir / "link_state.json"
    link_states = None
    if link_state_path.exists():
        with link_state_path.open() as f:
            link_data = json.load(f)
        link_states = link_data.get("samples", [])

    has_link_states = link_states is not None and len(link_states) > 0
    n_panels = 4 if has_link_states else 3

    # Create figure
    fig, axes = plt.subplots(n_panels, 1, figsize=(10, 2.5 * n_panels), sharex=True)
    if n_panels == 1:
        axes = [axes]

    # Panel 1: Temperature
    ax1 = axes[0]
    ax1.plot(cycles, temps, "r-", linewidth=1.5, label="Temperature")
    ax1.set_ylabel("Temperature (°C)", color="r")
    ax1.tick_params(axis="y", labelcolor="r")
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="upper left")

    # Panel 2: Detuning and CRC probability
    ax2 = axes[1]
    color_detune = "tab:blue"
    color_crc = "tab:orange"

    ax2.plot(cycles, detunes, color=color_detune, linewidth=1.5, label="Detuning")
    ax2.set_ylabel("Detuning (nm)", color=color_detune)
    ax2.tick_params(axis="y", labelcolor=color_detune)

    ax2_twin = ax2.twinx()
    ax2_twin.plot(cycles, crc_probs, color=color_crc, linewidth=1.5,
                  linestyle="--", label="CRC Fail Prob")
    ax2_twin.set_ylabel("CRC Fail Probability", color=color_crc)
    ax2_twin.tick_params(axis="y", labelcolor=color_crc)
    ax2_twin.set_ylim(-0.05, 1.05)

    ax2.grid(True, alpha=0.3)

    lines1, labels1 = ax2.get_legend_handles_labels()
    lines2, labels2 = ax2_twin.get_legend_handles_labels()
    ax2.legend(lines1 + lines2, labels1 + labels2, loc="upper left")

    # Panel 3: Heater duty and workload
    ax3 = axes[2]
    ax3.plot(cycles, heater_duties, "g-", linewidth=1.5, label="Heater Duty")
    ax3.plot(cycles, workloads, "m--", linewidth=1.5, label="Workload")
    ax3.set_ylabel("Duty Cycle / Fraction")
    ax3.set_ylim(-0.05, 1.05)
    ax3.grid(True, alpha=0.3)
    ax3.legend(loc="upper left")

    # Panel 4: Link state (if available)
    if has_link_states:
        ax4 = axes[3]
        link_cycles = [s["cycle"] for s in link_states]
        link_up = [1 if s["link_up"] else 0 for s in link_states]
        consec_fails = [s["consec_fails"] for s in link_states]
        consec_passes = [s["consec_passes"] for s in link_states]

        ax4.fill_between(link_cycles, link_up, alpha=0.3, color="green",
                         step="post", label="Link UP")
        ax4.step(link_cycles, link_up, where="post", color="green", linewidth=2)

        ax4_twin = ax4.twinx()
        ax4_twin.plot(link_cycles, consec_fails, "r-", linewidth=1,
                      alpha=0.7, label="Consec Fails")
        ax4_twin.plot(link_cycles, consec_passes, "b-", linewidth=1,
                      alpha=0.7, label="Consec Passes")
        ax4_twin.set_ylabel("Consecutive Count")

        ax4.set_ylabel("Link State")
        ax4.set_yticks([0, 1])
        ax4.set_yticklabels(["DOWN", "UP"])
        ax4.set_ylim(-0.1, 1.1)
        ax4.grid(True, alpha=0.3)

        lines1, labels1 = ax4.get_legend_handles_labels()
        lines2, labels2 = ax4_twin.get_legend_handles_labels()
        ax4.legend(lines1 + lines2, labels1 + labels2, loc="upper right")

        ax4.set_xlabel("Cycle")
    else:
        ax3.set_xlabel("Cycle")

    # Title from metrics
    run_info = metrics_data.get("run", {})
    scenario = run_info.get("scenario_name", "unknown")
    total_cycles = run_info.get("total_cycles", len(cycles))
    fig.suptitle(f"ThermalRes Simulation: {scenario} ({total_cycles} cycles)",
                 fontsize=14, fontweight="bold")

    plt.tight_layout()

    # Determine output path
    if output_path is None:
        output_path = artifact_dir / "plot.png"
    else:
        output_path = Path(output_path)

    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"Plot saved to: {output_path}")

    if show:
        plt.show()

    plt.close(fig)
