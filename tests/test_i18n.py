from app.models import UiLanguage
from app.telegram.i18n import translate_button_label, translate_text


def test_translate_text_leaves_english_unchanged():
    text = "Model provider selected.\n\n- Default model: codex"
    assert translate_text(text, UiLanguage.ENGLISH) == text


def test_nav_labels_localize_to_korean():
    assert translate_button_label("‹ Back", UiLanguage.KOREAN) == "‹ 뒤로"
    assert translate_button_label("✖ Close", UiLanguage.KOREAN) == "✖ 닫기"
    assert translate_text("Closed.", UiLanguage.KOREAN) == "닫았습니다."


def test_translate_text_codex_rate_limit_window_labels():
    raw = "- 5-hour limit: remaining 44%\n- Weekly limit: remaining 90%"
    out = translate_text(raw, UiLanguage.KOREAN)
    assert "5시간 한도" in out
    assert "주간 한도" in out


def test_translate_text_rebase_no_branch_hint_full_sentence():
    raw = (
        "No branch is available to rebase. Specify one with /rebase <branch>."
    )
    out = translate_text(raw, UiLanguage.KOREAN)
    assert "리베이스할 브랜치가 없습니다" in out
    assert "/rebase <branch>" in out
    assert "Specify one" not in out


def test_translate_text_still_replaces_distinct_bot_phrases():
    raw = "Job accepted\nBranch"
    out = translate_text(raw, UiLanguage.KOREAN)
    assert "작업 접수 완료" in out
    assert "브랜치 확인" in out


def test_translate_text_translates_confirmation_mode_label():
    raw = "- Mode: agent (allows edit, commit, and push)"
    out = translate_text(raw, UiLanguage.KOREAN)
    assert out == "- 모드: agent (코드 수정·커밋·push 가능)"


def test_translate_text_translates_model_provider_detail_prompt():
    raw = "Model provider selected.\n\n- Default model: codex\n- Choose a specific model."
    out = translate_text(raw, UiLanguage.KOREAN)
    assert out == "모델 제공자가 선택되었습니다.\n\n- 기본 모델: codex\n- 세부 모델을 선택하세요."


def test_translate_text_preserves_help_list_layout():
    raw = "Commands:\n- /model <claude|codex|gemini>\n  Change the default model"

    out = translate_text(raw, UiLanguage.KOREAN)

    assert out == "명령어 목록:\n- /model <claude|codex|gemini>\n  기본 모델 변경"


def test_translate_text_localizes_monitor_list_labels_and_headings():
    raw = (
        "Branch monitor\n"
        "- Project: remote-coder\n"
        "- Current checkout: main\n\n"
        "Local branches\n"
        "- main"
    )

    out = translate_text(raw, UiLanguage.KOREAN)

    assert "브랜치 모니터" in out
    assert "- 프로젝트: remote-coder" in out
    assert "- 현재 checkout: main" in out
    assert "로컬 브랜치\n- main" in out
