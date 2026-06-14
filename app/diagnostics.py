from __future__ import annotations

import shutil

from pydantic import BaseModel

from app import tunnel

AI_CLI_TOOLS = ("claude", "codex", "gemini")
GITHUB_CLI_TOOL = "gh"


class AiCliStatus(BaseModel):
    name: str
    installed: bool


class PrerequisitesReport(BaseModel):
    ngrok_ok: bool
    ngrok_detail: str
    ai_clis: list[AiCliStatus]
    github_cli: AiCliStatus


def check_prerequisites() -> PrerequisitesReport:
    try:
        tunnel.ensure_ngrok_available()
        tunnel.ensure_ngrok_configured()
        ngrok_ok = True
        ngrok_detail = ""
    except tunnel.TunnelError as exc:
        ngrok_ok = False
        ngrok_detail = str(exc)

    ai_clis = [
        AiCliStatus(name=tool, installed=shutil.which(tool) is not None)
        for tool in AI_CLI_TOOLS
    ]
    github_cli = AiCliStatus(
        name=GITHUB_CLI_TOOL,
        installed=shutil.which(GITHUB_CLI_TOOL) is not None,
    )
    return PrerequisitesReport(
        ngrok_ok=ngrok_ok,
        ngrok_detail=ngrok_detail,
        ai_clis=ai_clis,
        github_cli=github_cli,
    )
