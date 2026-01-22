from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .interfaces import ChunkSummary, CrcEvent, RunMetrics, TimeSeriesSample


def write_run_artifacts(
        *,
        out_path: Path,
        metrics: RunMetrics,
        chunks: list[ChunkSummary],
        timeseries: list[TimeSeriesSample] | None = None,
        events: list[CrcEvent] | None = None,
    ) -> None:
    """
    Write simulation artifacts to disk.

    Args:
        out_path: Output directory
        metrics: Run-level metrics
        chunks: Chunk summaries
        timeseries: Optional time-series samples (Milestone 3+)
        events: Optional CRC events (Milestone 4+)
    """
    out_path = Path(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    # Write metrics.json (Milestone 1)
    payload = {
        "run": asdict(metrics),
        "chunks": [asdict(c) for c in chunks],
    }

    metrics_path = out_path.joinpath("metrics.json")
    metrics_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Write timeseries.json (Milestone 3+)
    if timeseries is not None and len(timeseries) > 0:
        timeseries_payload = {
            "samples": [asdict(s) for s in timeseries],
        }
        timeseries_path = out_path.joinpath("timeseries.json")
        timeseries_path.write_text(
            json.dumps(timeseries_payload, indent=2) + "\n",
            encoding="utf-8"
        )

    # Write events.jsonl (Milestone 4+)
    if events is not None and len(events) > 0:
        events_path = out_path.joinpath("events.jsonl")
        with events_path.open("w", encoding="utf-8") as f:
            for event in events:
                json.dump(asdict(event), f, sort_keys=True)
                f.write("\n")
