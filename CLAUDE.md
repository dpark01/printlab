# CLAUDE.md

Claude-Code-specific notes for working in this repo. **`AGENTS.md` is the
canonical source of behavioral rules for any coding agent** (Claude Code
included) — read it first. This file only adds Claude-Code-specific
mechanics that don't belong there.

## Commands

```bash
uv sync                                    # install/update the environment
uv run printlab doctor                     # check native slicer versions
uv run printlab all examples/bracket --backend prusaslicer
uv run pytest tests/                       # unit + integration (self-skipping)
uv run ruff check .                        # lint
uv run python scripts/generate_schemas.py  # regenerate docs/schemas/*.json
```

## Conventions

- Python 3.12, managed by `uv`. Don't `pip install` directly — edit
  `pyproject.toml` and run `uv sync` (or `uv add <pkg>`), then commit the
  updated `uv.lock` and regenerate `requirements.txt` via
  `uv export --no-hashes -o requirements.txt`.
- Pydantic v2 models for every artifact schema, defined once in
  `printlab/schemas/` and imported everywhere else — don't redefine a
  shape inline in a stage module.
- After changing any model in `printlab/schemas/`, run
  `scripts/generate_schemas.py` — `tests/unit/test_schemas.py` fails the
  build otherwise.
- No comments explaining *what* code does; a short comment is fine for a
  non-obvious *why* (see existing modules for the expected density).
