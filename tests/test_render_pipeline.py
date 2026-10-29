"""End-to-end rendering without the network.

The edge engine needs Microsoft's endpoint, which makes the interesting part
of the pipeline (chunking, stitching, effect processing) unreachable in a test.
So this file swaps in a tiny local engine that writes a sine wave: the chunk
loop, the concatenation, the cleanup of part files and the DSP chain all run
for real.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from voiceforge import render  # noqa: E402
from voiceforge.project import Project  # noqa: E402


class FakeEngine:
    """Minimal engine: one tone per call, at the requested path."""

    name = "fake"
    extension = ".wav"
    parallel_safe = False

    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    def available(self, reference: str = "") -> tuple[bool, str]:
        return True, ""

    def render(self, text: str, settings: dict, target: Path) -> Path:
        import numpy as np
        import soundfile as sf

        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        rate = 8000
        # 30 ms per character, so a chunk is audibly non-empty.
        frames = max(400, min(8000, len(text) * 24))
        t = np.arange(frames, dtype=np.float32) / rate
        tone = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        sf.write(str(target), tone, rate)
        self.calls.append((text, target))
        return target


class ParallelFakeEngine(FakeEngine):
    """Same tone, but safe to call from several threads at once."""

    parallel_safe = True

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def render(self, text: str, settings: dict, target: Path) -> Path:
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(0.05)
            return super().render(text, settings, target)
        finally:
            with self._lock:
                self.active -= 1


class CorruptOnceEngine(FakeEngine):
    """Writes junk on the first call, real audio after that."""

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def render(self, text: str, settings: dict, target: Path) -> Path:
        self.attempts += 1
        if self.attempts == 1:
            target = Path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"not audio" * 40)
            return target
        return super().render(text, settings, target)


class AlwaysCorruptEngine(FakeEngine):
    def render(self, text: str, settings: dict, target: Path) -> Path:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"still not audio" * 40)
        return target



class Pipe:
    def __init__(self, engine: FakeEngine) -> None:
        self.engine = engine

    def __call__(self, name, root):
        return self.engine


class TestLongFormRender(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine = FakeEngine()
        self._original = render.get_engine
        render.get_engine = Pipe(self.engine)  # type: ignore[assignment]
        self.project = Project.load(self.root)

    def tearDown(self) -> None:
        render.get_engine = self._original  # type: ignore[assignment]
        self.tmp.cleanup()

    def test_short_text_is_one_engine_call(self) -> None:
        path, engine = render.render_text(self.project, "Hello there.",
                                          out="short.wav")
        self.assertEqual(engine, "fake")
        self.assertTrue(path.exists())
        self.assertEqual(len(self.engine.calls), 1)

    def test_long_text_is_chunked_stitched_and_leaves_no_parts(self) -> None:
        text = " ".join(["This sentence is deliberately repeated."] * 60)
        out = self.root / "long.wav"
        path, _ = render.render_text(self.project, text, out=out,
                                     chunk_chars=120)

        self.assertGreater(len(self.engine.calls), 1, "should have split")
        self.assertTrue(path.exists())
        self.assertEqual(path, out)
        parts = list(out.parent.glob(f"{out.stem}.part*"))
        self.assertEqual(parts, [], "temporary chunks must be deleted")

        # The scratch directory is cleaned too; a crash must not slowly fill
        # the data folder with orphaned chunk audio.
        scratch = render.work_dir(self.project)
        self.assertEqual(list(scratch.iterdir()), [])

        # The stitched file is longer than any single chunk.
        import soundfile as sf

        info = sf.info(str(path))
        durations = []
        for _, part in self.engine.calls:
            if part.exists():
                durations.append(sf.info(str(part)).duration)
        self.assertGreater(info.duration, 0.0)

    def test_chunks_never_appear_beside_the_download(self) -> None:
        text = "A line that will be split. " * 20
        out = self.root / "only-one.wav"
        render.render_text(self.project, text, out=out, chunk_chars=100)

        names = sorted(p.name for p in self.root.iterdir() if p.is_file())
        self.assertEqual(names, ["only-one.wav"])

    def test_stale_parts_from_older_builds_are_cleaned(self) -> None:
        old = self.root / "20261025-142250-a-story.part001.mp3"
        old.write_bytes(b"leftover")
        keep = self.root / "my-own.part001.mp3"
        keep.write_bytes(b"user file")
        removed = render.cleanup_partials(self.root)
        self.assertEqual(removed, 1)
        self.assertFalse(old.exists())
        self.assertTrue(keep.exists(), "only VoiceForge's stamped names go")

    def test_progress_reports_parts_characters_and_timings(self) -> None:
        text = " ".join(["Progress is reported for this part."] * 30)
        events: list[dict] = []
        render.render_text(self.project, text, out=self.root / "progress.wav",
                           chunk_chars=120, progress=events.append)
        phases = [event["phase"] for event in events]
        self.assertEqual(phases[0], "prepare")
        self.assertIn("part", phases)
        self.assertIn("part_done", phases)
        self.assertEqual(phases[-1], "done")
        parts = [event for event in events if event["phase"] == "part"]
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(event["parts"] == len(parts) for event in parts))
        done = [event for event in events if event["phase"] == "part_done"]
        self.assertTrue(done)
        self.assertGreater(done[-1]["chars_done"], 0)
        # Fake engines finish instantly, so the recorded time can be 0.0.
        self.assertGreaterEqual(done[-1]["seconds"], 0.0)
        self.assertEqual(done[-1]["chars_done"], done[-1]["total_chars"])

    def test_a_broken_progress_sink_cannot_break_the_render(self) -> None:
        def explode(_event: dict) -> None:
            raise RuntimeError("progress UI died")

        path, _ = render.render_text(
            self.project, "Still renders safely.", out=self.root / "safe.wav",
            progress=explode)
        self.assertTrue(path.exists())

    def test_effect_runs_on_the_stitched_result(self) -> None:
        text = "Chunk one is here. " * 40
        path, _ = render.render_text(self.project, text, out="fx.wav",
                                     chunk_chars=100,
                                     overrides={"effect": "room"})
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 1000)

    def test_empty_text_raises(self) -> None:
        with self.assertRaises(ValueError):
            render.render_text(self.project, "   ")

    # -- adaptive / parallel ----------------------------------------------
    def test_outcome_carries_real_file_metadata(self) -> None:
        outcome = render.render_text(self.project, "Metadata please.",
                                     out="meta.wav")
        self.assertIsInstance(outcome.meta, dict)
        self.assertEqual(outcome.path, outcome[0])
        self.assertEqual(outcome.engine, "fake")
        self.assertEqual(outcome.meta["format"], "wav")
        self.assertGreater(outcome.meta["bytes"], 0)
        self.assertGreater(outcome.meta["duration"], 0.0)
        self.assertEqual(outcome.meta["sample_rate"], 8000)
        self.assertEqual(outcome.meta["parts"], 1)

    def test_parallel_parts_use_several_workers_and_report_them(self) -> None:
        engine = ParallelFakeEngine()
        render.get_engine = Pipe(engine)  # type: ignore[assignment]
        text = " ".join(["Parallel rendering keeps the wait short."] * 60)
        events: list[dict] = []

        outcome = render.render_text(
            self.project, text, out=self.root / "parallel.wav",
            chunk_chars=120, adaptive=False, workers=3,
            progress=events.append)

        self.assertGreater(len(engine.calls), 4)
        self.assertGreaterEqual(outcome.meta["workers"], 2,
                                "more than one part should be in flight")
        self.assertFalse(outcome.meta["adaptive"])
        self.assertEqual(outcome.meta["parts"], len(engine.calls))
        self.assertLessEqual(engine.peak, 3, "never above the fixed budget")

        done = [event for event in events if event["phase"] == "part_done"]
        self.assertEqual(len(done), outcome.meta["parts"])
        self.assertTrue(all(event["workers"] >= 1 for event in events
                            if "workers" in event))
        self.assertGreater(done[-1]["chars_done"], 0)
        self.assertEqual(done[-1]["chars_done"], done[-1]["total_chars"])

    def test_one_part_at_a_time_skips_the_thread_pool(self) -> None:
        engine = ParallelFakeEngine()
        render.get_engine = Pipe(engine)  # type: ignore[assignment]
        text = " ".join(["Sequential is still supported."] * 40)
        outcome = render.render_text(
            self.project, text, out=self.root / "serial.wav",
            chunk_chars=120, adaptive=False, workers=1)
        self.assertEqual(engine.peak, 1)
        self.assertEqual(outcome.meta["workers"], 1)

    def test_a_corrupt_part_is_deleted_and_retried_once(self) -> None:
        engine = CorruptOnceEngine()
        render.get_engine = Pipe(engine)  # type: ignore[assignment]
        outcome = render.render_text(self.project, "Please render me.",
                                     out="retried.wav")
        self.assertEqual(engine.attempts, 2, "one retry, then success")
        self.assertTrue(outcome.path.exists())
        self.assertGreater(outcome.meta["bytes"], 100)

    def test_a_permanently_corrupt_part_writes_nothing(self) -> None:
        engine = AlwaysCorruptEngine()
        render.get_engine = Pipe(engine)  # type: ignore[assignment]
        target = self.root / "never.wav"
        with self.assertRaises(render.EngineError) as caught:
            render.render_text(self.project, "This will not work.",
                               out=target)
        self.assertIn("corrupt", str(caught.exception).lower())
        self.assertFalse(target.exists())
        leftovers = [p.name for p in self.root.iterdir()
                     if ".vf-" in p.name or p.suffix == ".part"]
        self.assertEqual(leftovers, [])



if __name__ == "__main__":
    unittest.main()
