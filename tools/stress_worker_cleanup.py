"""Windows-local stress test for recording-session cleanup.

Runs the recorder worker runtime repeatedly through ChangeInput / Shutdown and
reports any iteration that leaves a temporary segment file or an uncleaned
session directory behind.  This complements (and does not replace) the pytest
regression tests.

Usage::

    uv run python tools/stress_worker_cleanup.py --mode change-input --iterations 100
    uv run python tools/stress_worker_cleanup.py --mode shutdown --iterations 100
    uv run python tools/stress_worker_cleanup.py --mode combined --iterations 100
"""

import argparse
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from fake_worker_input import ScriptedInputFactory, WorkerHarness  # noqa: E402

from quickreplay.input.models import CameraInputConfig, NdiInputConfig  # noqa: E402
from quickreplay.recording.commands import ChangeInput, Shutdown, StartRecording  # noqa: E402
from quickreplay.recording.events import RecordingMetricsUpdated  # noqa: E402
from quickreplay.recording.models import WorkerState  # noqa: E402
from quickreplay.worker.settings import RecorderWorkerSettings  # noqa: E402


def _settings(tmp: Path) -> RecorderWorkerSettings:
    return RecorderWorkerSettings(
        working_directory=tmp,
        metrics_interval_ns=20_000_000,
        stream_start_timeout_ns=2_000_000_000,
        video_queue_capacity=4096,
        audio_queue_capacity=4096,
    )


def _start(harness: WorkerHarness, factory: ScriptedInputFactory) -> None:
    harness.start()
    harness.wait_state(WorkerState.IDLE)
    harness.send(StartRecording(NdiInputConfig("fake")))
    harness.wait_state(WorkerState.RECORDING)
    harness.wait_event(
        RecordingMetricsUpdated,
        predicate=lambda event: event.metrics.captured_video_frames >= factory.video_frames,
    )


def _check_cleanup(tmp: Path, *, expect_session_dirs: int) -> str:
    leftover = [str(path.relative_to(tmp)) for path in tmp.rglob("*.tmp.mkv")]
    buffer_root = tmp / "buffer"
    directories = (
        [entry for entry in buffer_root.iterdir() if entry.is_dir()] if buffer_root.exists() else []
    )
    problems = []
    if leftover:
        problems.append(f"tmp files remain: {leftover}")
    if len(directories) != expect_session_dirs:
        problems.append(f"session dirs={len(directories)} expected={expect_session_dirs}")
    return "; ".join(problems)


def _change_input(iterations: int) -> int:
    failures = 0
    for index in range(iterations):
        tmp = Path(tempfile.mkdtemp(prefix="qr_stress_ci_"))
        factory = ScriptedInputFactory(duration_ns=1_000_000_000)
        harness = WorkerHarness(_settings(tmp), input_factory=factory)
        problem = ""
        try:
            _start(harness, factory)
            harness.send(ChangeInput(uuid4(), CameraInputConfig("cam", 0, "any")))
            harness.wait_state(WorkerState.RECORDING, timeout=5.0)
            problem = _check_cleanup(tmp, expect_session_dirs=1)
        except AssertionError as exc:
            problem = str(exc)
        finally:
            try:
                harness.shutdown()
            except Exception:  # noqa: BLE001 - best effort
                pass
        if problem:
            failures += 1
            print(f"change-input {index}: FAIL {problem}", flush=True)
    return failures


def _shutdown(iterations: int) -> int:
    failures = 0
    for index in range(iterations):
        tmp = Path(tempfile.mkdtemp(prefix="qr_stress_sd_"))
        factory = ScriptedInputFactory(duration_ns=2_000_000_000)
        harness = WorkerHarness(_settings(tmp), input_factory=factory)
        problem = ""
        try:
            harness.start()
            harness.wait_state(WorkerState.IDLE)
            harness.send(StartRecording(NdiInputConfig("fake")))
            harness.wait_state(WorkerState.RECORDING)
            harness.send(Shutdown())
            harness.wait_state(WorkerState.SHUTTING_DOWN)
            harness.join(timeout=10.0)
            problem = _check_cleanup(tmp, expect_session_dirs=0)
        except AssertionError as exc:
            problem = str(exc)
        if problem:
            failures += 1
            print(f"shutdown {index}: FAIL {problem}", flush=True)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", choices=("change-input", "shutdown", "combined"), default="combined"
    )
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()

    failures = 0
    if args.mode in ("change-input", "combined"):
        failures += _change_input(args.iterations)
    if args.mode in ("shutdown", "combined"):
        failures += _shutdown(args.iterations)

    total = args.iterations * (2 if args.mode == "combined" else 1)
    print(f"iterations={total} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
