"""Regression + characterization tests for app.ai.usage token/model parsing.

Tester 3 (AI Runners & Git Automation). Token usage is extracted once from the
concatenated `stdout + "\\n" + stderr` of a runner (see
app.jobs.result_writer.save_runner_log) and stored on the job, then surfaced to
the user (F8) and saved to conversation memory.

FIXED: `_extract_token_metrics` used to *sum* every match for a label across all
patterns and lines, so the same metric reported twice -- in two syntactic forms,
or mirrored on stdout and stderr -- inflated the count. It now keeps the largest
value per label; these tests guard against a regression.
"""

from __future__ import annotations

from app.ai.usage import extract_runner_usage, format_token_usage


def test_extract_runner_usage_reads_model_and_tokens():
    text = (
        "actual model: Claude Sonnet 4.5\n"
        "input tokens: 1200\n"
        "output tokens: 300\n"
    )
    usage = extract_runner_usage(text)

    assert usage.actual_model == "Claude Sonnet 4.5"
    assert usage.token_usage == {"input": 1200, "output": 300}
    assert usage.total_tokens == 1500


def test_extract_runner_usage_normalizes_prompt_completion_labels():
    text = "prompt_tokens: 50\ncompletion_tokens: 25\ntotal_tokens: 75"
    usage = extract_runner_usage(text)

    assert usage.token_usage == {"input": 50, "output": 25, "total": 75}
    assert usage.total_tokens == 75


def test_total_tokens_prefers_explicit_total_over_sum():
    # cache read/write are excluded from the implicit sum.
    usage = extract_runner_usage(
        "input tokens: 100\noutput tokens: 40\ncache read tokens: 999\ntotal tokens: 140"
    )
    assert usage.total_tokens == 140


def test_format_token_usage_renders_total_with_details():
    rendered = format_token_usage({"input": 1200, "output": 300})
    assert rendered == "1,500 (input=1,200, output=300)"


def test_duplicate_metric_in_two_syntaxes_is_not_double_counted():
    # A single response that prints both a human summary and a structured field
    # for the SAME 120 prompt tokens should report 120, not 240.
    usage = extract_runner_usage("prompt tokens: 120\nprompt_tokens: 120")
    assert usage.token_usage.get("input") == 120


def test_same_total_on_stdout_and_stderr_is_not_double_counted():
    stdout = "total tokens: 1234"
    stderr = "total tokens: 1234"
    usage = extract_runner_usage(f"{stdout}\n{stderr}")
    assert usage.token_usage.get("total") == 1234
