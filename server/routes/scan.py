"""Run a strategy spec over a universe and return the ranked signal table."""
from __future__ import annotations

import logging
import os
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from core.data import fetch_universe, load_panel_kite, load_panel_yf
from core.engine import run_spec, warmup_bars
from core.spec import VARSITY_DEFAULT, StrategySpec
from server.kite_client import SESSION, KiteNotAuthenticated

router = APIRouter()
log = logging.getLogger("varsity.scan")

# The panel is expensive to build, so keep the last one for a few minutes.
_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_TTL = int(os.getenv("PANEL_CACHE_SECONDS", "600"))


class ScanBody(BaseModel):
    spec: dict | None = None
    source: str | None = Field(default=None, description="yfinance | kite")
    refresh: bool = False
    limit_symbols: int | None = Field(default=None, ge=1, le=500)


def _panel(universe: str, interval: str, bars: int, source: str,
           refresh: bool, limit: int | None) -> dict:
    key = f"{source}:{universe}:{interval}:{bars}:{limit}"
    now = time.time()
    if not refresh and key in _CACHE:
        ts, panel = _CACHE[key]
        if now - ts < CACHE_TTL:
            return panel

    symbols = fetch_universe(universe)
    if limit:
        symbols = symbols[:limit]

    t0 = time.time()
    if source == "kite":
        try:
            kite = SESSION.client()
        except KiteNotAuthenticated as e:
            raise HTTPException(
                status_code=401,
                detail=f"{e} Or set PRICE_SOURCE=yfinance to scan without a "
                       f"Kite subscription.") from e
        panel = load_panel_kite(kite, symbols, bars, interval)
    else:
        if interval != "day":
            raise HTTPException(
                status_code=400,
                detail="Intraday intervals need PRICE_SOURCE=kite. The free "
                       "Yahoo feed only reliably serves daily bars.")
        panel = load_panel_yf(symbols, bars, interval, force=refresh)

    log.info("built %s panel: %d symbols, %d bars in %.1fs",
             source, panel["close"].shape[1], panel["close"].shape[0],
             time.time() - t0)
    _CACHE[key] = (now, panel)
    return panel


@router.post("")
def scan(body: ScanBody) -> dict:
    try:
        spec = (StrategySpec.model_validate(body.spec) if body.spec
                else VARSITY_DEFAULT)
    except ValidationError as e:
        raise HTTPException(status_code=422,
                            detail=f"invalid strategy spec: {e}") from e

    source = (body.source or os.getenv("PRICE_SOURCE", "yfinance")).lower()
    bars = warmup_bars(spec)

    try:
        panel = _panel(spec.universe, spec.interval, bars, source,
                       body.refresh, body.limit_symbols)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502,
                            detail=f"could not load prices: {e}") from e

    missing = panel.get("_missing", [])
    panel = {k: v for k, v in panel.items() if not k.startswith("_")}

    try:
        table = run_spec(spec, panel)
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"strategy failed to run: {e}") from e

    close = panel["close"]
    asof = close.index[-1]
    return {
        "spec": spec.model_dump(mode="json"),
        "summary": spec.describe(),
        "asof": str(asof.date()),
        "source": source,
        "universe_size": close.shape[1],
        "bars": close.shape[0],
        "missing_symbols": missing,
        "signals": table.to_dict("records") if not table.empty else [],
        "counts": {
            "entry": int((table["side"] == "ENTRY").sum()) if not table.empty else 0,
            "exit": int((table["side"] == "EXIT").sum()) if not table.empty else 0,
        },
    }


@router.get("/universes")
def universes() -> dict:
    return {"universes": ["nifty50", "nifty100", "nifty200", "nifty500"]}
