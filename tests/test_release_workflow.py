"""Checks that release version detection delegates to uv."""

from pathlib import Path

WORKFLOW = (Path(__file__).parents[1] / ".github" / "workflows" / "release.yml").read_text(
    encoding="utf-8"
)


def test_release_workflow_uses_uv_version_and_tag_existence() -> None:
    assert "uv version --short" in WORKFLOW
    assert "git/ref/tags/$tag" in WORKFLOW
    assert "github.event.before" not in WORKFLOW
    assert "release_version.py" not in WORKFLOW
