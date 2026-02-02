"""
Link monitor runner for co-simulation.

This module provides the LinkRunner class, which wraps the link monitor
(Python reference or RTL) and integrates it with the CoSimKernel. It
processes CrcEvent objects from the EventSampler and produces
LinkStateSample outputs for recording.

The LinkRunner follows the same design pattern as PlantRunner:
- Clean separation between the kernel and the link monitor implementation
- Encapsulates state management
- Provides inspection methods for testing

Architecture:
```
    CoSimKernel
        |
        v
    EventSampler ---> CrcEvent
        |
        v
    LinkRunner
        |-- LinkMonitorRef (Python reference, always runs)
        |-- RTL validation (optional, post-run)
        |
        v
    LinkStateSample ---> link_state.json
```

Two execution modes are supported:

1. Python-only mode (default):
   - Fast execution using LinkMonitorRef
   - No external dependencies
   - Suitable for CI/CD pipelines
   - `LinkRunner(LinkMonitorConfig(use_rtl=False))`

2. RTL validation mode:
   - Python reference runs during simulation (for speed)
   - Post-run: validates against RTL using cocotb/Verilator
   - Requires `verilator` and `cocotb` packages
   - `LinkRunner(LinkMonitorConfig(use_rtl=True))`

Example usage:
    >>> from thermalres.cosim.link_runner import LinkRunner
    >>> from thermalres.cosim.interfaces import CrcEvent, LinkMonitorConfig
    >>>
    >>> # Create runner with default config
    >>> runner = LinkRunner()
    >>>
    >>> # Process some CRC events
    >>> event1 = CrcEvent(cycle=0, chunk_idx=0, crc_fail=False, crc_fail_prob=0.1)
    >>> sample1 = runner.step(event1)
    >>> print(f"Link up: {sample1.link_up}, Frames: {sample1.total_frames}")
    >>>
    >>> # Get all samples for artifact writing
    >>> samples = runner.get_samples()
"""

from __future__ import annotations

from thermalres.cosim.interfaces import (
    CrcEvent,
    LinkMonitorConfig,
    LinkStateSample,
)
from thermalres.digital.reference import (
    LinkMonitorParams,
    LinkMonitorRef,
)


