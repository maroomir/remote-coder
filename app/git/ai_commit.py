from __future__ import annotations

import subprocess
import tempfile

from app.monitoring.events import EventLogger

_log = EventLogger("app.git.ai_commit", "git.commit")


class AiCommitBodyGenerator:
    """변경된 파일과 지시 내용을 바탕으로 AI가 커밋 메시지 body를 생성한다."""

    _PROMPT = (
        "You are writing a git commit message body.\n"
        "Write 2-3 concise bullet points describing what was changed.\n"
        "Focus on WHAT changed, not how.\n\n"
        "User request: {instruction}\n"
        "Changed files: {files}\n\n"
        "Output ONLY bullet points starting with '- '. Nothing else."
    )

    def generate(
        self,
        instruction: str,
        changed_files: list[str],
        timeout: int = 30,
    ) -> str | None:
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
            _log.warning("ai commit body generation failed: %s", exc)
            return None

        if result.returncode != 0 or not result.stdout.strip():
            _log.warning("ai commit body generation failed exit=%d", result.returncode)
            return None

        lines = [
            line.strip()
            for line in result.stdout.strip().splitlines()
            if line.strip().startswith("- ")
        ]
        return "\n".join(lines) if lines else None
