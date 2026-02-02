"""
ThermalRes: Mixed-domain co-simulation framework for photonic resonator thermal control.

Features:
- Plant models: thermal RC network, photonic resonator, link impairment
- Controllers: PID and bang-bang feedback control
- Link monitoring: hysteresis state machine with RTL validation
- Deterministic simulation with seeded RNGs
- JSON/JSONL run artifacts
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
