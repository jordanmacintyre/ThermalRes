"""
System tests for link monitor integration with CoSimKernel.

This module tests the end-to-end integration of the link monitor with
the co-simulation kernel. It verifies:
- Kernel produces link state outputs when LinkRunner is configured
- Link states correlate correctly with CRC events
- Link state artifacts are written to disk
- Determinism (same seed -> same results)
- Backward compatibility (no link_runner -> no link_states)

These tests use the full simulation stack with plant models to generate
realistic CRC events from thermal/resonator/impairment physics.
"""

import json
import tempfile
from pathlib import Path

import pytest

from thermalres.config import PlantConfig, SimConfig
from thermalres.cosim.interfaces import CrcEvent, LinkMonitorConfig
from thermalres.cosim.kernel import CoSimKernel
from thermalres.cosim.link_runner import LinkRunner
from thermalres.cosim.metrics import write_run_artifacts
from thermalres.cosim.plant_runner import PlantRunner
from thermalres.plant import ThermalParams, ThermalState
from thermalres.plant.impairment import ImpairmentParams
from thermalres.plant.resonator import ResonatorParams
from thermalres.scenarios.open_loop import constant_heater, step_workload


# ─────────────────────────────────────────────────────────────────────────────
# Test Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _create_plant_runner(initial_temp: float = 25.0) -> PlantRunner:
    """
    Create a PlantRunner with default plant config.

    This helper creates a fully configured PlantRunner using the
    default physical parameters. It's used by multiple tests to
    ensure consistent setup.

    Args:
        initial_temp: Initial temperature in °C (default: ambient)

    Returns:
        Configured PlantRunner ready for simulation.
    """
    plant_cfg = PlantConfig()

    thermal_params = ThermalParams(
        ambient_c=plant_cfg.ambient_c,
        r_th_c_per_w=plant_cfg.r_th_c_per_w,
        c_th_j_per_c=plant_cfg.c_th_j_per_c,
        heater_w_max=plant_cfg.heater_w_max,
        workload_w_max=plant_cfg.workload_w_max,
    )

    resonator_params = ResonatorParams(
        lambda0_nm=plant_cfg.lambda0_nm,
        thermo_optic_nm_per_c=plant_cfg.thermo_optic_nm_per_c,
        lock_window_nm=plant_cfg.lock_window_nm,
        target_lambda_nm=plant_cfg.target_lambda_nm,
        ambient_c=plant_cfg.ambient_c,
    )

    impairment_params = ImpairmentParams(
        detune_50_nm=plant_cfg.detune_50_nm,
        detune_floor_nm=plant_cfg.detune_floor_nm,
        detune_ceil_nm=plant_cfg.detune_ceil_nm,
    )

    return PlantRunner(
        thermal_params=thermal_params,
        resonator_params=resonator_params,
        impairment_params=impairment_params,
        initial_temp_c=initial_temp,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Basic Integration Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestKernelLinkIntegration:
    """Tests for CoSimKernel integration with LinkRunner."""

    def test_kernel_produces_link_states_when_configured(self):
        """Test that kernel produces link_states when LinkRunner is configured."""
        config = SimConfig.from_args(
            name="link_test",
            cycles=50,
            cycle_chunks=10,
            seed=42,
            out_dir=None,
        )

        plant_runner = _create_plant_runner()
        schedule = constant_heater(heater=0.3, workload=0.2)
        link_runner = LinkRunner()

        kernel = CoSimKernel(
            config,
            plant_runner=plant_runner,
            schedule=schedule,
            link_runner=link_runner,
        )
        result = kernel.run()

        # Should have link states
        assert result.link_states is not None
        assert len(result.link_states) > 0

        # Should have same count as events
        assert len(result.link_states) == len(result.events)

    def test_kernel_no_link_states_without_link_runner(self):
        """Test backward compatibility: no link_states without LinkRunner."""
        config = SimConfig.from_args(
            name="no_link_test",
            cycles=50,
            cycle_chunks=10,
            seed=42,
            out_dir=None,
        )

        plant_runner = _create_plant_runner()
        schedule = constant_heater(heater=0.3, workload=0.2)

        # No link_runner configured
        kernel = CoSimKernel(
            config,
            plant_runner=plant_runner,
            schedule=schedule,
        )
        result = kernel.run()

        # link_states should be None
        assert result.link_states is None

    def test_link_states_correlate_with_events(self):
        """Test that link states cycle numbers match CRC events."""
        config = SimConfig.from_args(
            name="correlation_test",
            cycles=30,
            cycle_chunks=5,
            seed=123,
            out_dir=None,
        )

        plant_runner = _create_plant_runner()
        schedule = constant_heater(heater=0.5, workload=0.3)
        link_runner = LinkRunner()

        kernel = CoSimKernel(
            config,
            plant_runner=plant_runner,
            schedule=schedule,
            link_runner=link_runner,
        )
        result = kernel.run()

        # Each link state should have matching cycle with event
        for event, link_state in zip(result.events, result.link_states):
            assert event.cycle == link_state.cycle, (
                f"Cycle mismatch: event.cycle={event.cycle}, "
                f"link_state.cycle={link_state.cycle}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Link State Consistency Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLinkStateConsistency:
    """Tests for link state logical consistency."""

    def test_total_frames_equals_sample_count(self):
        """Test that final total_frames equals number of samples."""
        config = SimConfig.from_args(
            name="frames_test",
            cycles=100,
            cycle_chunks=10,
            seed=999,
            out_dir=None,
        )

        plant_runner = _create_plant_runner()
        schedule = constant_heater(heater=0.4, workload=0.25)
        link_runner = LinkRunner()

        kernel = CoSimKernel(
            config,
            plant_runner=plant_runner,
            schedule=schedule,
            link_runner=link_runner,
        )
        result = kernel.run()

        final_state = result.link_states[-1]
        assert final_state.total_frames == len(result.link_states)

    def test_total_crc_fails_matches_events(self):
        """Test that total_crc_fails matches count of crc_fail=True events."""
        config = SimConfig.from_args(
            name="crc_count_test",
            cycles=100,
            cycle_chunks=5,
            seed=777,
            out_dir=None,
        )

        plant_runner = _create_plant_runner()
        schedule = constant_heater(heater=0.2, workload=0.4)
        link_runner = LinkRunner()

        kernel = CoSimKernel(
            config,
            plant_runner=plant_runner,
            schedule=schedule,
            link_runner=link_runner,
        )
        result = kernel.run()

        # Count CRC failures from events
        expected_fails = sum(1 for e in result.events if e.crc_fail)

        # Should match final total_crc_fails
        final_state = result.link_states[-1]
        assert final_state.total_crc_fails == expected_fails

    def test_counters_are_monotonic(self):
        """Test that total_frames and total_crc_fails never decrease."""
        config = SimConfig.from_args(
            name="monotonic_test",
            cycles=50,
            cycle_chunks=5,
            seed=555,
            out_dir=None,
        )

        plant_runner = _create_plant_runner()
        schedule = step_workload(
            heater=0.3, workload_low=0.1, workload_high=0.5, step_at_cycle=25
        )
        link_runner = LinkRunner()

        kernel = CoSimKernel(
            config,
            plant_runner=plant_runner,
            schedule=schedule,
            link_runner=link_runner,
        )
        result = kernel.run()

        prev_frames = 0
        prev_fails = 0

        for state in result.link_states:
            assert state.total_frames >= prev_frames, (
                f"total_frames decreased: {prev_frames} -> {state.total_frames}"
            )
            assert state.total_crc_fails >= prev_fails, (
                f"total_crc_fails decreased: {prev_fails} -> {state.total_crc_fails}"
            )
            prev_frames = state.total_frames
            prev_fails = state.total_crc_fails


# ─────────────────────────────────────────────────────────────────────────────
# Artifact Generation Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLinkStateArtifacts:
    """Tests for link_state.json artifact generation."""

    def test_link_state_json_written(self):
        """Test that link_state.json is written when link_states present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir)

            config = SimConfig.from_args(
                name="artifact_test",
                cycles=20,
                cycle_chunks=5,
                seed=42,
                out_dir=str(out_path),
            )

            plant_runner = _create_plant_runner()
            schedule = constant_heater(heater=0.5, workload=0.3)
            link_runner = LinkRunner()

            kernel = CoSimKernel(
                config,
                plant_runner=plant_runner,
                schedule=schedule,
                link_runner=link_runner,
            )
            result = kernel.run()

            # Write artifacts
            write_run_artifacts(
                out_path=config.out_dir,
                metrics=result.metrics,
                chunks=result.chunks,
                timeseries=result.timeseries,
                events=result.events,
                link_states=result.link_states,
            )

            # Check link_state.json exists
            link_state_file = config.out_dir / "link_state.json"
            assert link_state_file.exists(), "link_state.json should be created"

    def test_link_state_json_not_written_without_link_states(self):
        """Test that link_state.json is NOT written when link_states is None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir)

            config = SimConfig.from_args(
                name="no_artifact_test",
                cycles=20,
                cycle_chunks=5,
                seed=42,
                out_dir=str(out_path),
            )

            plant_runner = _create_plant_runner()
            schedule = constant_heater(heater=0.5, workload=0.3)
            # No link_runner

            kernel = CoSimKernel(
                config,
                plant_runner=plant_runner,
                schedule=schedule,
            )
            result = kernel.run()

            # Write artifacts (no link_states)
            write_run_artifacts(
                out_path=config.out_dir,
                metrics=result.metrics,
                chunks=result.chunks,
                timeseries=result.timeseries,
                events=result.events,
                link_states=result.link_states,
            )

            # link_state.json should NOT exist
            link_state_file = config.out_dir / "link_state.json"
            assert not link_state_file.exists(), "link_state.json should not be created"

    def test_link_state_json_schema(self):
        """Test that link_state.json has correct schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir)

            config = SimConfig.from_args(
                name="schema_test",
                cycles=10,
                cycle_chunks=5,
                seed=42,
                out_dir=str(out_path),
            )

            plant_runner = _create_plant_runner()
            schedule = constant_heater(heater=0.5, workload=0.3)
            link_runner = LinkRunner()

            kernel = CoSimKernel(
                config,
                plant_runner=plant_runner,
                schedule=schedule,
                link_runner=link_runner,
            )
            result = kernel.run()

            write_run_artifacts(
                out_path=config.out_dir,
                metrics=result.metrics,
                chunks=result.chunks,
                timeseries=result.timeseries,
                events=result.events,
                link_states=result.link_states,
            )

            # Load and verify schema
            link_state_file = config.out_dir / "link_state.json"
            with open(link_state_file) as f:
                data = json.load(f)

            # Should have "samples" key
            assert "samples" in data
            assert isinstance(data["samples"], list)
            assert len(data["samples"]) > 0

            # Each sample should have required fields
            for sample in data["samples"]:
                assert "cycle" in sample
                assert "link_up" in sample
                assert "total_frames" in sample
                assert "total_crc_fails" in sample
                assert "consec_fails" in sample
                assert "consec_passes" in sample


# ─────────────────────────────────────────────────────────────────────────────
# Determinism Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLinkDeterminism:
    """Tests for link monitor determinism."""

    def test_same_seed_produces_same_link_states(self):
        """Test that identical seeds produce identical link state sequences."""
        def run_with_seed(seed: int):
            config = SimConfig.from_args(
                name=f"determinism_{seed}",
                cycles=50,
                cycle_chunks=10,
                seed=seed,
                out_dir=None,
            )

            plant_runner = _create_plant_runner()
            schedule = constant_heater(heater=0.4, workload=0.3)
            link_runner = LinkRunner()

            kernel = CoSimKernel(
                config,
                plant_runner=plant_runner,
                schedule=schedule,
                link_runner=link_runner,
            )
            return kernel.run()

        # Run twice with same seed
        result1 = run_with_seed(12345)
        result2 = run_with_seed(12345)

        # Link states should be identical
        assert len(result1.link_states) == len(result2.link_states)

        for s1, s2 in zip(result1.link_states, result2.link_states):
            assert s1.cycle == s2.cycle
            assert s1.link_up == s2.link_up
            assert s1.total_frames == s2.total_frames
            assert s1.total_crc_fails == s2.total_crc_fails
            assert s1.consec_fails == s2.consec_fails
            assert s1.consec_passes == s2.consec_passes

    def test_different_seeds_may_produce_different_link_states(self):
        """Test that different seeds can produce different outcomes."""
        def run_with_seed(seed: int):
            config = SimConfig.from_args(
                name=f"diff_seed_{seed}",
                cycles=100,
                cycle_chunks=10,
                seed=seed,
                out_dir=None,
            )

            plant_runner = _create_plant_runner()
            # High failure probability scenario
            schedule = constant_heater(heater=0.0, workload=0.5)
            link_runner = LinkRunner()

            kernel = CoSimKernel(
                config,
                plant_runner=plant_runner,
                schedule=schedule,
                link_runner=link_runner,
            )
            return kernel.run()

        # Run with different seeds
        result1 = run_with_seed(111)
        result2 = run_with_seed(222)

        # Get final states
        final1 = result1.link_states[-1]
        final2 = result2.link_states[-1]

        # With different seeds, the random CRC events should differ
        # Check that at least total_crc_fails differs (highly likely)
        # Note: This could theoretically fail with very low probability
        # but with 100 cycles and high failure probability, it's extremely unlikely
        # that both runs produce exactly the same sequence
        assert final1.total_crc_fails != final2.total_crc_fails or \
               final1.link_up != final2.link_up, \
               "Different seeds should produce different results (probabilistic)"


# ─────────────────────────────────────────────────────────────────────────────
# Custom Config Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCustomLinkConfig:
    """Tests for custom LinkMonitorConfig parameters."""

    def test_custom_fails_to_down(self):
        """Test custom fails_to_down threshold with direct LinkRunner."""
        # This test uses LinkRunner directly to ensure deterministic behavior
        # The kernel+plant integration test validates the integration;
        # this test validates the threshold configuration.

        # Custom config: only 2 fails to bring link down
        link_config = LinkMonitorConfig(fails_to_down=2, passes_to_up=8)
        link_runner = LinkRunner(link_config)

        # Send exactly 2 consecutive failures
        for i in range(2):
            event = CrcEvent(cycle=i, chunk_idx=0, crc_fail=True, crc_fail_prob=1.0)
            sample = link_runner.step(event)

        # Link should be down after 2 consecutive failures
        assert sample.link_up is False, \
            f"Link should be down after 2 consecutive fails, got: {sample}"
        assert sample.consec_fails == 2
