"""
Unit tests for LinkRunner.

This module tests the LinkRunner component that bridges the CoSimKernel
with the link monitor state machine. It verifies:
- Basic event processing
- Link state transitions (up -> down -> up)
- Counter updates (total_frames, total_crc_fails, consec_*)
- Reset functionality
- Sample history accumulation

These tests use the Python reference model only (no RTL). RTL equivalence
tests are in tests/rtl/test_rtl_equiv.py.
"""

import pytest

from thermalres.cosim.interfaces import CrcEvent, LinkMonitorConfig, LinkStateSample
from thermalres.cosim.link_runner import LinkRunner


# ─────────────────────────────────────────────────────────────────────────────
# Basic Functionality Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLinkRunnerBasic:
    """Tests for basic LinkRunner functionality."""

    def test_init_default_config(self):
        """Test that LinkRunner initializes with default config."""
        runner = LinkRunner()

        # Should have default config
        assert runner.config.fails_to_down == 4
        assert runner.config.passes_to_up == 8
        assert runner.config.use_rtl is False

        # Should start with empty history
        assert len(runner.get_samples()) == 0
        assert len(runner.get_events()) == 0

    def test_init_custom_config(self):
        """Test that LinkRunner accepts custom config."""
        config = LinkMonitorConfig(
            fails_to_down=3,
            passes_to_up=6,
            use_rtl=False,
        )
        runner = LinkRunner(config)

        assert runner.config.fails_to_down == 3
        assert runner.config.passes_to_up == 6

    def test_step_single_pass(self):
        """Test processing a single CRC pass event."""
        runner = LinkRunner()

        event = CrcEvent(cycle=0, chunk_idx=0, crc_fail=False, crc_fail_prob=0.1)
        sample = runner.step(event)

        # Link should remain up
        assert sample.link_up is True
        # Counters should update
        assert sample.total_frames == 1
        assert sample.total_crc_fails == 0
        assert sample.consec_passes == 1
        assert sample.consec_fails == 0
        # Cycle should match event
        assert sample.cycle == 0

    def test_step_single_fail(self):
        """Test processing a single CRC failure event."""
        runner = LinkRunner()

        event = CrcEvent(cycle=0, chunk_idx=0, crc_fail=True, crc_fail_prob=0.9)
        sample = runner.step(event)

        # Link should still be up (need 4 consecutive fails by default)
        assert sample.link_up is True
        # Counters should update
        assert sample.total_frames == 1
        assert sample.total_crc_fails == 1
        assert sample.consec_fails == 1
        assert sample.consec_passes == 0

    def test_step_preserves_event_cycle(self):
        """Test that step preserves the event's cycle number in sample."""
        runner = LinkRunner()

        # Events with non-sequential cycles
        for cycle in [5, 10, 15]:
            event = CrcEvent(
                cycle=cycle, chunk_idx=0, crc_fail=False, crc_fail_prob=0.0
            )
            sample = runner.step(event)
            assert sample.cycle == cycle


# ─────────────────────────────────────────────────────────────────────────────
# Link State Transition Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLinkStateTransitions:
    """Tests for link up/down state transitions."""

    def test_link_goes_down_after_consecutive_fails(self):
        """Test that link transitions to DOWN after fails_to_down consecutive failures."""
        runner = LinkRunner()  # Default: fails_to_down=4

        # Send 3 failures - link should stay up
        for i in range(3):
            event = CrcEvent(cycle=i, chunk_idx=0, crc_fail=True, crc_fail_prob=1.0)
            sample = runner.step(event)
            assert sample.link_up is True, f"Link should be up after {i+1} fails"

        # 4th failure should bring link down
        event = CrcEvent(cycle=3, chunk_idx=0, crc_fail=True, crc_fail_prob=1.0)
        sample = runner.step(event)
        assert sample.link_up is False, "Link should be down after 4 consecutive fails"
        assert sample.consec_fails == 4

    def test_link_goes_up_after_consecutive_passes(self):
        """Test that link transitions to UP after passes_to_up consecutive passes."""
        runner = LinkRunner()  # Default: fails_to_down=4, passes_to_up=8

        # First, bring link down
        for i in range(4):
            event = CrcEvent(cycle=i, chunk_idx=0, crc_fail=True, crc_fail_prob=1.0)
            sample = runner.step(event)

        assert sample.link_up is False, "Link should be down"

        # Send 7 passes - link should stay down
        for i in range(7):
            event = CrcEvent(
                cycle=4 + i, chunk_idx=0, crc_fail=False, crc_fail_prob=0.0
            )
            sample = runner.step(event)
            assert sample.link_up is False, f"Link should stay down after {i+1} passes"

        # 8th pass should bring link up
        event = CrcEvent(cycle=11, chunk_idx=0, crc_fail=False, crc_fail_prob=0.0)
        sample = runner.step(event)
        assert sample.link_up is True, "Link should be up after 8 consecutive passes"
        assert sample.consec_passes == 8

    def test_consecutive_counter_resets_on_opposite_event(self):
        """Test that consecutive counters reset when opposite event occurs."""
        runner = LinkRunner()

        # Send 2 failures
        for i in range(2):
            event = CrcEvent(cycle=i, chunk_idx=0, crc_fail=True, crc_fail_prob=1.0)
            sample = runner.step(event)

        assert sample.consec_fails == 2
        assert sample.consec_passes == 0

        # Send 1 pass - should reset consec_fails
        event = CrcEvent(cycle=2, chunk_idx=0, crc_fail=False, crc_fail_prob=0.0)
        sample = runner.step(event)

        assert sample.consec_fails == 0, "Consecutive fails should reset on pass"
        assert sample.consec_passes == 1

    def test_custom_thresholds(self):
        """Test link transitions with custom thresholds."""
        config = LinkMonitorConfig(fails_to_down=2, passes_to_up=3)
        runner = LinkRunner(config)

        # 2 failures should bring link down
        for i in range(2):
            event = CrcEvent(cycle=i, chunk_idx=0, crc_fail=True, crc_fail_prob=1.0)
            sample = runner.step(event)

        assert sample.link_up is False, "Link should be down after 2 fails"

        # 3 passes should bring link up
        for i in range(3):
            event = CrcEvent(
                cycle=2 + i, chunk_idx=0, crc_fail=False, crc_fail_prob=0.0
            )
            sample = runner.step(event)

        assert sample.link_up is True, "Link should be up after 3 passes"


