# ThermalRes

Mixed-domain co-simulation framework for photonic resonator thermal control with digital link monitoring.

## Overview

ThermalRes simulates a **silicon photonics transceiver** where thermal management is critical for maintaining optical link integrity:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SILICON PHOTONICS CHIP                               │
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │   WORKLOAD   │───▶│   THERMAL    │───▶│  RESONATOR   │                   │
│  │  (CPU heat)  │    │   MODEL      │    │ (wavelength) │                   │
│  └──────────────┘    │              │    │              │                   │
│                      │  dT/dt =     │    │  λ = λ₀ +    │                   │
│  ┌──────────────┐    │  (P·R - ΔT)  │    │  α·(T-T_amb) │                   │
│  │   HEATER     │───▶│    / τ       │    │              │                   │
│  │ (controller) │    └──────────────┘    └──────┬───────┘                   │
│  └──────────────┘           ▲                   │                           │
│        ▲                    │                   │ detuning                  │
│        │              heat sink                 ▼                           │
│        │              (to ambient)      ┌──────────────┐                    │
│        │                                │  IMPAIRMENT  │                    │
│        │                                │  |detune| →  │                    │
│        │                                │  CRC fail %  │                    │
│        │                                └──────┬───────┘                    │
│        │                                       │ CRC events                 │
│        │                                       ▼                            │
│  ┌─────┴────────┐                      ┌──────────────┐                     │
│  │ CONTROLLER   │◀─────── feedback ────│ LINK MONITOR │ ◀── RTL validates   │
│  │ (PID/bang)   │                      │ (RTL/Python) │     this component  │
│  └──────────────┘                      │ consec_fails │                     │
│                                        │ → link_up    │                     │
│                                        └──────────────┘                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### System Behavior

- **Temperature** affects resonator wavelength via the thermo-optic effect
- **Wavelength detuning** causes link impairments (CRC failures on received data)
- A **digital link monitor** tracks connection health via hysteresis state machine
- **PID controller** adjusts heater to maintain resonance alignment

The framework supports both Python-only simulation and RTL validation against Verilator/cocotb.

## Features

- **Plant Models**: Thermal RC network, photonic resonator, link impairment probability
- **Controllers**: PID (incremental with anti-windup) and bang-bang feedback control
- **Link Monitoring**: Hysteresis state machine with configurable thresholds
- **RTL Validation**: Optional equivalence checking against SystemVerilog via Verilator
- **Deterministic**: Seeded simulation for reproducible results
- **Chunked Execution**: Efficient batched time advancement with configurable chunk size
- **Structured Artifacts**: JSON outputs for analysis and regression testing
- **Visualization**: Optional plotting of simulation results (requires matplotlib)

---

## Installation

### Requirements
- Python **3.11 or newer**
- `pip` (or equivalent package manager)
- **Optional**: Verilator + cocotb for RTL validation
- **Optional**: matplotlib for visualization (`pip install thermalres[plot]`)

### Install (Editable Mode)

```bash
python -m pip install -e ".[dev]"
```

This installs:
- The `thermalres` package
- The `thermalres` CLI command
- Development dependencies (pytest)

### Verify Installation

```bash
thermalres --help
```

---

## Quick Start

### Basic Simulation

```bash
# Run a simple simulation
thermalres --name demo --cycles 100

# Output: artifacts/runs/<timestamp>_demo/metrics.json
```

### With Link Monitoring

```bash
# Enable link state tracking
thermalres --name demo --cycles 100 --with-link-monitor

# Output includes: link_state.json
```

### With RTL Validation (requires Verilator)

```bash
# Validate Python model against RTL
thermalres --name demo --cycles 100 --with-link-monitor --validate-rtl
```

### Run Demo Script

```bash
# Pulsed AI/ML batch workload with closed-loop control (recommended)
python sim/demo.py --pulsed --cycles 300 --plot --verbose

# Step workload (constant after warmup)
python sim/demo.py --cycles 300 --plot --verbose

# Open-loop comparison (no controller - shows need for thermal control)
python sim/demo.py --pulsed --open-loop --cycles 300 --plot

# RTL validation (requires Verilator)
python sim/demo.py --validate-rtl --verbose

# Custom pulse timing (60-cycle period, 40% active)
python sim/demo.py --pulsed --pulse-period 60 --pulse-duty 0.4 --plot
```

---

## Architecture

```
CLI (thermalres)
 └── SimConfig
      └── CoSimKernel (time authority)
           ├── PlantRunner
           │    ├── step_thermal()     → ThermalState
           │    ├── eval_resonator()   → detune_nm, locked
           │    └── eval_impairment()  → crc_fail_prob
           │
           ├── Controller (optional)
           │    ├── PIDController      → heater_duty
           │    └── BangBangController → heater_duty
           │
           ├── EventSampler
           │    └── Bernoulli sampling → CrcEvent
           │
           └── LinkRunner (optional)
                ├── LinkMonitorRef (Python)
                └── RTL validation (Verilator)
           │
           v
      RunResult → Artifacts
           ├── metrics.json
           ├── timeseries.json
           ├── events.jsonl
           └── link_state.json
```

