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
from server.jobs import STORE, Job
from server.kite_client import SESSION, KiteNotAuthenticated
from server.price_source import resolve as resolve_source

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
           refresh: bool, limit: int | None, job: Job | None = None) -> dict:
    key = f"{source}:{universe}:{interval}:{bars}:{limit}"
    now = time.time()
    if not refresh and key in _CACHE:
        ts, panel = _CACHE[key]
        if now - ts < CACHE_TTL:
            return panel

    symbols = fetch_universe(universe)
    if limit:
        symbols = symbols[:limit]

    if job is not None:
        job.total = len(symbols)
        job.message = f"downloading {len(symbols)} symbols"

    def report(done: int, total: int, missing: int) -> None:
        if job is not None:
            job.current = done
            job.message = (f"downloaded {done}/{total} symbols"
                           + (f", {missing} unavailable" if missing else ""))

    t0 = time.time()
    if source == "kite":
        try:
            kite = SESSION.client()
        except KiteNotAuthenticated as e:
            raise HTTPException(
                status_code=401,
                detail=f"{e} Or set PRICE_SOURCE=yfinance to scan without a "
                       f"Kite subscription.") from e
        panel = load_panel_kite(kite, symbols, bars, interval,
                                progress=report)
    else:
        if interval != "day":
            raise HTTPException(
                status_code=400,
                detail="Intraday intervals need PRICE_SOURCE=kite. The free "
                       "Yahoo feed only reliably serves daily bars.")
        panel = load_panel_yf(symbols, bars, interval, force=refresh,
                              progress=report)

    log.info("built %s panel: %d symbols, %d bars in %.1fs",
             source, panel["close"].shape[1], panel["close"].shape[0],
             time.time() - t0)
    _CACHE[key] = (now, panel)
    return panel


def _do_scan(spec: StrategySpec, source: str, refresh: bool,
             limit: int | None, job: Job | None = None) -> dict:
    """The whole scan. Shared by the blocking and the job-based endpoints."""
    bars = warmup_bars(spec)
    panel = _panel(spec.universe, spec.interval, bars, source, refresh, limit, job)

    missing = panel.get("_missing", [])
    panel = {k: v for k, v in panel.items() if not k.startswith("_")}

    if job is not None:
        job.message = "computing signals"
    table = run_spec(spec, panel)

    close = panel["close"]
    a = table.attrs
    dropped = int(a.get("dropped", 0))
    if dropped:
        log.info("scan produced %d signals, showing %d (max_signals=%d)",
                 a.get("total"), a.get("shown"), spec.max_signals)

    return {
        "spec": spec.model_dump(mode="json"),
        "summary": spec.describe(),
        "asof": str(close.index[-1].date()),
        "source": source,
        "universe_size": close.shape[1],
        "bars": close.shape[0],
        "missing_symbols": missing,
        "signals": table.to_dict("records") if not table.empty else [],
        # Counts are for ALL signals found, not just the rows returned.
        "counts": {"entry": int(a.get("total_entry", 0)),
                   "exit": int(a.get("total_exit", 0))},
        "shown": int(a.get("shown", 0)),
        "total": int(a.get("total", 0)),
        "dropped": dropped,
        "max_signals": spec.max_signals,
    }


def _resolve(body: "ScanBody") -> tuple[StrategySpec, str]:
    try:
        spec = (StrategySpec.model_validate(body.spec) if body.spec
                else VARSITY_DEFAULT)
    except ValidationError as e:
        raise HTTPException(status_code=422,
                            detail=f"invalid strategy spec: {e}") from e
    source, _pinned = resolve_source(body.source)
    return spec, source


@router.post("")
def scan(body: ScanBody) -> dict:
    """Blocking scan. Fine for a cached panel; use /start for a cold one."""
    spec, source = _resolve(body)
    try:
        return _do_scan(spec, source, body.refresh, body.limit_symbols)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"scan failed: {e}") from e


@router.post("/start")
def scan_start(body: ScanBody) -> dict:
    """Kick off a scan on a worker thread and return a job id to poll.

    A cold first scan downloads hundreds of symbols. Doing that inside the
    request leaves the browser on a spinner with no idea whether it is working
    or hung, which is where people give up.
    """
    spec, source = _resolve(body)
    job = STORE.create("scan")
    STORE.run(job, lambda j: _do_scan(spec, source, body.refresh,
                                      body.limit_symbols, j))
    return {"job_id": job.id, "state": job.state}


@router.get("/status/{job_id}")
def scan_status(job_id: str) -> dict:
    job = STORE.get(job_id)
    if job is None:
        raise HTTPException(status_code=404,
                            detail="Unknown job. It may have expired — "
                                   "start the scan again.")
    return job.to_dict()


@router.get("/universes")
def universes() -> dict:
    return {"universes": ["nifty50", "nifty100", "nifty200", "nifty500"]}
