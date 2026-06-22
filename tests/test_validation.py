import sys
from pathlib import Path

from app.jobs.validation import run_validation_command


def test_passing_command_reports_passed(tmp_path: Path):
    result = run_validation_command(f"{sys.executable} -c \"import sys; sys.exit(0)\"", tmp_path, 30)
    assert result.passed
    assert result.exit_code == 0
    assert not result.timed_out


def test_failing_command_reports_not_passed_with_output(tmp_path: Path):
    result = run_validation_command(
        f"{sys.executable} -c \"import sys; sys.stderr.write('boom'); sys.exit(2)\"",
        tmp_path,
        30,
    )
    assert not result.passed
    assert result.exit_code == 2
    assert "boom" in result.output_summary


def test_missing_executable_reports_not_passed(tmp_path: Path):
    result = run_validation_command("definitely-not-a-real-binary-xyz", tmp_path, 30)
    assert not result.passed
    assert result.exit_code is None
    assert "not found" in result.output_summary


def test_timeout_reports_not_passed_and_timed_out(tmp_path: Path):
    result = run_validation_command(
        f"{sys.executable} -c \"import time; time.sleep(5)\"", tmp_path, 1
    )
    assert not result.passed
    assert result.timed_out
    assert "timed out" in result.output_summary


def test_empty_command_reports_not_passed(tmp_path: Path):
    result = run_validation_command("   ", tmp_path, 30)
    assert not result.passed
    assert result.exit_code is None


def test_unparseable_command_reports_not_passed(tmp_path: Path):
    # Unbalanced quote makes shlex fail; the gate must treat it as a failure, not crash.
    result = run_validation_command('echo "unterminated', tmp_path, 30)
    assert not result.passed
    assert "parse" in result.output_summary.lower()
