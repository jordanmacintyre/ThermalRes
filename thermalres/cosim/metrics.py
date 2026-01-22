from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .interfaces import ChunkSummary, RunMetrics


def write_run_artifacts(
        *, 
        out_path: Path, 
        metrics: RunMetrics, 
        chunks: list[ChunkSummary]
    ) -> None:
    
    out_path = Path(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    payload = {
        "run": asdict(metrics),
        "chunks": [asdict(c) for c in chunks],
    }

    metrics_path = out_path.joinpath("metrics.json")
    metrics_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
