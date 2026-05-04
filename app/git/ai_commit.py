from __future__ import annotations

import subprocess
import tempfile

from app.monitoring.events import EventLogger

_log = EventLogger("app.git.ai_commit", "git.commit")


class AiCommitBodyGenerator:
    """변경된 파일과 지시 내용을 바탕으로 AI가 커밋 메시지 title과 body를 생성한다."""

    _PROMPT = (
        "You are writing a git commit message.\n"
        "First, output one line: \"title: <concise summary under 72 chars>\"\n"
        "Then output 2-3 bullet points describing what was changed.\n"
        "Focus on WHAT changed, not how.\n\n"
        "User request: {instruction}\n"
        "Changed files: {files}\n\n"
        "Output format (exactly):\n"
        "title: <title here>\n"
        "- <bullet 1>\n"
        "- <bullet 2>"
    )

    def generate(
        self,
        instruction: str,
        changed_files: list[str],
        timeout: int = 30,
    ) -> tuple[str | None, str | None]:
        """AI가 생성한 (title, body) 튜플을 반환. 실패 시 (None, None)."""
        prompt = self._PROMPT.format(
            instruction=instruction.strip(),
            files=", ".join(changed_files) if changed_files else "(none)",
        )
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run(
                    ["claude", "-p", prompt, "--dangerously-skip-permissions"],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=tmpdir,
                    check=False,
                    shell=False,
                )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            _log.warning("ai commit generation failed: %s", exc)
            return None, None

        if result.returncode != 0 or not result.stdout.strip():
            _log.warning("ai commit generation failed exit=%d", result.returncode)
            return None, None

        ai_title: str | None = None
        bullet_lines: list[str] = []
        for line in result.stdout.strip().splitlines():
            stripped = line.strip()
            if ai_title is None and stripped.startswith("title: "):
                ai_title = stripped[len("title: "):].strip()
            elif stripped.startswith("- "):
                bullet_lines.append(stripped)

        ai_body = "\n".join(bullet_lines) if bullet_lines else None
        return ai_title or None, ai_body
