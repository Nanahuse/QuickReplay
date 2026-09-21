"""Headless tests for the portable Windows distribution staging helper."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from zipfile import ZipFile

_SPEC = spec_from_file_location(
    "package_windows_release", Path(__file__).parents[1] / "tools" / "package_windows_release.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
create_distribution = _MODULE.create_distribution
read_project_version = _MODULE.read_project_version


def test_project_version_is_read_from_pyproject() -> None:
    assert read_project_version() == "2.0.0"


def test_distribution_contains_versioned_zip_and_notices(tmp_path: Path) -> None:
    build_dir = tmp_path / "build" / "windows"
    build_dir.mkdir(parents=True)
    (build_dir / "QuickReplay.exe").write_bytes(b"test executable")
    (build_dir / "runtime.dll").write_bytes(b"test runtime")

    archive = create_distribution(build_dir=build_dir, output_dir=tmp_path / "dist")

    assert archive.name == "QuickReplay-2.0.0-windows-x64.zip"
    with ZipFile(archive) as zip_file:
        assert set(zip_file.namelist()) == {
            "QuickReplay/QuickReplay.exe",
            "QuickReplay/runtime.dll",
            "QuickReplay/LICENSE",
            "QuickReplay/LICENSE_ThirdParty.md",
        }
