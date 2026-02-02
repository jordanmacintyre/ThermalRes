"""
RTL equivalence tests.

This module tests the equivalence between:
1. Python reference model (LinkMonitorRef)
2. LinkRunner wrapper
3. RTL simulation via cocotb/Verilator (when available)

The tests are organized into three levels:
- Reference model tests: Always run, test Python implementation
- LinkRunner tests: Always run, test LinkRunner wrapper
- RTL tests: Only run when Verilator is available

RTL tests can be run manually with:
    make -C sim/cocotb

To skip RTL tests (e.g., in CI without Verilator):
    pytest tests/rtl/ -k "not rtl"
"""

from __future__ import annotations

import random
import shutil

import pytest

from thermalres.cosim.interfaces import CrcEvent, LinkMonitorConfig
from thermalres.cosim.link_runner import LinkRunner
from thermalres.digital import LinkMonitorParams, LinkMonitorRef


# ─────────────────────────────────────────────────────────────────────────────
# Verilator Detection
# ─────────────────────────────────────────────────────────────────────────────


def check_verilator() -> bool:
    """
    Check if Verilator is available on the system PATH.

    Returns:
        True if Verilator is found, False otherwise.
    """
    return shutil.which("verilator") is not None


# ─────────────────────────────────────────────────────────────────────────────
# Python Reference Model Tests (Always Run)
# ─────────────────────────────────────────────────────────────────────────────


class TestPythonReferenceModel:
    """Tests for the Python reference model (LinkMonitorRef)."""

    def test_initial_state(self):
        """Test initial state after construction."""
        ref = LinkMonitorRef()

        assert ref.state.link_up is True, "Link should start up"
        assert ref.state.total_frames == 0
        assert ref.state.total_crc_fails == 0
        assert ref.state.consec_fails == 0
        assert ref.state.consec_passes == 0

    def test_basic_pass_handling(self):
        """Test handling of CRC pass events."""
        ref = LinkMonitorRef()

        for i in range(5):
            state = ref.step(valid=True, crc_fail=False)
            assert state.link_up is True
            assert state.total_frames == i + 1
            assert state.consec_passes == i + 1
            assert state.consec_fails == 0

    def test_basic_fail_handling(self):
        """Test handling of CRC failure events."""
        ref = LinkMonitorRef()

        for i in range(3):
            state = ref.step(valid=True, crc_fail=True)
            assert state.link_up is True  # Still up (need 4 by default)
            assert state.total_crc_fails == i + 1
            assert state.consec_fails == i + 1
            assert state.consec_passes == 0

    def test_link_down_transition(self):
        """Test link down transition after consecutive failures."""
        ref = LinkMonitorRef(LinkMonitorParams(fails_to_down=4, passes_to_up=8))

        # 3 failures - still up
        for _ in range(3):
            state = ref.step(valid=True, crc_fail=True)
            assert state.link_up is True

        # 4th failure - goes down
        state = ref.step(valid=True, crc_fail=True)
        assert state.link_up is False
        assert state.consec_fails == 4

    def test_link_up_transition(self):
        """Test link up transition after consecutive passes."""
        ref = LinkMonitorRef(LinkMonitorParams(fails_to_down=4, passes_to_up=8))

        # First bring link down
        for _ in range(4):
            ref.step(valid=True, crc_fail=True)
        assert ref.state.link_up is False

        # 7 passes - still down
        for _ in range(7):
            state = ref.step(valid=True, crc_fail=False)
            assert state.link_up is False

        # 8th pass - comes up
        state = ref.step(valid=True, crc_fail=False)
        assert state.link_up is True
        assert state.consec_passes == 8

    def test_consecutive_counter_reset(self):
        """Test that consecutive counters reset on opposite event."""
        ref = LinkMonitorRef()

        # Build up consec_fails
        for _ in range(2):
            ref.step(valid=True, crc_fail=True)
        assert ref.state.consec_fails == 2

        # Pass resets consec_fails
        ref.step(valid=True, crc_fail=False)
        assert ref.state.consec_fails == 0
        assert ref.state.consec_passes == 1

        # Fail resets consec_passes
        ref.step(valid=True, crc_fail=True)
        assert ref.state.consec_passes == 0
        assert ref.state.consec_fails == 1

    def test_invalid_frames_ignored(self):
        """Test that invalid frames (valid=False) don't update state."""
        ref = LinkMonitorRef()

        # Process some valid frames
        for _ in range(5):
            ref.step(valid=True, crc_fail=False)

        initial_frames = ref.state.total_frames
        initial_passes = ref.state.consec_passes

        # Invalid frames should be ignored
        for _ in range(10):
            ref.step(valid=False, crc_fail=True)  # Would be fails if valid

        assert ref.state.total_frames == initial_frames
        assert ref.state.consec_passes == initial_passes
        assert ref.state.total_crc_fails == 0

    def test_reset(self):
        """Test reset functionality."""
        ref = LinkMonitorRef()

        # Modify state
        for _ in range(10):
            ref.step(valid=True, crc_fail=True)

        # Reset
        ref.reset()

        # Should be back to initial
        assert ref.state.link_up is True
        assert ref.state.total_frames == 0
        assert ref.state.total_crc_fails == 0
        assert ref.state.consec_fails == 0
        assert ref.state.consec_passes == 0

    def test_determinism(self):
        """Test that reference model is deterministic."""
        params = LinkMonitorParams(fails_to_down=4, passes_to_up=8)

        # Generate pattern
        random.seed(42)
        pattern = [(True, random.random() < 0.3) for _ in range(100)]

        # Run twice
        ref1 = LinkMonitorRef(params)
        states1 = [ref1.step(v, f) for v, f in pattern]

        ref2 = LinkMonitorRef(params)
        states2 = [ref2.step(v, f) for v, f in pattern]

        # Should be identical
        for s1, s2 in zip(states1, states2):
            assert s1.link_up == s2.link_up
            assert s1.total_frames == s2.total_frames
            assert s1.total_crc_fails == s2.total_crc_fails

    def test_to_link_state_sample(self):
        """Test conversion to LinkStateSample."""
        ref = LinkMonitorRef()

        # Process some events
        for i in range(5):
            ref.step(valid=True, crc_fail=i % 2 == 0)

        # Convert to sample
        sample = ref.to_link_state_sample(cycle=42)

        assert sample.cycle == 42
        assert sample.link_up == ref.state.link_up
        assert sample.total_frames == ref.state.total_frames
        assert sample.total_crc_fails == ref.state.total_crc_fails


