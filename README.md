# QuickReplay

QuickReplay Version 2 is a Windows desktop instant replay application for NDI
inputs.

Version 2 is a rewrite of QuickReplay.  The previous Version 1 implementation
has been removed from this repository.  The core domain model, the segment
recording core, the ring storage / retention core, the replay asset
(stream-copy remux) core, the NDI input core and the
headless recorder worker (separate process, capture/encode threads, bounded
queues, replay preparation) and the mpv-based replay controller (external mpv
process, JSON IPC, frame-accurate stepping and seeking) are implemented.  The
headless application controller orchestrates recording, replay preparation, mpv
playback and recording resume.  Configuration persistence (versioned JSON
schema v1, NDI input selection, recorder buffer setting, mpv executable
setting, atomic save) is implemented.  A Flet 1.0 desktop UI is implemented:
NDI input discovery and selection, recording state,
stream information and metrics, replay preparation, and the replay control UI
(Play/Pause, ±1 and ±20 frame steps, seek bar, Set Point, time and frame
difference, resume).  A settings editor (explicit Apply/Cancel) edits the
persisted configuration: the recording buffer duration and the mpv executable.
Buffer duration and mpv executable changes are saved but need an application
restart to take effect.

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
uv run flet run src/main.py
```

## Build for Windows

Windows packaging requires Visual Studio with **Desktop development with C++**
and Windows Developer Mode (for symlink support). Build the x64 desktop
application from a clean Flet build with:

```powershell
uv run flet clean
uv run flet build windows --python-version 3.14
```

The packaged application is generated under `build/windows` as
`QuickReplay.exe`. The build uses the dependencies declared in
`pyproject.toml`; no separate `requirements.txt` is needed.

### Runtime requirements

The packaged application does not require Python, uv, or Visual Studio to run.
Replay playback requires an external mpv executable, which can be configured
from Settings. mpv is not bundled in the distribution ZIP.

NDI input uses the NDI runtime available to the packaged application through
the existing `ndi-python` integration; this phase does not introduce a new NDI
distribution mechanism.

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

Development is performed on short-lived branches and merged into `main` through
pull requests.

## Project layout

```text
src/
└─ quickreplay/
   ├─ app/          # application state and view models
   ├─ application/  # headless application controller (recording/replay lifecycle)
   ├─ configuration/# versioned JSON configuration persistence
   ├─ input/        # input config, stream info, frame models, InputSource
   │  └─ ndi/       # NDI discovery, receiver and frame conversion
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

See `LICENSE`.  Third-party license notices are listed in
`LICENSE_ThirdParty.md`.
