from __future__ import annotations

from pathlib import Path

WORKFLOW = (
    Path(__file__).parents[1] / ".github" / "workflows" / "ci-pipeline.yml"
).read_text(encoding="utf-8")


def test_ci_requires_tests_when_source_code_changes() -> None:
    assert "Enforce tests for source changes" in WORKFLOW
    assert 'path.startsWith("src/")' in WORKFLOW
    assert 'path.startsWith("test/")' in WORKFLOW
    assert "Source changes require test changes" in WORKFLOW


def test_ci_requires_approval_for_the_current_pull_request_head() -> None:
    assert "pull_request_review:" in WORKFLOW
    assert "pull-requests: read" in WORKFLOW
    assert "Code review" in WORKFLOW
    assert 'review.state === "APPROVED"' in WORKFLOW
    assert "review.commit_id === headSha" in WORKFLOW
    assert "Current HEAD requires an approving review" in WORKFLOW
