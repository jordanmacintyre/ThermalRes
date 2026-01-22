from __future__ import annotations

import json
import random
from dataclasses import asdict
from pathlib import Path

from thermalres.cosim.interfaces import CrcEvent


class EventSampler:
    """
    Deterministic event sampler using seeded RNG.

    Converts probabilities into binary events (CRC failures) in a reproducible way.
    """

    def __init__(self, seed: int):
        """
        Initialize event sampler with seed.

        Args:
            seed: Random seed for deterministic sampling
        """
        self._rng = random.Random(seed)

    def sample_crc_event(
        self,
        cycle: int,
        chunk_idx: int,
        crc_fail_prob: float,
        locked: bool,
    ) -> CrcEvent:
        """
        Sample a CRC event from probability.

        If unlocked, force failure (consistent with impairment model).
        Otherwise, sample Bernoulli(crc_fail_prob).

        Args:
            cycle: Current cycle number
            chunk_idx: Current chunk index
            crc_fail_prob: Probability of CRC failure [0, 1]
            locked: Whether system is locked

        Returns:
            CrcEvent with realized failure status
        """
        if not locked:
            # Unlocked always fails
            crc_fail = True
        else:
            # Sample from Bernoulli distribution
            crc_fail = self._rng.random() < crc_fail_prob

        return CrcEvent(
            cycle=cycle,
            chunk_idx=chunk_idx,
            crc_fail=crc_fail,
            crc_fail_prob=crc_fail_prob,
        )


def write_events_jsonl(out_path: Path, events: list[CrcEvent]) -> None:
    """
    Write events to JSONL format (one JSON object per line).

    JSONL is efficient for streaming and appending.

    Args:
        out_path: Output directory
        events: List of CRC events to write
    """
    if len(events) == 0:
        return

    out_path = Path(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    events_file = out_path.joinpath("events.jsonl")
    with events_file.open("w", encoding="utf-8") as f:
        for event in events:
            json.dump(asdict(event), f, sort_keys=True)
            f.write("\n")
