# ThermalRes

Mixed-domain co-simulation framework for photonic resonator thermal control with digital link monitoring.

## Overview

ThermalRes simulates a **silicon photonics transceiver** where thermal management is critical for maintaining optical link integrity. The system models:

- **Thermal physics**: Heat flow through an RC thermal network
- **Photonic behavior**: Resonator wavelength shift due to temperature (thermo-optic effect)
- **Link impairment**: CRC failure probability as a function of detuning
- **Digital monitoring**: Hysteresis-based link state machine
- **Feedback control**: PID controller for thermal stabilization

### System Architecture

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
│        │                                       │ P(CRC fail)                │
│        │                                       ▼                            │
│  ┌─────┴────────┐                      ┌──────────────┐                     │
│  │ CONTROLLER   │◀─────── feedback ────│ LINK MONITOR │ ◀── RTL (cocotb)    │
│  │ (PID)        │                      │  (Python or  │     drives this     │
│  └──────────────┘                      │    RTL)      │                     │
│                                        │ consec_fails │                     │
│                                        │ → link_up    │                     │
│                                        └──────────────┘                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Signal Flow

1. **Workload** (external heat source, e.g., CPU activity) adds thermal power
2. **Thermal model** computes temperature rise through RC network dynamics
3. **Resonator** wavelength shifts due to thermo-optic effect (α ≈ 0.01 nm/°C)
4. **Impairment model** maps detuning to CRC failure probability (sigmoid)
5. **LFSR** in RTL generates Bernoulli-sampled CRC fail events from probability
6. **Link monitor** tracks consecutive failures/passes with hysteresis state machine
7. **Controller** adjusts heater duty to minimize detuning (closed-loop mode)

---

## Two Simulation Modes

ThermalRes supports two simulation backends:

### 1. RTL Co-Simulation (Default)

**Requires**: Verilator + cocotb (available via conda)

cocotb drives the simulation loop, calling Python plant models on each RTL clock cycle:

```
┌─────────────────────────────────────────────────────────────────┐
│                     cocotb Test (Python)                        │
│                                                                 │
│  for each cycle:                                                │
│    1. Python: step plant model → crc_fail_prob                  │
│    2. Python → RTL: write crc_fail_prob (Q0.16 fixed-point)     │
│    3. RTL: LFSR generates crc_fail event                        │
│    4. RTL: link_monitor updates state (hysteresis FSM)          │
│    5. cocotb: wait for rising clock edge                        │
│    6. RTL → Python: read link_up, consec_fails, etc.            │
│    7. Python: record samples for artifacts                      │
└─────────────────────────────────────────────────────────────────┘
```

The RTL module (`cosim_top.sv`) contains:
- **LFSR**: 32-bit linear feedback shift register for pseudorandom event generation
- **Bernoulli sampler**: Compares LFSR output against `crc_fail_prob` threshold
- **Link monitor**: Hysteresis state machine (configurable thresholds)

### 2. Python-Only Mode (`--no-rtl`)

**No external dependencies** beyond Python packages.

Useful for:
- Quick iteration without Verilator compilation
- Development on systems without RTL tooling
- Debugging plant models and controllers

The Python reference model (`LinkMonitorRef`) implements identical logic to the RTL.

---

## Installation

### Requirements

- Python **3.11+**
- **For RTL co-simulation**: Verilator + cocotb

### Recommended: Conda Environment

```bash
# Create environment with RTL tools
conda create -n photonics python=3.11 verilator cocotb -c conda-forge
conda activate photonics

# Install ThermalRes
pip install -e ".[dev,plot]"
```

### Minimal (Python-only mode)

```bash
pip install -e ".[dev,plot]"
```

### Verify Installation

```bash
# Check CLI
thermalres --help

# Check Verilator (for RTL mode)
verilator --version
```

---

## Quick Start

### Run Demo (Recommended)

```bash
# RTL co-simulation with closed-loop PID control (default)
python sim/demo.py --cycles 300

# Python-only mode (no Verilator needed)
python sim/demo.py --no-rtl --cycles 300

# Pulsed workload (simulates AI/ML batch jobs)
python sim/demo.py --pulsed --cycles 300

# Open-loop (no controller - shows need for thermal control)
python sim/demo.py --no-rtl --open-loop --cycles 300

# Skip plot generation
python sim/demo.py --no-rtl --cycles 300 --no-plot
```

### Run CLI

