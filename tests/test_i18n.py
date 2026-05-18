from app.models import UiLanguage
from app.telegram.i18n import translate_text


def test_translate_text_leaves_isolated_common_korean_tokens():
    text = "예시로 메시지와 모드 토큰을 사용자 지시에 넣습니다"
    assert translate_text(text, UiLanguage.ENGLISH) == text


def test_translate_text_codex_rate_limit_window_labels():
    raw = "- 5시간 한도: 잔여 44%\n- 주간 한도: 잔여 90%"
    out = translate_text(raw, UiLanguage.ENGLISH)
    assert "5-hour limit" in out
    assert "Weekly limit" in out


def test_translate_text_rebase_no_branch_hint_full_sentence():
    raw = (
        "리베이스할 브랜치가 없습니다. /rebase <branch> 로 직접 지정할 수 있습니다."
    )
    out = translate_text(raw, UiLanguage.ENGLISH)
    assert "No branch is available to rebase" in out
    assert "/rebase <branch>" in out
    assert "로 직접" not in out


def test_translate_text_still_replaces_distinct_bot_phrases():
    raw = "작업 접수 완료\n브랜치 확인"
    out = translate_text(raw, UiLanguage.ENGLISH)
    assert "Job accepted" in out
    assert "Branch" in out


def test_translate_text_translates_confirmation_mode_label():
    raw = "- 모드: agent (코드 수정·커밋·push 가능)"
    out = translate_text(raw, UiLanguage.ENGLISH)
    assert out == "- Mode: agent (allows edit, commit, and push)"