# ─────────────────────────────────────────────────────────────────────────────
# LinkRunner Wrapper Tests (Always Run)
# ─────────────────────────────────────────────────────────────────────────────


class TestLinkRunnerEquivalence:
    """Tests for LinkRunner equivalence with reference model."""

    def test_link_runner_matches_reference(self):
        """Test that LinkRunner produces same results as reference model."""
        # Same parameters
        params = LinkMonitorParams(fails_to_down=4, passes_to_up=8)
        config = LinkMonitorConfig(fails_to_down=4, passes_to_up=8, use_rtl=False)

        # Generate pattern
        random.seed(123)
        pattern = [random.random() < 0.35 for _ in range(50)]

        # Run reference model
        ref = LinkMonitorRef(params)
        ref_states = []
        for i, crc_fail in enumerate(pattern):
            state = ref.step(valid=True, crc_fail=crc_fail)
            ref_states.append(
                (state.link_up, state.total_frames, state.total_crc_fails)
            )

        # Run LinkRunner
        runner = LinkRunner(config)
        runner_states = []
        for i, crc_fail in enumerate(pattern):
            event = CrcEvent(
                cycle=i,
                chunk_idx=0,
                crc_fail=crc_fail,
                crc_fail_prob=1.0 if crc_fail else 0.0,
            )
            sample = runner.step(event)
            runner_states.append(
                (sample.link_up, sample.total_frames, sample.total_crc_fails)
            )

        # Compare
        assert ref_states == runner_states

    def test_link_runner_custom_thresholds(self):
        """Test LinkRunner with custom thresholds matches reference."""
        params = LinkMonitorParams(fails_to_down=2, passes_to_up=3)
        config = LinkMonitorConfig(fails_to_down=2, passes_to_up=3, use_rtl=False)

        pattern = [True, True, False, False, False, True]  # Down, then up

        # Reference
        ref = LinkMonitorRef(params)
        ref_final = None
        for crc_fail in pattern:
            ref_final = ref.step(valid=True, crc_fail=crc_fail)

        # LinkRunner
        runner = LinkRunner(config)
        runner_final = None
        for i, crc_fail in enumerate(pattern):
            event = CrcEvent(
                cycle=i, chunk_idx=0, crc_fail=crc_fail, crc_fail_prob=0.5
            )
            runner_final = runner.step(event)

        assert runner_final.link_up == ref_final.link_up
        assert runner_final.total_frames == ref_final.total_frames