### Components

| Component | Responsibility |
|-----------|---------------|
| **CoSimKernel** | Time authority, orchestrates simulation loop |
| **PlantRunner** | Evaluates thermal → resonator → impairment chain |
| **Controller** | Computes heater_duty from plant feedback (optional) |
| **EventSampler** | Realizes CRC events from probabilities (Bernoulli) |
| **LinkRunner** | Tracks link up/down state from CRC events (optional) |

### Data Flow

1. **Kernel** advances time in chunks (configurable size)
2. **Plant models** compute temperature, detuning, CRC failure probability
3. **EventSampler** realizes CRC events via seeded Bernoulli sampling
4. **LinkRunner** updates link state based on consecutive failures/passes
5. **Artifacts** written to disk at end of run

---

## Output Artifacts

Each run produces a directory under `artifacts/runs/<timestamp>_<name>/`:

```
artifacts/runs/20240101_120000_demo/
├── metrics.json      # Run metadata (cycles, timing, scenario name)
├── timeseries.json   # Plant state per chunk (temp, detune, CRC prob)
├── events.jsonl      # CRC events per cycle (streaming JSONL format)
├── link_state.json   # Link monitor state (if --with-link-monitor)
└── plot.png          # Visualization (if --plot, requires matplotlib)
```

### Visualization (plot.png)

When `--plot` is enabled, a 4-panel figure is generated showing the simulation dynamics:

1. **Temperature** (top panel) - Shows thermal response over time. When workload increases, temperature rises due to heat dissipation through the RC thermal network.

2. **Detuning & CRC Probability** (second panel) - Dual-axis plot showing:
   - *Detuning (nm)*: How far the resonator wavelength has shifted from target due to temperature change (thermo-optic effect)
   - *CRC Fail Probability*: The resulting link impairment - higher detuning means worse signal quality and more CRC failures

3. **Heater Duty & Workload** (third panel) - Control inputs showing:
   - *Heater Duty*: Thermal compensation (0-1 scale)
   - *Workload Fraction*: External heat load representing chip activity

4. **Link State** (bottom panel, if link monitor enabled) - Digital state machine output:
   - *Green shaded region*: Link is UP (healthy)
   - *White region*: Link is DOWN (degraded)
   - *Red/blue lines*: Consecutive failure/pass counters that drive state transitions

This visualization makes it easy to trace cause and effect: workload change → temperature rise → detuning → CRC failures → link state transition.

### Schema Examples

**metrics.json:**
```json
{
  "total_cycles": 100,
  "total_chunks": 10,
  "scenario_name": "demo",
  "start_time": "2024-01-01T12:00:00Z",
  "finish_time": "2024-01-01T12:00:01Z"
}
```

**link_state.json:**
```json
[
  {"cycle": 0, "link_up": true, "consec_fails": 0, "consec_passes": 1},
  {"cycle": 1, "link_up": true, "consec_fails": 0, "consec_passes": 2}
]
```

---

## CLI Reference

```
thermalres [OPTIONS]

Options:
  --name NAME           Scenario name for artifacts (default: "default")
  --cycles N            Total simulation cycles (default: 100)
  --chunk-cycles N      Cycles per chunk (default: 10)
  --seed N              Random seed for determinism (default: 0)
  --out-dir PATH        Output directory override

Link Monitor Options:
  --with-link-monitor   Enable link state tracking
  --validate-rtl        Validate against RTL (requires Verilator)
  --fails-to-down N     Consecutive fails to trigger link down (default: 4)
  --passes-to-up N      Consecutive passes to trigger link up (default: 8)
```

---

## Testing

```bash
# Run all tests (108 tests)
pytest tests/ -v

# Unit tests only
pytest tests/unit/ -v

# System integration tests
pytest tests/system/ -v

# RTL equivalence tests (requires Verilator)
pytest tests/rtl/ -v
```

---

## Physics Model

### Thermal Dynamics

The thermal model is a first-order RC network with passive cooling to ambient:

```
dT/dt = (P_in × R_th - ΔT) / τ

where:
  T      = current temperature (°C)
  ΔT     = T - T_ambient
  P_in   = heater_power + workload_power (W)
  R_th   = thermal resistance to ambient (°C/W)
  τ      = R_th × C_th = thermal time constant (s)
  C_th   = thermal capacitance (J/°C)
```

At steady state (dT/dt = 0):
```
T_eq = T_ambient + P_in × R_th
```

### Heat-Only Control

Real silicon photonics systems **cannot actively cool** individual resonators - they can only add heat. The control strategy is:

1. **Design cold**: The system is designed so the resonator runs *below* target wavelength at ambient temperature
2. **Heater bias**: The heater provides a thermal "bias" to bring the resonator up to target alignment
3. **Disturbance rejection**: When workload increases (adding heat), the controller *reduces* heater duty
4. **Passive cooling**: Natural heat dissipation to ambient handles excess thermal load

