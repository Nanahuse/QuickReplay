"""Read project versions and decide whether a release is required."""

from __future__ import annotations

import argparse
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZERO_SHA = "0" * 40


def version_from_text(text: str) -> str | None:
    data = tomllib.loads(text)
    version = data.get("project", {}).get("version")
    return str(version) if version else None


def version_from_path(path: Path = ROOT / "pyproject.toml") -> str | None:
    return version_from_text(path.read_text(encoding="utf-8"))


def previous_version(commit: str, *, repository: Path = ROOT) -> str | None:
    if not commit or commit == ZERO_SHA:
        return None
    result = subprocess.run(
        ["git", "show", f"{commit}:pyproject.toml"],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return version_from_text(result.stdout)


def release_required(previous: str | None, current: str | None) -> bool:
    return bool(current) and previous != current


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--current", action="store_true")
    source.add_argument("--previous-ref")
    args = parser.parse_args()
    version = version_from_path() if args.current else previous_version(args.previous_ref)
    print(version or "")


if __name__ == "__main__":
    main()
