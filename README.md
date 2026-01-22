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

**Milestone 3 — Kernel-Plant Integration (Current)**

The kernel now drives the plant models as the authoritative timebase:
- **PlantRunner**: Clean glue layer between kernel and plant models
- **Open-loop scenarios**: Deterministic input schedules (constant, step, ramp)
- **Time-series artifacts**: Per-chunk plant state recorded to `timeseries.json`
- **System-level tests**: End-to-end kernel+plant integration validation
- **Deterministic**: Identical configs produce identical results

No feedback control yet—inputs are scheduled, not computed from plant state.

**Milestone 2 — Plant Models (Complete)**

Deterministic plant models:
- **Thermal model**: First-order RC thermal network with heater and workload inputs
- **Resonator model**: Temperature-dependent photonic resonator with lock detection
- **Impairment model**: Detuning-based CRC failure probability mapping
- **Plant chain**: Integrated evaluation function connecting all models
- **Comprehensive unit tests**: 39 tests validating correctness and monotonic behavior

**Milestone 1 — Execution Skeleton and Contracts (Complete)**

The foundation provides:
- An installable Python package
- A stable command-line interface
- A deterministic execution kernel
- Explicit time chunking
- Structured JSON run artifacts

There are **no closed-loop controllers or RTL integration yet**.

---

## High-Level Architecture

At a high level, the project currently looks like this:

```
CLI
 |-- SimConfig (run definition)
       |-- CoSimKernel (time advancement)
             |-- ChunkSummary[]
             |-- RunMetrics
                   |
                   v
              metrics.json (artifact)

Plant Models (Milestone 2):
  ThermalState + PlantInputs
       |
       v
  step_thermal() → ThermalState (updated)
       |
       v
  eval_resonator() → ResonatorOutputs (resonance, detune, locked)
       |
       v
  eval_impairment() → ImpairmentOutputs (crc_fail_prob)
       |
       v
  PlantOutputs (combined state)
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

The test suite validates:

**Milestone 1 Tests:**
- Chunking behavior
- Metric consistency
- Artifact creation
- Schema shape

**Milestone 2 Tests (39 unit tests):**
- Thermal model: convergence to ambient, steady-state accuracy, input clamping
- Resonator model: thermo-optic shift, lock/unlock transitions, boundary conditions
- Impairment model: monotonic probability curves, symmetry, clamping

**Milestone 3 Tests (4 system tests):**
- Open-loop constant heater: monotonic temperature increase
- Open-loop step workload: transient response validation
- Artifact generation: timeseries.json structure and content
- Determinism: identical configs produce identical results

Run all tests:
```bash
pytest
```

Run only unit tests:
```bash
pytest tests/unit/
```

Run only system tests:
```bash
pytest tests/system/
```

Tests focus on **contracts and correctness**, not physical fidelity.
This ensures future refactors do not break downstream consumers.

---

## Milestones

### Milestone 1 (complete)
- Package structure and installation
- CLI entrypoint
- Deterministic, chunk-based execution
- Stable configuration and metric contracts
- JSON run artifacts

### Milestone 2 (complete)
- **Thermal model** ([thermalres/plant/thermal.py](thermalres/plant/thermal.py)):
  - First-order RC network: `dT/dt = (P*R - ΔT) / (R*C)`
  - Euler integration with configurable timestep
  - Heater and workload power inputs
- **Resonator model** ([thermalres/plant/resonator.py](thermalres/plant/resonator.py)):
  - Thermo-optic wavelength shift: `λ = λ₀ + α*(T - T_amb)`
  - Lock detection within tolerance window
  - Detuning calculation (signed)
- **Impairment model** ([thermalres/plant/impairment.py](thermalres/plant/impairment.py)):
  - Smooth CRC failure probability vs. detuning
  - Cubic smoothstep mapping centered at 50% point
  - Unlocked state forces 100% failure
- **Plant chain helper** ([thermalres/plant/__init__.py](thermalres/plant/__init__.py)):
  - `eval_plant_chain()` integrates all three models
  - Takes `ThermalState` + `PlantInputs`
  - Returns updated `ThermalState` + `PlantOutputs`
- **Configuration defaults** ([thermalres/config.py](thermalres/config.py)):
  - `PlantConfig` dataclass with reasonable defaults
  - Ambient temp 25°C, R_th=10°C/W, C_th=0.1 J/°C
  - λ₀=1550nm, α=0.1nm/°C, lock window ±0.5nm
- **Comprehensive unit tests** ([tests/unit/](tests/unit/)):
  - 11 thermal tests: convergence, steady-state, immutability
  - 14 resonator tests: thermo-optic shift, lock boundaries
  - 14 impairment tests: monotonicity, symmetry, smoothness

### Milestone 3 (current)
- **PlantRunner** ([thermalres/cosim/plant_runner.py](thermalres/cosim/plant_runner.py)):
  - Encapsulates plant state evolution
  - Clean glue layer between kernel and plant models
  - Maintains thermal state across simulation
- **Open-loop scenarios** ([thermalres/scenarios/open_loop.py](thermalres/scenarios/open_loop.py)):
  - `constant_heater()`: Fixed heater/workload schedule
  - `step_workload()`: Step change at specified cycle
  - `ramp_workload()`: Linear ramp over time
  - `heater_off_workload_on()`: Workload-only operation
- **Kernel integration** ([thermalres/cosim/kernel.py](thermalres/cosim/kernel.py)):
  - Optional `plant_runner` and `schedule` parameters
  - Steps plant models at each chunk boundary
  - Kernel remains time authority
- **Time-series recording** ([thermalres/cosim/interfaces.py](thermalres/cosim/interfaces.py)):
  - `TimeSeriesSample` captures plant state + inputs per chunk
  - Written to `timeseries.json` artifact
- **System-level tests** ([tests/system/test_open_loop.py](tests/system/test_open_loop.py)):
  - End-to-end kernel+plant validation
  - Monotonic behavior checks
  - Artifact structure validation
  - Determinism verification

### Milestone 4 (planned)
_Closed-loop control with PID or bang-bang controller._

---

## License

MIT