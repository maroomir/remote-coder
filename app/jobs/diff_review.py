from __future__ import annotations

import re

from pydantic import BaseModel, Field

# Heuristic risk rules. Kept deliberately few and high-confidence so the review card stays
# signal-rich on mobile rather than flagging every file. Each rule maps a file path to a short,
# human-readable reason a reviewer should look closer before trusting the change.

_LOCKFILE_NAMES = frozenset(
    {
        "poetry.lock",
        "uv.lock",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "cargo.lock",
        "gemfile.lock",
        "composer.lock",
        "go.sum",
        "pdm.lock",
    }
)

_MIGRATION_PATH = re.compile(r"(^|/)(migrations?|alembic/versions)(/|$)", re.IGNORECASE)
_SHARED_UTIL_PATH = re.compile(r"(^|/)(utils?|helpers?|common|shared|lib)(/|\.)", re.IGNORECASE)
_TEST_PATH = re.compile(r"(^|/)(tests?|spec)(/|$)|(^|/)test_|_test\.|\.spec\.|\.test\.", re.IGNORECASE)

_LARGE_DELETION_THRESHOLD = 100


class FileDiffStat(BaseModel):
    path: str
    added: int | None = None
    deleted: int | None = None

    @property
    def is_binary(self) -> bool:
        return self.added is None or self.deleted is None

    @property
    def churn(self) -> int:
        return (self.added or 0) + (self.deleted or 0)


class DiffReviewSummary(BaseModel):
    files: list[FileDiffStat] = Field(default_factory=list)
    total_added: int = 0
    total_deleted: int = 0
    risk_flags: list[str] = Field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.files)


def _classify_risk(stat: FileDiffStat) -> str | None:
    name = stat.path.rsplit("/", 1)[-1].lower()
    if name in _LOCKFILE_NAMES:
        return "dependency lockfile changed"
    if _MIGRATION_PATH.search(stat.path):
        return "database migration"
    if (stat.deleted or 0) >= _LARGE_DELETION_THRESHOLD:
        return f"large deletion ({stat.deleted} lines)"
    if _SHARED_UTIL_PATH.search(stat.path) and not _TEST_PATH.search(stat.path):
        return "shared utility (downstream impact)"
    return None


def build_diff_review_summary(
    raw_stats: list[tuple[str, int | None, int | None]],
    *,
    max_listed_files: int = 8,
) -> DiffReviewSummary:
    """Turn raw `git diff --numstat` rows into a mobile-friendly review summary.

    Files are impact-ranked by churn (added + deleted) so the most consequential edits surface
    first. Risk flags are collected from a small high-confidence ruleset and deduplicated to keep
    the card terse.
    """
    stats = [FileDiffStat(path=path, added=added, deleted=deleted) for path, added, deleted in raw_stats]
    stats.sort(key=lambda stat: stat.churn, reverse=True)

    total_added = sum(stat.added or 0 for stat in stats)
    total_deleted = sum(stat.deleted or 0 for stat in stats)

    risk_flags: list[str] = []
    seen: set[str] = set()
    for stat in stats:
        reason = _classify_risk(stat)
        if reason is None:
            continue
        flag = f"{stat.path}: {reason}"
        if flag not in seen:
            seen.add(flag)
            risk_flags.append(flag)

    # Cap flags so a sweeping change (e.g. dozens of migrations) cannot bury the card in noise;
    # the goal is a few high-signal warnings on mobile, not an exhaustive audit.
    truncated_flags = risk_flags[:max_listed_files]
    if len(risk_flags) > max_listed_files:
        truncated_flags.append(f"… (+{len(risk_flags) - max_listed_files} more)")

    return DiffReviewSummary(
        files=stats[:max_listed_files],
        total_added=total_added,
        total_deleted=total_deleted,
        risk_flags=truncated_flags,
    )