This means the controller always works within `0 ≤ heater_duty ≤ 1` - it can only reduce heating, not actively cool.

### Thermo-Optic Effect

Silicon's refractive index changes with temperature, shifting the resonator wavelength:

```
λ_res = λ₀ + α × (T - T_ambient)

where:
  λ₀  = nominal resonance at T_ambient (nm)
  α   = thermo-optic coefficient (~0.01 nm/°C for Si)
```

### CRC Failure Probability

When the resonator is detuned from the target laser wavelength, optical coupling degrades and bit errors occur in received data. CRC (Cyclic Redundancy Check) detects these corrupted frames:

```
P_fail = sigmoid(|detune_nm| - threshold)
```

- Near resonance: P_fail ≈ 0 (clean signal)
- Far from resonance: P_fail ≈ 1 (corrupted frames)

### Link Monitor State Machine

The digital link monitor uses hysteresis to prevent oscillation:

- **4 consecutive CRC failures** → Link goes DOWN
- **8 consecutive CRC passes** → Link goes UP

This asymmetry means the link is "sticky" - once down, it requires more evidence of recovery before coming back up.

---

## Design Decisions

### Why Chunked Time?

Chunks provide explicit synchronization points between analog and digital domains:
- Efficient batched computation
- Clean state recording boundaries
- Flexible fidelity vs. performance trade-off
- Foundation for future multi-rate simulation

### Why Determinism?

All randomness flows through seeded RNGs. Same configuration + seed = identical results.
This enables:
- Reproducible debugging
- Regression testing
- Controlled experiments

### Python vs RTL: What Runs Where

The simulation divides work between Python and RTL based on what each does best:

**Python (always runs):**
- **Plant models** (thermal, resonator, impairment) - Continuous-time physics modeled with floating-point math. These represent the analog world and would be impractical in synthesizable RTL.
- **Co-simulation kernel** - Orchestrates time advancement, event sampling, and artifact generation. Pure coordination logic.
- **Controllers** (PID, bang-bang) - Feedback algorithms that could be RTL but benefit from rapid prototyping in Python.

**RTL (optional validation):**
- **Link monitor** (`link_monitor.sv`) - Digital state machine tracking CRC failures. This is the component that would actually be synthesized to silicon, so RTL equivalence matters.

**Why this split?**
- **Fast iteration**: Python runs in milliseconds; RTL compilation takes seconds to minutes
- **Physics fidelity**: Plant models need floating-point precision that fixed-point RTL can't match
- **Verification where it matters**: The link monitor is the only component destined for hardware, so that's where RTL validation adds value

### RTL Validation Strategy

The Python reference model (`LinkMonitorRef`) runs during simulation for speed. RTL validation is an optional post-run check:
1. Replay the same CRC event sequence through Verilator/cocotb
2. Sample RTL outputs at each cycle
3. Compare Python samples against RTL outputs bit-for-bit
4. Report any mismatches with cycle-level detail

This approach gives fast iteration (Python-only) with optional correctness verification (RTL). When developing the link monitor logic, you can iterate quickly in Python, then validate against RTL before tapeout.

### Link Monitor Hysteresis

The link monitor uses asymmetric thresholds (default: 4 fails to down, 8 passes to up).
This "stickiness" prevents rapid state oscillation on marginal links - once down,
the link requires more evidence of recovery before coming back up.

---

## Project Structure

```
thermalres/
├── cli.py              # Command-line interface
├── config.py           # SimConfig and PlantConfig dataclasses
├── cosim/              # Co-simulation kernel and interfaces
│   ├── kernel.py       # CoSimKernel - time authority
│   ├── plant_runner.py # Plant model wrapper
│   ├── link_runner.py  # Link monitor wrapper
│   ├── events.py       # CRC event sampling
│   ├── interfaces.py   # Data contracts (dataclasses)
│   └── metrics.py      # Artifact writing
├── plant/              # Analog plant models
│   ├── thermal.py      # First-order RC thermal network
│   ├── resonator.py    # Thermo-optic resonator model
│   └── impairment.py   # CRC failure probability mapping
├── control/            # Feedback controllers
│   ├── interfaces.py   # Controller protocol
│   ├── pid.py          # Incremental PID with anti-windup
│   └── bang_bang.py    # Threshold-based controller
├── digital/            # Digital reference models
│   └── reference.py    # Link monitor Python implementation
├── rtl/                # RTL integration
│   └── adapter.py      # Verilator/cocotb adapter
└── scenarios/          # Input schedules
    └── open_loop.py    # Constant, step, ramp workloads

rtl/                    # SystemVerilog sources
├── link_monitor.sv     # Link monitor state machine
└── top.sv              # Simulation wrapper

sim/                    # Simulation scripts
├── demo.py             # Full feature demonstration
└── cocotb/             # Cocotb test infrastructure

tests/                  # Test suite
├── unit/               # Unit tests for each module
├── system/             # System integration tests
└── rtl/                # RTL equivalence tests
```

---

## License

MIT
