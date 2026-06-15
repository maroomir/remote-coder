import sys
from pathlib import Path

from app.ai.base import BaseCliRunner, RunnerInput
from app.monitoring.events import EventLogger


class _PythonRunner(BaseCliRunner):
    name = "python"
    _log = EventLogger("tests.base_runner", "tests.base_runner")

    def build_argv(self, runner_input: RunnerInput) -> list[str]:
        return [
            sys.executable,
            "-c",
            (
                "import sys, time; "
                "print('out 1', flush=True); "
                "print('err 1', file=sys.stderr, flush=True); "
                "time.sleep(0.01); "
                "print('out 2', flush=True)"
            ),
        ]


def test_base_runner_streams_output_to_callback():
    chunks: list[tuple[str, str]] = []

    result = _PythonRunner().run(
        RunnerInput(
            instruction="x",
            cwd=Path("."),
            timeout_seconds=5,
            output_callback=lambda stream, chunk: chunks.append((stream, chunk)),
        )
    )

    assert result.exit_code == 0
    assert result.stdout == "out 1\nout 2\n"
    assert result.stderr == "err 1\n"
    assert ("stdout", "out 1\n") in chunks
    assert ("stdout", "out 2\n") in chunks
    assert ("stderr", "err 1\n") in chunks
