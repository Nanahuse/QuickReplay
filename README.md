# QuickReplay

QuickReplay Version 2 is under development.

Version 2 is a rewrite of QuickReplay.  The previous Version 1 implementation
has been removed from this repository.  The core domain model, the segment
recording core, the ring storage / retention core, the replay asset
(stream-copy remux) core, the NDI input core, the camera input core and the
headless recorder worker (separate process, capture/encode threads, bounded
queues, replay preparation) and the mpv-based replay controller (external mpv
process, JSON IPC, frame-accurate stepping and seeking) are implemented.  The
headless application controller orchestrates recording, replay preparation, mpv
playback and recording resume.  Configuration persistence (versioned JSON
schema v1, NDI/Camera input selection, recorder buffer setting, mpv executable
setting, atomic save) is implemented.  A Flet 1.0 desktop UI foundation (input
discovery and selection, camera backend selection, recording state, stream
information and metrics, replay preparation and resume) is implemented.  The
full replay control UI, settings editor and packaging are not implemented yet.

## Requirements

- Python >= 3.14
- [uv](https://docs.astral.sh/uv/)

The local development baseline is Python 3.14 (see `.python-version`).  This is
the development baseline, not an upper bound: Version 2 supports Python 3.14
and later.

## Development setup

```powershell
uv sync
```

## Run the desktop app

```powershell
uv run flet run src/quickreplay/ui/app.py
```

## Test

```powershell
uv run pytest
```

## Lint

```powershell
uv run ruff check .
```

## Type check

```powershell
uv run ty check
```

`ty` is used for static type checking.  `mypy` is intentionally not used.

## Branch status

Version 2 is developed on the `feature/version2` integration branch.  Feature
work is done on short-lived branches (for example `feature/v2-domain`) and
merged into `feature/version2` via pull request.  `main` is not merged into
directly.

## Project layout

```text
src/
└─ quickreplay/
   ├─ app/          # application state and view models
   ├─ application/  # headless application controller (recording/replay lifecycle)
   ├─ configuration/# versioned JSON configuration persistence
   ├─ input/        # input config, stream info, frame models, InputSource
   │  ├─ ndi/       # NDI discovery, receiver and frame conversion
   │  └─ camera/    # camera discovery, OpenCV capture and frame conversion
   ├─ recording/    # segment/session models, segment recorder, worker protocol
   ├─ replay/       # replay models, asset builder, remux and mpv controller
   ├─ worker/       # recorder worker process, pipeline and frame queues
   ├─ ui/           # Flet 1.0 desktop UI (bootstrap, bridge, session, view)
   └─ units.py      # nanosecond / Fraction helpers
tests/
pyproject.toml
uv.lock
```

## License

See `LICENSE`.  Third-party license notes are in `LICENSE_ThirdParty.md` and
will be updated once the Version 2 dependencies are finalised.