# ─────────────────────────────────────────────────────────────────────────────
# RTL Equivalence Tests (Require Verilator)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not check_verilator(), reason="Verilator not found")
class TestRtlEquivalence:
    """RTL equivalence tests requiring Verilator."""

    def test_link_runner_rtl_validation_random_pattern(self):
        """Test LinkRunner RTL validation with random pattern."""
        config = LinkMonitorConfig(fails_to_down=4, passes_to_up=8, use_rtl=True)
        runner = LinkRunner(config)

        # Generate random pattern
        random.seed(456)
        for i in range(100):
            crc_fail = random.random() < 0.3
            event = CrcEvent(
                cycle=i,
                chunk_idx=i // 10,
                crc_fail=crc_fail,
                crc_fail_prob=0.3 if crc_fail else 0.0,
            )
            runner.step(event)

        # Validate against RTL
        success, message = runner.validate_against_rtl()
        assert success, f"RTL validation failed: {message}"

    def test_link_runner_rtl_validation_all_passes(self):
        """Test RTL validation with all passes."""
        config = LinkMonitorConfig(fails_to_down=4, passes_to_up=8, use_rtl=True)
        runner = LinkRunner(config)

        for i in range(50):
            event = CrcEvent(
                cycle=i, chunk_idx=0, crc_fail=False, crc_fail_prob=0.0
            )
            runner.step(event)

        success, message = runner.validate_against_rtl()
        assert success, f"RTL validation failed: {message}"

    def test_link_runner_rtl_validation_all_fails(self):
        """Test RTL validation with all failures."""
        config = LinkMonitorConfig(fails_to_down=4, passes_to_up=8, use_rtl=True)
        runner = LinkRunner(config)

        for i in range(50):
            event = CrcEvent(
                cycle=i, chunk_idx=0, crc_fail=True, crc_fail_prob=1.0
            )
            runner.step(event)

        success, message = runner.validate_against_rtl()
        assert success, f"RTL validation failed: {message}"

    def test_link_runner_rtl_validation_alternating(self):
        """Test RTL validation with alternating pattern."""
        config = LinkMonitorConfig(fails_to_down=4, passes_to_up=8, use_rtl=True)
        runner = LinkRunner(config)

        for i in range(50):
            crc_fail = i % 2 == 0
            event = CrcEvent(
                cycle=i,
                chunk_idx=0,
                crc_fail=crc_fail,
                crc_fail_prob=0.5,
            )
            runner.step(event)

        success, message = runner.validate_against_rtl()
        assert success, f"RTL validation failed: {message}"

    def test_link_runner_rtl_validation_link_flap(self):
        """Test RTL validation with link flapping scenario."""
        config = LinkMonitorConfig(fails_to_down=2, passes_to_up=2, use_rtl=True)
        runner = LinkRunner(config)

        # Pattern that causes link to flap: 2 fails, 2 passes, repeat
        cycle = 0
        for _ in range(5):  # 5 flap cycles
            # 2 fails -> link down
            for _ in range(2):
                event = CrcEvent(
                    cycle=cycle, chunk_idx=0, crc_fail=True, crc_fail_prob=1.0
                )
                runner.step(event)
                cycle += 1

            # 2 passes -> link up
            for _ in range(2):
                event = CrcEvent(
                    cycle=cycle, chunk_idx=0, crc_fail=False, crc_fail_prob=0.0
                )
                runner.step(event)
                cycle += 1

        success, message = runner.validate_against_rtl()
        assert success, f"RTL validation failed: {message}"


# ─────────────────────────────────────────────────────────────────────────────
# Edge Case Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge case tests for reference model and LinkRunner."""

    def test_minimum_threshold_values(self):
        """Test with minimum threshold values (1)."""
        params = LinkMonitorParams(fails_to_down=1, passes_to_up=1)
        ref = LinkMonitorRef(params)

        # Single fail brings link down
        ref.step(valid=True, crc_fail=True)
        assert ref.state.link_up is False

        # Single pass brings link up
        ref.step(valid=True, crc_fail=False)
        assert ref.state.link_up is True

    def test_large_threshold_values(self):
        """Test with large threshold values."""
        params = LinkMonitorParams(fails_to_down=100, passes_to_up=200)
        ref = LinkMonitorRef(params)

        # 99 failures - still up
        for _ in range(99):
            ref.step(valid=True, crc_fail=True)
        assert ref.state.link_up is True

        # 100th failure - goes down
        ref.step(valid=True, crc_fail=True)
        assert ref.state.link_up is False

    def test_boundary_at_threshold(self):
        """Test exact boundary behavior at threshold."""
        params = LinkMonitorParams(fails_to_down=4, passes_to_up=8)
        ref = LinkMonitorRef(params)

        # Exactly at threshold - 1
        for _ in range(3):
            ref.step(valid=True, crc_fail=True)
        assert ref.state.link_up is True
        assert ref.state.consec_fails == 3

        # Cross threshold
        ref.step(valid=True, crc_fail=True)
        assert ref.state.link_up is False
        assert ref.state.consec_fails == 4


