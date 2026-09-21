"""Seek-bar conversion and drag logic (pure, no Flet widgets)."""

from quickreplay.ui.main_view import SeekDrag, slider_seconds_to_ns


def test_slider_seconds_to_ns() -> None:
    assert slider_seconds_to_ns(0) == 0
    assert slider_seconds_to_ns(0.001) == 1_000_000
    assert slider_seconds_to_ns(1.25) == 1_250_000_000
    assert slider_seconds_to_ns(3.5) == 3_500_000_000


def test_seek_drag_lifecycle() -> None:
    drag = SeekDrag()
    assert not drag.active

    drag.start(1.0)
    assert drag.active
    assert drag.preview_ns == 1_000_000_000

    drag.update_preview(2.5)
    assert drag.active  # preview updates do not end the drag
    assert drag.preview_ns == 2_500_000_000

    target = drag.end(3.25)
    assert target == 3_250_000_000
    assert drag.preview_ns == 3_250_000_000
    assert not drag.active
