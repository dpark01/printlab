#!/usr/bin/env python3
"""Regenerate docs/schemas/*.json from printlab.schemas.ARTIFACT_MODELS.

Run after changing any artifact model. tests/unit/test_schemas.py asserts
these committed files stay in sync so CI catches drift.
"""

from __future__ import annotations

import json
from pathlib import Path

from printlab.schemas import ARTIFACT_MODELS

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"


def main() -> None:
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    for model_cls in ARTIFACT_MODELS:
        schema = model_cls.model_json_schema()
        path = SCHEMAS_DIR / f"{model_cls.__name__}.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
