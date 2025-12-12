# ruff: noqa: E402

import sys
from pathlib import Path

import cv2

work_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(work_dir / "src"))

from replayer.file_manager import FileManager
from replayer.internal_types import Resolution
from replayer.writer import Writer

fmt = cv2.VideoWriter.fourcc(*"mp4v")

if __name__ == "__main__":
    capture = cv2.VideoCapture(5)

    writer = Writer(
        FileManager(Path(work_dir / "tmp_video"), 600),
        fmt=fmt,
        frame_rate=60,
        frame_size=Resolution(640, 480),
        max_buffer_seconds=10,
    )
    try:
        with writer:
            while True:
                ret, frame = capture.read()
                if not ret:
                    break

                writer.write(frame)

                cv2.imshow("Webcam", frame)

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        capture.release()
        cv2.destroyAllWindows()
