from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from thermalres.config import SimConfig
from thermalres.cosim.kernel import CoSimKernel
from thermalres.cosim.metrics import write_run_artifacts


def test_smoke_kernel_and_artifacts() -> None:
    cfg = SimConfig.from_args(
        name="smoke", 
        cycles=10, 
        cycle_chunks=4, 
        seed=42, 
        out_dir=None
    )

    kernel = CoSimKernel(cfg)
    metrics, chunks = kernel.run()

    # cycles=10 with chunk=4 -> [0-4), [4-8), [8-10) => 3 chunks
    assert metrics.total_cycles == 10
    assert metrics.total_chunks == 3
    assert len(chunks) == 3
    assert chunks[0].start_cycle == 0 and chunks[0].end_cycle == 4
    assert chunks[1].start_cycle == 4 and chunks[1].end_cycle == 8
    assert chunks[2].start_cycle == 8 and chunks[2].end_cycle == 10

    with TemporaryDirectory() as td:
        out_dir = Path(td).joinpath("run")
        write_run_artifacts(out_path=out_dir, metrics=metrics, chunks=chunks)

        p = out_dir.joinpath("metrics.json")
        assert p.exists()

        data = json.loads(p.read_text(encoding="utf-8"))
        assert "run" in data
        assert "chunks" in data

        run = data["run"]
        assert set(run.keys()) >= {
            "total_cycles",
            "total_chunks",
            "start_time",
            "finish_time",
            "scenario_name",
        }
        assert run["total_cycles"] == 10
        assert run["total_chunks"] == 3
        assert run["scenario_name"] == "smoke"

        assert isinstance(data["chunks"], list)
        assert len(data["chunks"]) == 3
        assert set(data["chunks"][0].keys()) == {
            "chunk_idx", 
            "start_cycle", 
            "end_cycle"
        }
