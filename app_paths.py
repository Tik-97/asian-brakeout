from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def resolve_runtime_path(env_name: str, default_name: str) -> Path:
    raw_value = os.getenv(env_name, default_name)
    path = Path(raw_value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def ensure_parent_dir(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
