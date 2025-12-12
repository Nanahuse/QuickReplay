import tempfile
from pathlib import Path

from replayer.file_manager import FileManager


def test_file_manager_basic_push_and_files() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        fm = FileManager(work_dir, frame_threshold=100)
        fm.push_file(work_dir / "a.mp4", 10)
        fm.push_file(work_dir / "b.mp4", 20)
        files = fm.files()
        assert len(files) == 2
        assert files[0].path.name == "a.mp4"
        assert files[0].frame_num == 10
        assert files[1].path.name == "b.mp4"
        assert files[1].frame_num == 20
        assert fm.frame_count == 30


def test_file_manager_get_new_file_path() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        fm = FileManager(work_dir, frame_threshold=100)
        p1 = fm.get_new_file_path()
        p2 = fm.get_new_file_path()
        assert p1 != p2
        assert p1.name.startswith("record_")
        assert p1.suffix == ".mp4"


def test_file_manager_threshold_and_drop() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        fm = FileManager(work_dir, frame_threshold=15)
        # 1つ目が消える
        f1 = work_dir / "a.mp4"
        f2 = work_dir / "b.mp4"
        f3 = work_dir / "c.mp4"
        f1.touch()
        f2.touch()
        f3.touch()
        fm.push_file(f1, 10)
        fm.push_file(f2, 10)
        fm.push_file(f3, 5)
        files = fm.files()
        assert len(files) == 2
        assert files[0].path == f2
        assert files[1].path == f3
        assert not f1.exists()  # 削除された
        assert fm.frame_count == 15