# ─────────────────────────────────────────────────────────────────────────────
# Counter Accuracy Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCounters:
    """Tests for counter accuracy."""

    def test_total_frames_increments(self):
        """Test that total_frames increments on every event."""
        runner = LinkRunner()

        for i in range(10):
            crc_fail = i % 3 == 0  # Mix of passes and fails
            event = CrcEvent(
                cycle=i,
                chunk_idx=0,
                crc_fail=crc_fail,
                crc_fail_prob=1.0 if crc_fail else 0.0,
            )
            sample = runner.step(event)
            assert sample.total_frames == i + 1

    def test_total_crc_fails_only_increments_on_fail(self):
        """Test that total_crc_fails only increments on failure events."""
        runner = LinkRunner()

        # Pass, Fail, Pass, Fail, Pass
        pattern = [False, True, False, True, False]
        expected_fails = 0

        for i, crc_fail in enumerate(pattern):
            if crc_fail:
                expected_fails += 1

            event = CrcEvent(
                cycle=i,
                chunk_idx=0,
                crc_fail=crc_fail,
                crc_fail_prob=1.0 if crc_fail else 0.0,
            )
            sample = runner.step(event)
            assert sample.total_crc_fails == expected_fails


# ─────────────────────────────────────────────────────────────────────────────
# Reset and History Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestResetAndHistory:
    """Tests for reset functionality and history management."""

    def test_reset_clears_state(self):
        """Test that reset clears link monitor state."""
        runner = LinkRunner()

        # Process some events
        for i in range(5):
            event = CrcEvent(cycle=i, chunk_idx=0, crc_fail=True, crc_fail_prob=1.0)
            runner.step(event)

        # State should show 5 frames
        current = runner.get_current_state()
        assert current is not None
        assert current.total_frames == 5

        # Reset
        runner.reset()

        # State should be cleared
        assert runner.get_current_state() is None
        assert len(runner.get_samples()) == 0
        assert len(runner.get_events()) == 0

    def test_get_samples_returns_copy(self):
        """Test that get_samples returns a copy, not internal list."""
        runner = LinkRunner()

        event = CrcEvent(cycle=0, chunk_idx=0, crc_fail=False, crc_fail_prob=0.0)
        runner.step(event)

        samples1 = runner.get_samples()
        samples2 = runner.get_samples()

        # Should be equal but not the same object
        assert samples1 == samples2
        assert samples1 is not samples2

        # Modifying returned list should not affect internal state
        samples1.clear()
        assert len(runner.get_samples()) == 1

    def test_get_events_returns_copy(self):
        """Test that get_events returns a copy, not internal list."""
        runner = LinkRunner()

        event = CrcEvent(cycle=0, chunk_idx=0, crc_fail=False, crc_fail_prob=0.0)
        runner.step(event)

        events1 = runner.get_events()
        events2 = runner.get_events()

        # Should be equal but not the same object
        assert events1 == events2
        assert events1 is not events2

    def test_get_current_state_before_any_events(self):
        """Test that get_current_state returns None before any events."""
        runner = LinkRunner()
        assert runner.get_current_state() is None

    def test_get_current_state_after_events(self):
        """Test that get_current_state returns most recent sample."""
        runner = LinkRunner()

        for i in range(5):
            event = CrcEvent(cycle=i, chunk_idx=0, crc_fail=False, crc_fail_prob=0.0)
            runner.step(event)

        current = runner.get_current_state()
        assert current is not None
        assert current.cycle == 4
        assert current.total_frames == 5


