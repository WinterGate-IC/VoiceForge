"""The adaptive worker governor, with injected machine readings."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voiceforge import resources  # noqa: E402


def snapshot(cpu: float = 10.0, memory: float = 30.0,
             available_mb: float = 8192.0, cores: int = 8,
             age: float = 0.0) -> resources.Snapshot:
    return resources.Snapshot(
        cpu_percent=cpu,
        memory_percent=memory,
        available_mb=available_mb,
        total_mb=16384.0,
        cores=cores,
        load1=0.1,
        taken_at=time.monotonic() - age,
    )


class TestChooseWorkers(unittest.TestCase):
    def test_automatic_uses_more_than_one_on_a_healthy_machine(self) -> None:
        self.assertEqual(
            resources.choose_workers(20, 0, True, snapshot()), 4)
        self.assertEqual(
            resources.choose_workers(20, 0, True, snapshot(cores=2)), 2)

    def test_manual_setting_is_honoured_even_under_load(self) -> None:
        hot = snapshot(cpu=99.0, memory=98.0, available_mb=64.0)
        self.assertEqual(resources.choose_workers(50, 5, True, hot), 5)
        self.assertEqual(resources.choose_workers(50, 8, True, hot), 8)

    def test_manual_setting_is_capped_by_parts_and_the_ceiling(self) -> None:
        self.assertEqual(resources.choose_workers(2, 6, True, snapshot()), 2)
        self.assertEqual(resources.choose_workers(999, 99, True, snapshot()),
                         resources.MAX_WORKERS)

    def test_adaptive_off_means_one_part_at_a_time(self) -> None:
        self.assertEqual(resources.choose_workers(20, 0, False, snapshot()), 1)

    def test_hot_cpu_or_low_memory_drops_automatic_to_one(self) -> None:
        self.assertEqual(
            resources.choose_workers(20, 0, True, snapshot(cpu=95.0)), 1)
        self.assertEqual(
            resources.choose_workers(
                20, 0, True, snapshot(available_mb=120.0)), 1)
        self.assertEqual(
            resources.choose_workers(20, 0, True, snapshot(memory=96.0)), 1)

    def test_warm_machine_keeps_the_load_light(self) -> None:
        self.assertLessEqual(
            resources.choose_workers(20, 0, True, snapshot(cpu=78.0)), 2)
        self.assertLessEqual(
            resources.choose_workers(
                20, 0, True, snapshot(available_mb=600.0)), 2)


class TestGovernor(unittest.TestCase):
    def test_status_fields_are_ready_for_the_progress_payload(self) -> None:
        governor = resources.Governor(
            10, 0, True, snapshot_fn=lambda: snapshot())
        fields = governor.status_fields()
        for key in ("workers", "max_workers", "worker_note", "adaptive"):
            self.assertIn(key, fields)
        self.assertEqual(fields["workers"], 4)
        self.assertTrue(fields["adaptive"])

    def test_a_failed_part_halves_the_budget_and_then_recovers(self) -> None:
        governor = resources.Governor(
            10, 0, True, snapshot_fn=lambda: snapshot())
        self.assertEqual(governor.limit(), 4)

        notice = governor.observe(False)
        self.assertEqual(governor.limit(), 2)
        self.assertIn("failed", notice.lower())

        governor.observe(False)
        self.assertEqual(governor.limit(), 1)

        # Three healthy parts in a row step it back up.
        self.assertEqual(governor.observe(True), "")
        self.assertEqual(governor.observe(True), "")
        ramp = governor.observe(True)
        self.assertEqual(governor.limit(), 2)
        self.assertIn("stable", ramp.lower())

    def test_memory_pressure_slows_down_with_an_explanation(self) -> None:
        # Start with a slightly stale reading so the first finished part takes
        # a fresh sample (production samples at most once every 1.5 seconds).
        state = {"snap": snapshot(age=5.0)}
        governor = resources.Governor(
            10, 0, True, snapshot_fn=lambda: state["snap"])
        self.assertEqual(governor.limit(), 4)

        state["snap"] = snapshot(memory=95.0, available_mb=200.0)
        notice = governor.observe(True)
        self.assertLess(governor.limit(), 4)
        self.assertIn("memory", notice.lower())

    def test_fixed_budget_is_never_changed_by_pressure(self) -> None:
        governor = resources.Governor(
            10, 3, True, snapshot_fn=lambda: snapshot(memory=99.0))
        self.assertEqual(governor.limit(), 3)
        for _ in range(4):
            self.assertEqual(governor.observe(False), "")
        self.assertEqual(governor.limit(), 3)

    def test_adaptive_off_reports_one_and_does_not_ramp(self) -> None:
        governor = resources.Governor(
            10, 0, False, snapshot_fn=lambda: snapshot())
        self.assertEqual(governor.limit(), 1)
        for _ in range(5):
            governor.observe(True)
        self.assertEqual(governor.limit(), 1)
        self.assertIn("off", governor.reason().lower())

    def test_a_failing_sampler_is_survived(self) -> None:
        def broken() -> resources.Snapshot:
            raise RuntimeError("no /proc here")

        governor = resources.Governor(10, 0, True, snapshot_fn=broken)
        self.assertGreaterEqual(governor.limit(), 1)
        self.assertIn("workers", governor.status_fields())

    def test_describe_mentions_cores_and_memory(self) -> None:
        text = resources.describe(snapshot())
        self.assertIn("core", text)
        self.assertIn("memory", text)
        self.assertIn("CPU", text)


if __name__ == "__main__":
    unittest.main()
