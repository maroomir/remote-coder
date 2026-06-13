from app.telegram.lists import render_command_list, render_labeled_list


def test_render_labeled_list_keeps_full_values():
    value = "/very/long/path/" + "x" * 80

    output = render_labeled_list([("root", value)])

    assert output == f"- root: {value}"


def test_render_labeled_list_indents_multiline_values():
    output = render_labeled_list([("Output", "first\nsecond")])

    assert output == "- Output: first\n  second"


def test_render_command_list_uses_signature_and_description_lines():
    output = render_command_list(
        [("/model", "<claude|codex|gemini>", "Change the default model")]
    )

    assert output == (
        "- /model <claude|codex|gemini>\n"
        "  Change the default model"
    )
