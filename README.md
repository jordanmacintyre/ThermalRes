# ThermalRes

ThermalRes is an incremental project for building a mixed-domain co-simulation framework.
The project is developed milestone by milestone, with each stage intentionally small and
self-contained. Early milestones prioritize **architecture, contracts, and determinism**
over physical fidelity or performance.

---

## Design Goals

From the outset, ThermalRes is designed around the following principles:

- **Incremental construction**: each milestone is runnable end-to-end
- **Stable contracts first**: data shapes and execution flow are locked down early
- **Explicit time management**: simulated time is structured, not implicit
- **Determinism by default**: reproducibility is a first-class concern
- **Artifacts over side effects**: runs produce structured outputs

These goals shape every design decision in Milestone 1.

---

## Current Status

**Milestone 1 — Execution Skeleton and Contracts**

At this stage, ThermalRes provides:
- An installable Python package
- A stable command-line interface
- A deterministic execution kernel
- Explicit time chunking
- Structured JSON run artifacts

There are **no plant models, no physics, no RTL, and no co-simulation backends yet**.
This milestone exists to establish a foundation that future complexity can attach to
without refactoring the core.

---

## High-Level Architecture

At a high level, the project currently looks like this:

```
CLI
 |-- SimConfig (run definition)
       |-- CoSimKernel (time advancement)
             |-- ChunkSummary[]
             |-- RunMetrics
                   v
              metrics.json (artifact)
```

Each layer has a narrow, well-defined responsibility.

---

## Installation

### Requirements
- Python **3.11 or newer**
- `pip` (or equivalent Python package manager)

### Editable Install (Recommended for Development)

From the repository root:

```bash
python -m pip install -e ".[dev]"
```

This installs:
- the `thermalres` package in editable mode
- the `thermalres` CLI entrypoint
- development dependencies (currently `pytest`)

After installation, you should be able to run:

```bash
thermalres --help
```

or:

```bash
python -m thermalres --help
```

### Verifying the Installation

Run a minimal smoke scenario:

```bash
thermalres --name smoke --cycles 10 --chunk-cycles 4 --seed 0
```

This should create a run artifact under:

```
artifacts/runs/<timestamp>_smoke/metrics.json
```
---

## Execution Flow

1. **CLI Invocation**
   - Entry points:
     - `thermalres`
     - `python -m thermalres`
   - Both resolve to the same `cli.main()` function.

2. **Run Configuration**
   - CLI arguments are parsed into a `SimConfig` dataclass.
   - `SimConfig` defines *what run to execute*, not *how simulation works*.
   - Fields include:
     - scenario name
     - total cycles
     - chunk size
     - seed (for future determinism)
     - output directory override

3. **Kernel Execution**
   - `CoSimKernel` advances simulated time from `0 → N`.
   - Time advances in **chunks**, not single cycles.
   - For each chunk, a `ChunkSummary` is produced.

4. **Artifact Generation**
   - After execution completes, results are written to disk.
   - Each run produces a self-contained directory under:
     ```
     artifacts/runs/<timestamp>_<scenario>/
     ```
   - A single `metrics.json` file captures:
     - run-level metadata
     - per-chunk summaries

---

## Why Chunked Time?

Chunks are a foundational design choice.

A *chunk* is a contiguous range of cycles executed atomically by the kernel.
The kernel only synchronizes state and emits records at chunk boundaries.

Chunks exist now/before any physical models because:

- Co-simulation requires explicit synchronization points
- Different domains evolve at different natural rates
- Per-cycle synchronization is difficult to scale
- Time structure is difficult to retrofit later

Utilizing chunks enables future additions to:
- Integrate slow and fast models cleanly
- Aggregate metrics efficiently
- Synchronize software, hardware, and plant models
- Trade fidelity for performance without architectural change

---

## Data Contracts

The kernel produces two explicit data structures:

### RunMetrics
Captures run-level metadata:
- scenario name
- total cycles
- total chunks
- start and finish timestamps

### ChunkSummary
Captures per-chunk execution windows:
- chunk index
- start cycle (inclusive)
- end cycle (exclusive)

These are implemented as **dataclasses with fixed fields**.
They are intended to be:
- Immutable records
- Easy to serialize
- Stable across milestones

They represent **interfaces**, not internal implementation details.

---

## Output Artifacts

Every run produces a structured artifact:

```
artifacts/
  runs/
    <timestamp>_<scenario>/
      metrics.json
```

Artifacts are first-class outputs:
- They enable regression testing
- They allow offline analysis
- They provide a stable integration point for tooling

---

## Testing Scope

The current test suite validates:
- Chunking behavior
- Metric consistency
- Artifact creation
- Schema shape

Tests focus on **contracts**, not simulation fidelity.
This ensures future refactors do not break downstream consumers.

---

## Milestones

### Milestone 1 (current)
- Package structure and installation
- CLI entrypoint
- Deterministic, chunk-based execution
- Stable configuration and metric contracts
- JSON run artifacts

### Milestone 2 (planned)
_Additive milestone — details to be appended._

### Milestone 3 (planned)
_Additive milestone — details to be appended._

---

## License

MIT