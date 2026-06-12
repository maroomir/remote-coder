from app.telegram.tables import (
    TABLE_CLOSE,
    TABLE_OPEN,
    display_width,
    pad_to_width,
    render_table,
)


def test_display_width_ascii_one_per_char():
    assert display_width("abc") == 3
    assert display_width("") == 0


def test_display_width_hangul_two_per_char():
    assert display_width("가나다") == 6


def test_display_width_emoji_counts_as_wide():
    assert display_width("🎉") == 2


def test_display_width_ignores_combining_marks():
    # Decomposed form: 'e' + combining acute
    assert display_width("é") == 1


def test_pad_to_width_pads_right_side():
    assert pad_to_width("abc", 6) == "abc   "


def test_pad_to_width_pads_left_when_requested():
    assert pad_to_width("abc", 5, side="right") == "  abc"


def test_pad_to_width_keeps_string_when_already_wide_enough():
    assert pad_to_width("abc", 3) == "abc"


def test_render_table_wraps_with_sentinels():
    out = render_table([("a", "b")], headers=("k", "v"))
    lines = out.split("\n")
    assert lines[0] == TABLE_OPEN
    assert lines[-1] == TABLE_CLOSE


def test_render_table_aligns_two_columns():
    out = render_table(
        [("Project", "remote"), ("Model", "claude")],
        headers=("metric", "value"),
    )
    body = out.split("\n")[1:-1]
    assert body[0] == "metric   value"
    assert body[1] == "-------  ------"
    assert body[2] == "Project  remote"
    assert body[3] == "Model    claude"


def test_render_table_truncates_last_column_when_too_wide():
    long_value = "x" * 40
    out = render_table([("k", long_value)])
    body_line = out.split("\n")[1]
    assert body_line.endswith("...")
    assert len(body_line.rstrip()) <= 80


def test_render_table_respects_min_widths_for_translation_stability():
    out = render_table(
        [("프로젝트", "remote")],
        headers=("metric", "value"),
        min_widths=(10, 10),
    )
    body = out.split("\n")[1:-1]
    assert body[2].startswith("프로젝트")
    prefix_before_value = body[2].split("remote", 1)[0]
    assert display_width(prefix_before_value) >= 10
