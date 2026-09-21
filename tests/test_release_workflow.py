"""Checks that release version detection delegates to uv."""

from pathlib import Path

WORKFLOW = (Path(__file__).parents[1] / ".github" / "workflows" / "release.yml").read_text(
    encoding="utf-8"
)


def test_release_workflow_uses_uv_version_for_current_and_previous_projects() -> None:
    assert "uv version --short" in WORKFLOW
    assert "uv version --project $previousProject --short" in WORKFLOW
    assert "release_version.py" not in WORKFLOW