```bash
# Basic simulation
thermalres --name demo --cycles 100

# With link monitoring
thermalres --name demo --cycles 100 --with-link-monitor

# Python-only mode
thermalres --name demo --cycles 100 --with-link-monitor --no-rtl
```

### Run cocotb Tests Directly

```bash
cd sim/cocotb

# Run specific test
make TESTCASE=test_closed_loop_simulation

# Run all tests
make test-all

# Dump waveforms (creates sim_build/cosim_top.fst)
DUMP_WAVES=1 make TESTCASE=test_closed_loop_simulation
make waves  # Opens GTKWave
```

---

## Output Artifacts

Each run produces a timestamped directory under `artifacts/runs/`:

```
artifacts/runs/20260101_120000_demo/
├── metrics.json      # Run metadata (cycles, timing, scenario name)
├── chunks.json       # Per-chunk summaries
├── timeseries.json   # Plant state per cycle (temp, detune, CRC prob)
├── events.json       # CRC failure events
├── link_state.json   # Link monitor state history
└── plot.png          # 4-panel visualization (default)
```

### Plot Visualization

Plots are **generated by default** (use `--no-plot` to skip). The 4-panel figure shows:

1. **Temperature** - Thermal response with optional lock window reference
2. **Detuning & CRC Probability** - Resonator alignment and resulting impairment
3. **Heater Duty & Workload** - Control inputs (green) and disturbance (magenta)
4. **Link State** - UP/DOWN state with consecutive failure/pass counters

The plot makes cause-and-effect visible: workload change → temperature rise → detuning → CRC failures → link state transition.

---

## Physics Model

### Thermal Dynamics

First-order RC network with passive cooling to ambient:

```
dT/dt = (P_in × R_th - ΔT) / τ

where:
  T      = current temperature (°C)
  ΔT     = T - T_ambient
  P_in   = heater_power + workload_power (W)
  R_th   = thermal resistance to ambient (°C/W)
  τ      = R_th × C_th = thermal time constant (s)
```

At steady state: `T_eq = T_ambient + P_in × R_th`

### Thermo-Optic Effect

Silicon's refractive index changes with temperature:

```
λ_res = λ₀ + α × (T - T_ambient)

where:
  λ₀  = nominal resonance at ambient (nm)
  α   = thermo-optic coefficient (~0.01 nm/°C for silicon)
```

### CRC Failure Probability

Sigmoid function mapping detuning magnitude to failure probability:

```
P_fail = sigmoid((|detune| - threshold) / steepness)

- Near resonance: P_fail ≈ 0 (clean signal)
- Far from resonance: P_fail ≈ 1 (corrupted frames)
```

### Link Monitor State Machine

Hysteresis-based state machine prevents oscillation:

```
         4 consecutive fails
    ┌────────────────────────────┐
    │                            ▼
[LINK UP]                   [LINK DOWN]
    ▲                            │
    └────────────────────────────┘
         8 consecutive passes
```

The asymmetry (4 down, 8 up) makes the link "sticky" - once down, it requires more evidence of recovery before coming back up.

---

## Control System

### Heat-Only Constraint

Real silicon photonics systems **cannot actively cool** individual resonators. The control strategy:

1. **Design cold**: Resonator runs below target wavelength at ambient temperature
2. **Heater bias**: Controller maintains thermal "bias" to reach target alignment
3. **Disturbance rejection**: When workload increases, controller reduces heater duty
4. **Passive cooling**: Natural heat dissipation handles excess thermal load

The heater duty is always bounded: `0 ≤ heater_duty ≤ 1`

### PID Controller

Incremental PID with anti-windup:

```python
error = detune_target_nm - detune_nm  # Usually target = 0 (on resonance)
P = Kp × error
I = I_prev + Ki × error × dt  # With anti-windup clamping
D = Kd × (error - error_prev) / dt

heater_duty = clamp(unlock_boost + P + I + D, 0, 1)
```

The `unlock_boost` provides a bias point (typically 0.5) around which the controller operates.

---

## CLI Reference

### thermalres command

```
thermalres [OPTIONS]

Core Options:
  --name NAME           Scenario name for artifacts (default: "default")
  --cycles N            Total simulation cycles (default: 100)
  --cycle-chunks N      Cycles per chunk (default: 10)
  --seed N              Random seed for determinism (default: 0)
  --out-dir PATH        Output directory override

Link Monitor Options:
  --with-link-monitor   Enable link state tracking
  --no-rtl              Use Python-only simulation (no Verilator)
  --fails-to-down N     Consecutive fails to trigger link down (default: 4)
  --passes-to-up N      Consecutive passes to trigger link up (default: 8)
```

