from app.jobs.diff_review import build_diff_review_summary


def test_files_are_impact_ranked_by_churn():
    summary = build_diff_review_summary(
        [
            ("app/small.py", 1, 1),
            ("app/big.py", 100, 50),
            ("app/medium.py", 10, 5),
        ]
    )

    assert [stat.path for stat in summary.files] == ["app/big.py", "app/medium.py", "app/small.py"]


def test_totals_sum_added_and_deleted():
    summary = build_diff_review_summary([("a.py", 3, 2), ("b.py", 7, 1)])

    assert summary.total_added == 10
    assert summary.total_deleted == 3
    assert summary.file_count == 2


def test_lockfile_is_flagged_as_risk():
    summary = build_diff_review_summary([("poetry.lock", 50, 10)])

    assert summary.risk_flags == ["poetry.lock: dependency lockfile changed"]


def test_migration_path_is_flagged():
    summary = build_diff_review_summary([("app/db/migrations/0002_add.py", 20, 0)])

    assert any("database migration" in flag for flag in summary.risk_flags)


def test_large_deletion_is_flagged():
    summary = build_diff_review_summary([("app/legacy.py", 0, 150)])

    assert any("large deletion (150 lines)" in flag for flag in summary.risk_flags)


def test_shared_utility_is_flagged_but_test_helpers_are_not():
    summary = build_diff_review_summary(
        [
            ("app/utils.py", 5, 1),
            ("tests/utils.py", 5, 1),
        ]
    )

    flags = "\n".join(summary.risk_flags)
    assert "app/utils.py: shared utility (downstream impact)" in flags
    assert "tests/utils.py" not in flags


def test_binary_file_reports_none_counts_and_no_churn():
    summary = build_diff_review_summary([("logo.png", None, None)])

    stat = summary.files[0]
    assert stat.is_binary
    assert stat.churn == 0
    assert summary.total_added == 0
    assert summary.total_deleted == 0


def test_listed_files_are_capped():
    raw = [(f"file{i}.py", i, 0) for i in range(20)]

    summary = build_diff_review_summary(raw, max_listed_files=3)

    assert len(summary.files) == 3
    # Cap applies to the listed files, but totals still reflect every file.
    assert summary.total_added == sum(range(20))


def test_risk_flags_are_capped_with_overflow_marker():
    raw = [(f"app/db/migrations/{i:04d}.py", 5, 0) for i in range(20)]

    summary = build_diff_review_summary(raw, max_listed_files=3)

    assert len(summary.risk_flags) == 4  # 3 flags + 1 overflow marker
    assert summary.risk_flags[-1] == "… (+17 more)"


def test_risk_flags_are_deduplicated():
    summary = build_diff_review_summary(
        [
            ("poetry.lock", 1, 0),
            ("poetry.lock", 2, 0),
        ]
    )

    assert summary.risk_flags == ["poetry.lock: dependency lockfile changed"]
