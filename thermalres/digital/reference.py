"""
Python reference model for link_monitor RTL.

This module provides a cycle-accurate Python implementation of the
link_monitor.sv RTL module. It is used for:
1. Fast simulation without requiring Verilator/cocotb
2. Equivalence testing against the RTL implementation
3. Understanding the link monitor behavior

The link monitor implements a hysteresis-based state machine that tracks
CRC failures on a communication link:
- Link starts in the UP state after reset
- After `fails_to_down` consecutive CRC failures, link transitions to DOWN
- After `passes_to_up` consecutive CRC passes, link transitions back to UP

This hysteresis prevents rapid state oscillation when the link is marginal.

Example usage:
    >>> from thermalres.digital.reference import LinkMonitorRef, LinkMonitorParams
    >>> monitor = LinkMonitorRef(LinkMonitorParams(fails_to_down=4, passes_to_up=8))
    >>> # Process some frames
    >>> state = monitor.step(valid=True, crc_fail=False)  # Pass
    >>> state = monitor.step(valid=True, crc_fail=True)   # Fail
    >>> print(f"Link up: {state.link_up}, Consec fails: {state.consec_fails}")
"""

from __future__ import annotations

from dataclasses import dataclass

# Import LinkStateSample for the get_sample method
# This creates a circular import risk, so we use TYPE_CHECKING
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from thermalres.cosim.interfaces import LinkStateSample


@dataclass
class LinkMonitorParams:
    """
    Parameters for the link monitor state machine.

    These parameters control the hysteresis thresholds that determine
    when the link state transitions between UP and DOWN. The defaults
    match the RTL link_monitor.sv parameters.

    Attributes:
        fails_to_down: Number of consecutive CRC failures required to
                       transition from link_up=True to link_up=False.
                       Must be positive. Default is 4.
        passes_to_up: Number of consecutive CRC passes required to
                      transition from link_up=False to link_up=True.
                      Must be positive. Default is 8.

    Note:
        The asymmetric defaults (4 to go down, 8 to come up) create
        "stickiness" - once a link goes down, it requires more evidence
        of recovery before coming back up. This is typical in real
        communication systems to avoid flapping.
    """

    fails_to_down: int = 4  # Consecutive fails to trigger link down
    passes_to_up: int = 8   # Consecutive passes to trigger link up


@dataclass
class LinkMonitorState:
    """
    Link monitor internal state.

    This dataclass holds the mutable state of the link monitor and
    matches the outputs of link_monitor.sv exactly. It is used
    internally by LinkMonitorRef and can be inspected for debugging.

    Attributes:
        link_up: Current link state. True means the link is considered
                 healthy; False means degraded/down.
        total_frames: Running count of all frames processed (valid=True
                      cycles) since reset. Never decrements.
        total_crc_fails: Running count of all CRC failures observed
                         since reset. Never decrements.
        consec_fails: Current streak of consecutive CRC failures.
                      Resets to 0 on any CRC pass.
        consec_passes: Current streak of consecutive CRC passes.
                       Resets to 0 on any CRC failure.
    """

    link_up: bool
    total_frames: int
    total_crc_fails: int
    consec_fails: int
    consec_passes: int


