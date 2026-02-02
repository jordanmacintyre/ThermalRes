"""
Artifact writing for ThermalRes simulation runs.

This module provides functions for writing simulation artifacts to disk.
Artifacts are first-class outputs of the simulation, enabling:
- Regression testing (compare outputs across runs)
- Offline analysis (load and analyze without re-running)
- Integration with external tools (JSON/JSONL formats)

Artifact files produced:
- metrics.json: Run metadata and chunk summaries
- timeseries.json: Per-chunk plant state samples
- events.jsonl: Per-cycle CRC failure events
- link_state.json: Per-cycle link monitor state

All artifacts use JSON for human readability and tooling compatibility.
JSONL (JSON Lines) is used for events to support streaming and large runs.

Example artifact directory structure:
```
artifacts/runs/20240115_120000_example/
├── metrics.json       # Run metadata
├── timeseries.json    # Plant state history
├── events.jsonl       # CRC event stream
└── link_state.json    # Link monitor history
```
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .interfaces import (
    ChunkSummary,
    CrcEvent,
    LinkStateSample,
    RunMetrics,
    TimeSeriesSample,
)


def write_run_artifacts(
    *,
    out_path: Path,
    metrics: RunMetrics,
    chunks: list[ChunkSummary],
    timeseries: list[TimeSeriesSample] | None = None,
    events: list[CrcEvent] | None = None,
    link_states: list[LinkStateSample] | None = None,
) -> None:
    """
    Write all simulation artifacts to disk.

    This is the main entry point for artifact generation. It creates
    the output directory (if needed) and writes all artifact files.
    Each artifact type is written only if data is provided.

    Args:
        out_path: Output directory path. Will be created if it doesn't
                  exist, including parent directories.
        metrics: Run-level metrics containing timing, cycle counts,
                 and scenario name. Always written.
        chunks: List of chunk summaries with cycle ranges. Written
                as part of metrics.json.
        timeseries: Optional list of time-series samples.
                    When provided and non-empty, writes timeseries.json.
        events: Optional list of CRC events.
                When provided and non-empty, writes events.jsonl.
        link_states: Optional list of link state samples.
                     When provided and non-empty, writes link_state.json.

    Example:
        >>> from thermalres.cosim.metrics import write_run_artifacts
        >>> write_run_artifacts(
        ...     out_path=Path("artifacts/runs/my_run"),
        ...     metrics=result.metrics,
        ...     chunks=result.chunks,
        ...     timeseries=result.timeseries,
        ...     events=result.events,
        ...     link_states=result.link_states,
        ... )
    """
    # ─────────────────────────────────────────────────────────────────
    # Ensure output directory exists
    # ─────────────────────────────────────────────────────────────────
    out_path = Path(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────
    # Write metrics.json
    # Contains run-level metadata and chunk summaries
    # Always written regardless of other artifacts
    # ─────────────────────────────────────────────────────────────────
    _write_metrics_json(out_path, metrics, chunks)

    # ─────────────────────────────────────────────────────────────────
    # Write timeseries.json
    # Contains per-chunk plant state samples
    # ─────────────────────────────────────────────────────────────────
    if timeseries is not None and len(timeseries) > 0:
        _write_timeseries_json(out_path, timeseries)

    # ─────────────────────────────────────────────────────────────────
    # Write events.jsonl
    # Contains per-cycle CRC events in JSON Lines format
    # ─────────────────────────────────────────────────────────────────
    if events is not None and len(events) > 0:
        _write_events_jsonl(out_path, events)

    # ─────────────────────────────────────────────────────────────────
    # Write link_state.json
    # Contains per-cycle link monitor state samples
    # ─────────────────────────────────────────────────────────────────
    if link_states is not None and len(link_states) > 0:
        _write_link_state_json(out_path, link_states)


def _write_metrics_json(
    out_path: Path,
    metrics: RunMetrics,
    chunks: list[ChunkSummary],
) -> None:
    """
    Write metrics.json artifact.

    Schema:
    {
        "run": {
            "total_cycles": int,
            "total_chunks": int,
            "start_time": str (ISO 8601),
            "finish_time": str (ISO 8601),
            "scenario_name": str
        },
        "chunks": [
            {
                "chunk_idx": int,
                "start_cycle": int,
                "end_cycle": int
            },
            ...
        ]
    }
    """
    payload = {
        "run": asdict(metrics),
        "chunks": [asdict(c) for c in chunks],
    }

    metrics_path = out_path / "metrics.json"
    metrics_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_timeseries_json(
    out_path: Path,
    timeseries: list[TimeSeriesSample],
) -> None:
    """
    Write timeseries.json artifact.

    Schema:
    {
        "samples": [
            {
                "cycle": int,
                "temp_c": float,
                "detune_nm": float,
                "locked": bool,
                "crc_fail_prob": float,
                "heater_duty": float,
                "workload_frac": float,
                "controller_error": float | null,
                "controller_active": bool
            },
            ...
        ]
    }
    """
    timeseries_payload = {
        "samples": [asdict(s) for s in timeseries],
    }
    timeseries_path = out_path / "timeseries.json"
    timeseries_path.write_text(
        json.dumps(timeseries_payload, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_events_jsonl(
    out_path: Path,
    events: list[CrcEvent],
) -> None:
    """
    Write events.jsonl artifact.

    Uses JSON Lines format (one JSON object per line) for:
    - Streaming efficiency with large event counts
    - Easy line-by-line processing
    - Append-friendly format

    Each line schema:
    {"cycle": int, "chunk_idx": int, "crc_fail": bool, "crc_fail_prob": float}
    """
    events_path = out_path / "events.jsonl"
    with events_path.open("w", encoding="utf-8") as f:
        for event in events:
            # Write each event as a single JSON line
            json.dump(asdict(event), f, sort_keys=True)
            f.write("\n")


def _write_link_state_json(
    out_path: Path,
    link_states: list[LinkStateSample],
) -> None:
    """
    Write link_state.json artifact.

    Contains the link monitor state history, tracking how the digital
    link state machine responds to CRC events from the analog simulation.

    Schema:
    {
        "samples": [
            {
                "cycle": int,
                "link_up": bool,
                "total_frames": int,
                "total_crc_fails": int,
                "consec_fails": int,
                "consec_passes": int
            },
            ...
        ]
    }

    The link monitor implements a hysteresis-based state machine:
    - link_up starts True after reset
    - Transitions to False after N consecutive failures
    - Transitions back to True after M consecutive passes
    """
    link_state_payload = {
        "samples": [asdict(s) for s in link_states],
    }
    link_state_path = out_path / "link_state.json"
    link_state_path.write_text(
        json.dumps(link_state_payload, indent=2) + "\n",
        encoding="utf-8",
    )
