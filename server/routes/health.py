"""Health and configuration status — what the UI shows on the setup screen."""
from __future__ import annotations

import os
import sys

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "python": sys.version.split()[0]}


@router.get("/config")
def config() -> dict:
    """Everything the setup panel needs, with no secrets in the response."""
    from server.kite_client import SESSION
    from server.price_source import resolve as resolve_source
    from server.llm.registry import CATALOG, active_key, survey

    key = active_key()
    source, pinned = resolve_source()
    return {
        "kite": SESSION.status(),
        "llm": {
            "active": key,
            "active_label": CATALOG[key].label if key in CATALOG else key,
            "model": os.getenv("LLM_MODEL")
                     or (CATALOG[key].default_model if key in CATALOG else ""),
            "providers": survey(),
        },
        "price_source": source,
        "price_source_pinned": pinned,
        "trading_enabled": os.getenv("ENABLE_TRADING", "false").lower() == "true",
    }