### sim/demo.py options

```
python sim/demo.py [OPTIONS]

Simulation:
  --cycles N            Total cycles (default: 300)
  --seed N              Random seed (default: 42)
  --no-rtl              Python-only mode

Control:
  --open-loop           Disable controller (heater_duty = 0)

Workload:
  --warmup-cycles N     Warmup phase duration (default: 50)
  --warmup-workload F   Idle workload fraction (default: 0.3)
  --disturbance-workload F  Active workload fraction (default: 0.7)
  --pulsed              Enable pulsed workload pattern
  --pulse-period N      Pulse period in cycles (default: 40)
  --pulse-duty F        Pulse duty cycle (default: 0.5)

Output:
  --no-plot             Skip plot generation
  --show-plot           Display plot interactively
  --verbose             Print detailed progress
```

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Unit tests (plant models, controllers)
pytest tests/unit/ -v

# System integration tests (full simulation scenarios)
pytest tests/system/ -v

# RTL equivalence tests (requires Verilator)
pytest tests/rtl/ -v
```

---

## Project Structure

```
ThermalRes/
├── thermalres/              # Python package
│   ├── cli.py               # CLI entry point
│   ├── config.py            # SimConfig, PlantConfig dataclasses
│   ├── cosim/               # Co-simulation framework
│   │   ├── kernel.py        # CoSimKernel (time authority)
│   │   ├── plant_runner.py  # Plant model orchestration
│   │   ├── link_runner.py   # Link monitor wrapper
│   │   ├── events.py        # CRC event sampling
│   │   ├── interfaces.py    # Data contracts
│   │   ├── metrics.py       # Artifact writing
│   │   └── plotting.py      # Visualization
│   ├── plant/               # Analog plant models
│   │   ├── thermal.py       # RC thermal network
│   │   ├── resonator.py     # Thermo-optic model
│   │   └── impairment.py    # CRC probability mapping
│   ├── control/             # Feedback controllers
│   │   ├── interfaces.py    # Controller protocol
│   │   ├── pid.py           # PID with anti-windup
│   │   └── bang_bang.py     # Threshold controller
│   ├── digital/             # Digital reference models
│   │   └── reference.py     # Python LinkMonitorRef
│   └── rtl/                 # RTL adapter utilities
│       └── adapter.py       # Verilator/cocotb interface
│
├── rtl/                     # SystemVerilog sources
│   ├── cosim_top.sv         # Top-level for cocotb (LFSR + link_monitor)
│   ├── link_monitor.sv      # Hysteresis state machine
│   └── top.sv               # Simulation wrapper
│
├── sim/                     # Simulation infrastructure
│   ├── demo.py              # Full feature demonstration
│   └── cocotb/              # cocotb test environment
│       ├── Makefile         # cocotb build rules
│       ├── plant_adapter.py # PlantAdapter (bridges Python ↔ RTL)
│       ├── test_cosim.py    # Co-simulation tests
│       └── test_link_monitor.py  # Link monitor unit tests
│
├── tests/                   # pytest test suite
│   ├── unit/                # Unit tests
│   ├── system/              # Integration tests
│   └── rtl/                 # RTL equivalence tests
│
└── artifacts/               # Output directory (gitignored)
    └── runs/                # Timestamped run directories
```

---

## Design Decisions

### Why cocotb Drives the Loop?

cocotb (RTL clock) drives the simulation because:
1. **RTL is the source of truth** for the link monitor - it's what gets synthesized
2. **Lock-step execution** ensures Python and RTL see identical state each cycle
3. **No clock domain complexity** - single clock simplifies verification

### Why LFSR Instead of Python Random?

The LFSR (Linear Feedback Shift Register) in RTL:
1. **Deterministic** - same seed produces identical event sequences
2. **Synthesizable** - could be included in actual hardware
3. **Bit-exact** - no floating-point differences between Python and RTL

### Why Heat-Only Control?

Silicon photonics resonators:
1. **Cannot actively cool** - no practical way to remove heat faster than passive dissipation
2. **Run cold by design** - target wavelength is above ambient resonance
3. **Use heater as bias** - controller works by reducing heating, not adding cooling

### Why Hysteresis in Link Monitor?

Asymmetric thresholds (4 fails down, 8 passes up):
1. **Prevents oscillation** on marginal links
2. **Models real hardware** behavior
3. **"Sticky down"** - requires strong evidence of recovery

---

## License

MIT
