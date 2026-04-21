"""Cache de respostas do pipeline inteiro (preprocess + upstream + rerank)."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

from config import get_settings


def compute_key(preprocessed_png: bytes) -> str:
    return hashlib.sha256(preprocessed_png).hexdigest()


def get(key: str) -> Optional[dict[str, Any]]:
    settings = get_settings()
    path = settings.cache_path / f"{key}.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text("utf-8"))
    except Exception:
        return None
    ts = raw.get("_cached_at", 0)
    if time.time() - ts > settings.cache_ttl_seconds:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    return raw.get("data")


def put(key: str, data: dict[str, Any]) -> None:
    settings = get_settings()
    path = settings.cache_path / f"{key}.json"
    payload = {"_cached_at": time.time(), "data": data}
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    except OSError:
        pass