class LinkRunner:
    """
    Encapsulates link monitor state evolution for co-simulation.

    This class provides clean separation between the CoSimKernel and the
    link monitor implementation. It maintains the link state across the
    simulation and provides methods for stepping, resetting, and
    inspecting the state.

    The LinkRunner always uses the Python reference model (LinkMonitorRef)
    for the primary simulation. When `use_rtl=True` is configured, it
    additionally supports post-run RTL validation to verify that the
    Python and RTL implementations produce identical results.

    Attributes:
        config: The LinkMonitorConfig controlling behavior.

    Example:
        >>> runner = LinkRunner(LinkMonitorConfig(fails_to_down=3))
        >>> # Process events from EventSampler
        >>> for event in events:
        ...     sample = runner.step(event)
        ...     if not sample.link_up:
        ...         print(f"Link went down at cycle {sample.cycle}")
    """

    def __init__(self, config: LinkMonitorConfig | None = None) -> None:
        """
        Initialize the link runner.

        Creates a new LinkRunner with the specified configuration. The
        link monitor starts in the reset state (link_up=True, all
        counters at zero).

        Args:
            config: Link monitor configuration controlling thresholds
                    and RTL validation. Uses default LinkMonitorConfig()
                    if None.
        """
        # Store configuration (use defaults if not provided)
        self.config = config or LinkMonitorConfig()

        # ─────────────────────────────────────────────────────────────
        # Initialize the Python reference model
        # This is always used for the primary simulation because:
        # 1. It's fast (no subprocess overhead)
        # 2. It's deterministic
        # 3. It doesn't require external tools
        # ─────────────────────────────────────────────────────────────
        self._ref = LinkMonitorRef(
            LinkMonitorParams(
                fails_to_down=self.config.fails_to_down,
                passes_to_up=self.config.passes_to_up,
            )
        )

        # ─────────────────────────────────────────────────────────────
        # Event and sample history for analysis and RTL validation
        # We store all events so we can replay them through RTL later
        # ─────────────────────────────────────────────────────────────
        self._events: list[CrcEvent] = []
        self._samples: list[LinkStateSample] = []

    def reset(self) -> None:
        """
        Reset the link monitor to initial state.

        Clears all accumulated events and samples, and resets the
        Python reference model to its initial state (link_up=True,
        all counters at zero).

        This should be called at the start of each simulation run
        to ensure clean state.
        """
        # Reset the Python reference model
        self._ref.reset()

        # Clear accumulated history
        self._events.clear()
        self._samples.clear()

    def step(self, event: CrcEvent) -> LinkStateSample:
        """
        Process a CRC event and update link state.

        This is the main method called by CoSimKernel on each cycle.
        It takes a CrcEvent from the EventSampler and:
        1. Stores the event for potential RTL validation
        2. Steps the Python reference model
        3. Creates and stores a LinkStateSample
        4. Returns the sample for recording

        Args:
            event: CRC event from EventSampler. The `crc_fail` field
                   indicates whether a CRC failure occurred this cycle.

        Returns:
            LinkStateSample capturing the link state after processing
            this event. Includes cycle number, link_up status, and
            all counter values.

        Example:
            >>> event = CrcEvent(cycle=5, chunk_idx=0, crc_fail=True, crc_fail_prob=0.8)
            >>> sample = runner.step(event)
            >>> print(f"After cycle 5: link_up={sample.link_up}")
        """
        # ─────────────────────────────────────────────────────────────
        # Store event for history and potential RTL validation
        # ─────────────────────────────────────────────────────────────
        self._events.append(event)

        # ─────────────────────────────────────────────────────────────
        # Step the Python reference model
        # We always treat events as valid frames (valid=True) because
        # CrcEvent only exists when there's a realized frame
        # ─────────────────────────────────────────────────────────────
        self._ref.step(
            valid=True,             # Events always represent valid frames
            crc_fail=event.crc_fail,  # Pass through the CRC failure status
        )

        # ─────────────────────────────────────────────────────────────
        # Create immutable sample from current state
        # ─────────────────────────────────────────────────────────────
        sample = self._ref.to_link_state_sample(cycle=event.cycle)

        # Store sample for history
        self._samples.append(sample)

        return sample

    def get_samples(self) -> list[LinkStateSample]:
        """
        Get all link state samples collected during the run.

        Returns a copy of the internal sample list. This is used for
        artifact writing (link_state.json) and analysis.

        Returns:
            List of LinkStateSample objects, one per step() call,
            in chronological order.
        """
        return list(self._samples)

    def get_events(self) -> list[CrcEvent]:
        """
        Get all CRC events processed during the run.

        Returns a copy of the internal event list. This is useful for
        debugging and for replaying events through RTL.

        Returns:
            List of CrcEvent objects, one per step() call,
            in chronological order.
        """
        return list(self._events)

    def get_current_state(self) -> LinkStateSample | None:
        """
        Get the most recent link state sample.

        Returns:
            The last LinkStateSample, or None if no events have been
            processed yet.
        """
        if self._samples:
            return self._samples[-1]
        return None

    def validate_against_rtl(self) -> tuple[bool, str]:
        """
        Validate Python reference against RTL simulation.

        Runs the accumulated CRC events through the RTL link_monitor
        using cocotb/Verilator and compares the outputs against the
        Python reference samples.

        This is only meaningful when `config.use_rtl=True`. When
        `use_rtl=False`, this returns (True, "RTL validation disabled").

        Returns:
            Tuple of (success, message):
            - (True, "...") if validation passed or was disabled
            - (False, "...") if validation failed with details

        Raises:
            RuntimeError: If Verilator is not available but RTL
                          validation was requested.

        Example:
            >>> runner = LinkRunner(LinkMonitorConfig(use_rtl=True))
            >>> # ... process events ...
            >>> success, msg = runner.validate_against_rtl()
            >>> if not success:
            ...     print(f"RTL mismatch: {msg}")
        """
        # ─────────────────────────────────────────────────────────────
        # Check if RTL validation is enabled
        # ─────────────────────────────────────────────────────────────
        if not self.config.use_rtl:
            return (True, "RTL validation disabled (use_rtl=False)")

        # ─────────────────────────────────────────────────────────────
        # Check if we have any events to validate
        # ─────────────────────────────────────────────────────────────
        if not self._events:
            return (True, "No events to validate")

        # ─────────────────────────────────────────────────────────────
        # Import RTL adapter (deferred to avoid requiring cocotb/verilator
        # when not using RTL validation)
        # ─────────────────────────────────────────────────────────────
        try:
            from thermalres.rtl.adapter import (
                check_verilator_available,
                run_link_monitor_rtl,
            )
        except ImportError as e:
            return (False, f"Failed to import RTL adapter: {e}")

        # Check Verilator availability
        if not check_verilator_available():
            raise RuntimeError(
                "Verilator not found. Install with: "
                "conda install -c conda-forge verilator (or apt/brew)"
            )

        # ─────────────────────────────────────────────────────────────
        # Convert events to RTL pattern format
        # Each event becomes a (valid, crc_fail) tuple
        # ─────────────────────────────────────────────────────────────
        pattern = [(True, e.crc_fail) for e in self._events]

        # ─────────────────────────────────────────────────────────────
        # Run RTL simulation
        # ─────────────────────────────────────────────────────────────
        try:
            rtl_samples = run_link_monitor_rtl(
                pattern=pattern,
                fails_to_down=self.config.fails_to_down,
                passes_to_up=self.config.passes_to_up,
            )
        except Exception as e:
            return (False, f"RTL simulation failed: {e}")

        # ─────────────────────────────────────────────────────────────
        # Compare RTL outputs against Python samples
        # ─────────────────────────────────────────────────────────────
        if len(rtl_samples) != len(self._samples):
            return (
                False,
                f"Sample count mismatch: Python={len(self._samples)}, "
                f"RTL={len(rtl_samples)}",
            )

        for i, (py_sample, rtl_sample) in enumerate(
            zip(self._samples, rtl_samples)
        ):
            # Check each field for equivalence
            mismatches = []

            if py_sample.link_up != rtl_sample.link_up:
                mismatches.append(
                    f"link_up: Python={py_sample.link_up}, RTL={rtl_sample.link_up}"
                )

            if py_sample.total_frames != rtl_sample.total_frames:
                mismatches.append(
                    f"total_frames: Python={py_sample.total_frames}, "
                    f"RTL={rtl_sample.total_frames}"
                )

            if py_sample.total_crc_fails != rtl_sample.total_crc_fails:
                mismatches.append(
                    f"total_crc_fails: Python={py_sample.total_crc_fails}, "
                    f"RTL={rtl_sample.total_crc_fails}"
                )

            if py_sample.consec_fails != rtl_sample.consec_fails:
                mismatches.append(
                    f"consec_fails: Python={py_sample.consec_fails}, "
                    f"RTL={rtl_sample.consec_fails}"
                )

            if py_sample.consec_passes != rtl_sample.consec_passes:
                mismatches.append(
                    f"consec_passes: Python={py_sample.consec_passes}, "
                    f"RTL={rtl_sample.consec_passes}"
                )

            if mismatches:
                return (
                    False,
                    f"Mismatch at cycle {py_sample.cycle} (index {i}): "
                    + "; ".join(mismatches),
                )

        # ─────────────────────────────────────────────────────────────
        # All checks passed
        # ─────────────────────────────────────────────────────────────
        return (
            True,
            f"RTL validation passed: {len(self._samples)} samples verified",
        )
