from __future__ import annotations

import subprocess
import tempfile

from app.models import ModelName
from app.monitoring.events import EventLogger

_log = EventLogger("app.git.ai_commit", "git.commit")


class AiCommitBodyGenerator:
    _PROMPT = (
        "You are writing a git commit message.\n"
        "First, output one line: \"title: <concise summary under 72 chars>\"\n"
        "Then output 2-3 bullet points describing what was changed.\n"
        "Focus on WHAT changed, not how.\n\n"
        "Do not copy the raw user request into the title.\n"
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
        model_name: ModelName = ModelName.CLAUDE,
        timeout: int = 30,
    ) -> tuple[str | None, str | None]:
        prompt = self._PROMPT.format(
            instruction=instruction.strip(),
            files=", ".join(changed_files) if changed_files else "(none)",
        )
        argv = self._build_argv(model_name, prompt)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=tmpdir,
                    check=False,
                    shell=False,
                    stdin=subprocess.DEVNULL,
                )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            _log.warning("ai commit generation failed model=%s: %s", model_name.value, exc)
            return None, None

        if result.returncode != 0 or not result.stdout.strip():
            _log.warning(
                "ai commit generation failed model=%s exit=%d stderr=%s",
                model_name.value,
                result.returncode,
                self._preview(result.stderr),
            )
            return None, None

        return self._parse_output(result.stdout)

    @staticmethod
    def _build_argv(model_name: ModelName, prompt: str) -> list[str]:
        argv_by_model: dict[ModelName, list[str]] = {
            ModelName.CLAUDE: ["claude", "-p", prompt, "--dangerously-skip-permissions"],
            ModelName.CODEX: [
                "codex",
                "exec",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                prompt,
            ],
            ModelName.GEMINI: ["gemini", "-p", prompt],
        }
        argv = argv_by_model.get(model_name)
        if argv is None:
            raise ValueError(f"Unsupported model for commit body generation: {model_name}")
        return argv

    @staticmethod
    def _parse_output(stdout: str) -> tuple[str | None, str | None]:
        ai_title: str | None = None
        bullet_lines: list[str] = []
        for line in stdout.strip().splitlines():
            stripped = line.strip()
            if ai_title is None and stripped.startswith("title: "):
                ai_title = stripped[len("title: "):].strip()
            elif stripped.startswith("- "):
                bullet_lines.append(stripped)

        ai_body = "\n".join(bullet_lines) if bullet_lines else None
        return ai_title or None, ai_body

    @staticmethod
    def _preview(text: str, max_length: int = 120) -> str:
        preview = " ".join(text.strip().split())
        if len(preview) <= max_length:
            return preview
        return preview[: max_length - 3].rstrip() + "..."
