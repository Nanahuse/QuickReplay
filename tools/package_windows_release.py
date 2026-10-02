"""Stage the Flet Windows build and create the portable release ZIP."""

from __future__ import annotations

import argparse
import shutil
import tomllib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def read_project_version(pyproject: Path = ROOT / "pyproject.toml") -> str:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def create_distribution(
    *,
    build_dir: Path = ROOT / "build" / "windows",
    output_dir: Path = ROOT / "dist",
) -> Path:
    version = read_project_version()
    staging_root = output_dir / "QuickReplay"
    archive = output_dir / f"QuickReplay-{version}-windows-x64.zip"

    if not build_dir.is_dir():
        raise FileNotFoundError(f"Flet build output does not exist: {build_dir}")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    staging_root.mkdir(parents=True)
    for item in build_dir.iterdir():
        destination = staging_root / item.name
        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            shutil.copy2(item, destination)
    shutil.copy2(ROOT / "LICENSE", staging_root / "LICENSE")
    shutil.copy2(ROOT / "LICENSE_ThirdParty.md", staging_root / "LICENSE_ThirdParty.md")

    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zip_file:
        for path in staging_root.rglob("*"):
            if path.is_file():
                zip_file.write(path, path.relative_to(output_dir).as_posix())
    return archive


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build" / "windows")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    print(create_distribution(build_dir=args.build_dir, output_dir=args.output_dir))


if __name__ == "__main__":
    main()