# ─────────────────────────────────────────────────────────────────────────────
# Legacy test functions (for backward compatibility)
# These are standalone functions that replicate the original test behavior
# ─────────────────────────────────────────────────────────────────────────────


def test_python_reference_basic():
    """Test Python reference model basic behavior (legacy test name)."""
    ref = LinkMonitorRef(LinkMonitorParams(fails_to_down=4, passes_to_up=8))

    # Initial state
    assert ref.state.link_up is True
    assert ref.state.total_frames == 0

    # Send some passes
    for _ in range(3):
        state = ref.step(valid=True, crc_fail=False)
        assert state.link_up is True

    # Send consecutive failures
    for i in range(4):
        state = ref.step(valid=True, crc_fail=True)
        if i < 3:
            assert state.link_up is True
        else:
            assert state.link_up is False  # Should go down on 4th fail

    assert ref.state.total_frames == 7
    assert ref.state.total_crc_fails == 4
    assert ref.state.consec_fails == 4


@pytest.mark.skipif(not check_verilator(), reason="Verilator not found")
def test_python_reference_link_recovery():
    """Test Python reference model link recovery (legacy test name)."""
    ref = LinkMonitorRef(LinkMonitorParams(fails_to_down=4, passes_to_up=8))

    # Take link down
    for _ in range(4):
        ref.step(valid=True, crc_fail=True)

    assert ref.state.link_up is False

    # Recover with consecutive passes
    for i in range(8):
        state = ref.step(valid=True, crc_fail=False)
        if i < 7:
            assert state.link_up is False
        else:
            assert state.link_up is True  # Should come up on 8th pass

    assert ref.state.consec_passes == 8
    assert ref.state.consec_fails == 0


@pytest.mark.skipif(not check_verilator(), reason="Verilator not found")
def test_python_reference_deterministic():
    """Test Python reference determinism (legacy test name)."""
    params = LinkMonitorParams(fails_to_down=4, passes_to_up=8)

    # Generate deterministic pattern
    random.seed(42)
    pattern = [(True, random.random() < 0.3) for _ in range(50)]

    # Run twice
    ref1 = LinkMonitorRef(params)
    states1 = [ref1.step(v, f) for v, f in pattern]

    ref2 = LinkMonitorRef(params)
    states2 = [ref2.step(v, f) for v, f in pattern]

    # Should be identical
    for s1, s2 in zip(states1, states2):
        assert s1.link_up == s2.link_up
        assert s1.total_frames == s2.total_frames
        assert s1.total_crc_fails == s2.total_crc_fails
        assert s1.consec_fails == s2.consec_fails
        assert s1.consec_passes == s2.consec_passes


@pytest.mark.skipif(not check_verilator(), reason="Verilator not found")
def test_reference_model_reset():
    """Test reset (legacy test name)."""
    ref = LinkMonitorRef()

    # Run some cycles
    for _ in range(10):
        ref.step(valid=True, crc_fail=True)

    # Reset
    ref.reset()

    # Should be back to initial state
    assert ref.state.link_up is True
    assert ref.state.total_frames == 0
    assert ref.state.total_crc_fails == 0
    assert ref.state.consec_fails == 0
    assert ref.state.consec_passes == 0


@pytest.mark.skipif(not check_verilator(), reason="Verilator not found")
def test_reference_model_no_update_when_not_valid():
    """Test invalid frame handling (legacy test name)."""
    ref = LinkMonitorRef()

    # Send some valid frames
    for _ in range(5):
        ref.step(valid=True, crc_fail=False)

    initial_frames = ref.state.total_frames

    # Send invalid frames (should be ignored)
    for _ in range(10):
        ref.step(valid=False, crc_fail=True)

    # Counters should not have changed
    assert ref.state.total_frames == initial_frames
    assert ref.state.total_crc_fails == 0