class LinkMonitorRef:
    """
    Reference implementation of link_monitor RTL.

    This class provides a cycle-accurate Python model of the SystemVerilog
    link_monitor module. It maintains state and provides a step() method
    that mirrors the RTL behavior exactly.

    The state machine logic is:
    ```
    on reset:
        link_up = True
        all counters = 0

    on each valid frame:
        total_frames++
        if crc_fail:
            total_crc_fails++
            consec_fails++
            consec_passes = 0
            if link_up and consec_fails >= FAILS_TO_DOWN:
                link_up = False
        else:
            consec_passes++
            consec_fails = 0
            if not link_up and consec_passes >= PASSES_TO_UP:
                link_up = True
    ```

    Example:
        >>> monitor = LinkMonitorRef()
        >>> # Simulate 4 consecutive failures to bring link down
        >>> for _ in range(4):
        ...     state = monitor.step(valid=True, crc_fail=True)
        >>> print(state.link_up)  # False - link is down
        >>> # Now simulate 8 consecutive passes to bring link back up
        >>> for _ in range(8):
        ...     state = monitor.step(valid=True, crc_fail=False)
        >>> print(state.link_up)  # True - link is up again
    """

    def __init__(self, params: LinkMonitorParams | None = None):
        """
        Initialize link monitor reference model.

        Creates a new link monitor in the reset state (link_up=True,
        all counters at zero).

        Args:
            params: Link monitor parameters controlling the hysteresis
                    thresholds. Uses default LinkMonitorParams() if None.
        """
        # Store parameters (use defaults if not provided)
        self.params = params or LinkMonitorParams()

        # Initialize to reset state
        # Link starts up, all counters at zero
        self.state = LinkMonitorState(
            link_up=True,       # Link starts up (matches RTL reset)
            total_frames=0,
            total_crc_fails=0,
            consec_fails=0,
            consec_passes=0,
        )

    def reset(self) -> None:
        """
        Reset the link monitor to initial state.

        This mirrors the behavior of asserting rst_n=0 in the RTL.
        After reset:
        - link_up = True (link assumed healthy)
        - All counters = 0
        """
        self.state = LinkMonitorState(
            link_up=True,
            total_frames=0,
            total_crc_fails=0,
            consec_fails=0,
            consec_passes=0,
        )

    def step(self, valid: bool, crc_fail: bool) -> LinkMonitorState:
        """
        Step the link monitor by one cycle.

        This method implements one clock cycle of the link_monitor.sv
        state machine. If valid=False, no state change occurs (the
        frame is ignored). If valid=True, the frame is processed and
        counters/state are updated accordingly.

        Args:
            valid: Frame present signal (acts as clock enable).
                   If False, the crc_fail input is ignored and no
                   state change occurs.
            crc_fail: CRC failure indication for the current frame.
                      Only meaningful when valid=True.

        Returns:
            The current LinkMonitorState after processing. Note that
            this returns a reference to the internal state object,
            not a copy. The state is mutable.

        Note:
            The RTL uses registered outputs, meaning state changes
            appear on the next clock edge. This Python model updates
            state immediately for simplicity, but the logical behavior
            is equivalent when sampled at the right point.
        """
        # If no valid frame, no state change
        # This matches the RTL's "else if (valid)" condition
        if not valid:
            return self.state

        # ─────────────────────────────────────────────────────────────
        # Frame is valid - update counters and check for state transitions
        # ─────────────────────────────────────────────────────────────

        # Always increment total frame counter
        self.state.total_frames += 1

        if crc_fail:
            # ─────────────────────────────────────────────────────────
            # CRC FAILURE PATH
            # ─────────────────────────────────────────────────────────
            # Increment failure counters, reset pass streak
            self.state.total_crc_fails += 1
            self.state.consec_fails += 1
            self.state.consec_passes = 0  # Reset consecutive pass counter

            # Check if we should transition to link DOWN
            # Only transition if currently UP and threshold reached
            # With fails_to_down=4, the 4th consecutive failure triggers
            # the transition (consec_fails will be 4 after increment).
            if (
                self.state.link_up
                and self.state.consec_fails >= self.params.fails_to_down
            ):
                self.state.link_up = False
        else:
            # ─────────────────────────────────────────────────────────
            # CRC PASS PATH
            # ─────────────────────────────────────────────────────────
            # Increment pass counter, reset failure streak
            self.state.consec_passes += 1
            self.state.consec_fails = 0  # Reset consecutive fail counter

            # Check if we should transition to link UP
            # Only transition if currently DOWN and threshold reached
            # With passes_to_up=8, the 8th consecutive pass triggers
            # the transition (consec_passes will be 8 after increment).
            if (
                not self.state.link_up
                and self.state.consec_passes >= self.params.passes_to_up
            ):
                self.state.link_up = True

        return self.state

    def get_state(self) -> LinkMonitorState:
        """
        Get the current state without advancing.

        Returns:
            Current LinkMonitorState (reference to internal state).
        """
        return self.state

    def to_link_state_sample(self, cycle: int) -> "LinkStateSample":
        """
        Convert current state to a LinkStateSample for recording.

        This method creates an immutable LinkStateSample dataclass
        from the current mutable state, suitable for storing in
        simulation results.

        Args:
            cycle: The simulation cycle number to tag the sample with.

        Returns:
            A frozen LinkStateSample capturing the current state.

        Note:
            This import is deferred to avoid circular imports at
            module load time.
        """
        # Deferred import to avoid circular dependency
        from thermalres.cosim.interfaces import LinkStateSample

        return LinkStateSample(
            cycle=cycle,
            link_up=self.state.link_up,
            total_frames=self.state.total_frames,
            total_crc_fails=self.state.total_crc_fails,
            consec_fails=self.state.consec_fails,
            consec_passes=self.state.consec_passes,
        )
