from app.diagnostics import check_prerequisites
from app.tunnel import TunnelError


def test_check_prerequisites_all_ok(monkeypatch) -> None:
    monkeypatch.setattr("app.tunnel.ensure_ngrok_available", lambda: "/usr/bin/ngrok")
    monkeypatch.setattr("app.tunnel.ensure_ngrok_configured", lambda: None)
    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/" + name if name == "claude" else None
    )

    report = check_prerequisites()

    assert report.ngrok_ok is True
    assert report.ngrok_detail == ""
    installed = {cli.name: cli.installed for cli in report.ai_clis}
    assert installed == {"claude": True, "codex": False, "gemini": False, "ollama": False}
    assert report.github_cli.name == "gh"
    assert report.github_cli.installed is False


def test_check_prerequisites_ngrok_not_configured(monkeypatch) -> None:
    def _raise() -> None:
        raise TunnelError("ngrok AuthToken이 설정되지 않았습니다.")

    monkeypatch.setattr("app.tunnel.ensure_ngrok_available", lambda: "/usr/bin/ngrok")
    monkeypatch.setattr("app.tunnel.ensure_ngrok_configured", _raise)
    monkeypatch.setattr("shutil.which", lambda name: None)

    report = check_prerequisites()

    assert report.ngrok_ok is False
    assert "AuthToken" in report.ngrok_detail
    assert all(not cli.installed for cli in report.ai_clis)
    assert report.github_cli.installed is False


def test_check_prerequisites_reports_github_cli(monkeypatch) -> None:
    monkeypatch.setattr("app.tunnel.ensure_ngrok_available", lambda: "/usr/bin/ngrok")
    monkeypatch.setattr("app.tunnel.ensure_ngrok_configured", lambda: None)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/gh" if name == "gh" else None)

    report = check_prerequisites()

    assert report.github_cli.name == "gh"
    assert report.github_cli.installed is True