# ─────────────────────────────────────────────────────────────────────────────
# Sample Immutability Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestSampleImmutability:
    """Tests for LinkStateSample immutability."""

    def test_link_state_sample_is_frozen(self):
        """Test that LinkStateSample is immutable (frozen dataclass)."""
        runner = LinkRunner()

        event = CrcEvent(cycle=0, chunk_idx=0, crc_fail=False, crc_fail_prob=0.0)
        sample = runner.step(event)

        # Attempting to modify should raise an error
        with pytest.raises(AttributeError):
            sample.link_up = False  # type: ignore

        with pytest.raises(AttributeError):
            sample.total_frames = 999  # type: ignore


# ─────────────────────────────────────────────────────────────────────────────
# Edge Case Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_run(self):
        """Test LinkRunner with no events processed."""
        runner = LinkRunner()

        assert len(runner.get_samples()) == 0
        assert len(runner.get_events()) == 0
        assert runner.get_current_state() is None

    def test_all_passes(self):
        """Test a run with all CRC passes."""
        runner = LinkRunner()

        for i in range(100):
            event = CrcEvent(cycle=i, chunk_idx=0, crc_fail=False, crc_fail_prob=0.0)
            sample = runner.step(event)

        # Link should remain up throughout
        assert sample.link_up is True
        assert sample.total_frames == 100
        assert sample.total_crc_fails == 0

    def test_all_fails(self):
        """Test a run with all CRC failures."""
        runner = LinkRunner()

        for i in range(100):
            event = CrcEvent(cycle=i, chunk_idx=0, crc_fail=True, crc_fail_prob=1.0)
            sample = runner.step(event)

        # Link should go down after 4 fails and stay down
        assert sample.link_up is False
        assert sample.total_frames == 100
        assert sample.total_crc_fails == 100

    def test_alternating_pattern(self):
        """Test alternating pass/fail pattern (link should stay up)."""
        runner = LinkRunner()

        # Alternating pattern never accumulates 4 consecutive fails
        for i in range(100):
            crc_fail = i % 2 == 0
            event = CrcEvent(
                cycle=i,
                chunk_idx=0,
                crc_fail=crc_fail,
                crc_fail_prob=1.0 if crc_fail else 0.0,
            )
            sample = runner.step(event)

        # Link should stay up (never 4 consecutive fails)
        assert sample.link_up is True
        assert sample.total_frames == 100
        assert sample.total_crc_fails == 50

    def test_link_flap(self):
        """Test link going down and coming back up multiple times."""
        runner = LinkRunner(LinkMonitorConfig(fails_to_down=2, passes_to_up=2))

        # Cycle 0-1: 2 fails -> link down
        for i in range(2):
            event = CrcEvent(cycle=i, chunk_idx=0, crc_fail=True, crc_fail_prob=1.0)
            sample = runner.step(event)
        assert sample.link_up is False

        # Cycle 2-3: 2 passes -> link up
        for i in range(2, 4):
            event = CrcEvent(cycle=i, chunk_idx=0, crc_fail=False, crc_fail_prob=0.0)
            sample = runner.step(event)
        assert sample.link_up is True

        # Cycle 4-5: 2 fails -> link down again
        for i in range(4, 6):
            event = CrcEvent(cycle=i, chunk_idx=0, crc_fail=True, crc_fail_prob=1.0)
            sample = runner.step(event)
        assert sample.link_up is False


# ─────────────────────────────────────────────────────────────────────────────
# RTL Validation Tests (Python-only mode)
# ─────────────────────────────────────────────────────────────────────────────


class TestRtlValidationDisabled:
    """Tests for RTL validation when disabled."""

    def test_validate_rtl_returns_success_when_disabled(self):
        """Test that validate_against_rtl succeeds when use_rtl=False."""
        runner = LinkRunner(LinkMonitorConfig(use_rtl=False))

        # Process some events
        for i in range(10):
            event = CrcEvent(
                cycle=i, chunk_idx=0, crc_fail=i % 3 == 0, crc_fail_prob=0.5
            )
            runner.step(event)

        # Validation should pass (disabled)
        success, message = runner.validate_against_rtl()
        assert success is True
        assert "disabled" in message.lower()

    def test_validate_rtl_with_no_events(self):
        """Test validate_against_rtl with no events processed."""
        runner = LinkRunner(LinkMonitorConfig(use_rtl=True))

        # No events processed
        success, message = runner.validate_against_rtl()
        assert success is True
        assert "no events" in message.lower()
