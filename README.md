# QuickReplay

QuickReplay Version 2 is under development.

Version 2 is a rewrite of QuickReplay.  The previous Version 1 implementation
has been removed from this repository.  The Version 2 core domain model is
under implementation; no product functionality is implemented yet.

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
   ├─ input/        # input config, stream info and frame models
   ├─ recording/    # segment/session models, worker commands and events
   ├─ replay/       # replay snapshot, asset and set-point models
   └─ units.py      # nanosecond / Fraction helpers
tests/
pyproject.toml
uv.lock
```

## License

See `LICENSE`.  Third-party license notes are in `LICENSE_ThirdParty.md` and
will be updated once the Version 2 dependencies are finalised.
