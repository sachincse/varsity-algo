"""OHLC bars for one symbol, with the strategy's own indicators overlaid.

The signals table shows the close beside both moving averages so a crossover
can be checked by eye. Reading three numbers and picturing the lines crossing
is a poor substitute for seeing them cross, and it is exactly the check a chart
makes instant.

This endpoint exists so the Signals tab can draw one. It returns the same bars
the scan used and the same indicator series the engine computed, so the chart
cannot drift away from the table beside it — a chart that disagrees with the
signal it illustrates is worse than no chart.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from core.data import load_panel_kite, load_panel_yf
from server.kite_client import SESSION, KiteNotAuthenticated
from server.price_source import resolve as resolve_source

router = APIRouter()

MAX_BARS = 900


def _clean(v) -> float | None:
    """JSON has no NaN. A gap must arrive as null, not as a broken number."""
    if v is None:
        return None
    f = float(v)
    return None if (np.isnan(f) or np.isinf(f)) else round(f, 4)


@router.get("")
def bars(symbol: str = Query(min_length=1, max_length=30),
         interval: str = "day",
         count: int = Query(default=260, ge=30, le=MAX_BARS),
         short: int = Query(default=0, ge=0, le=400),
         long: int = Query(default=0, ge=0, le=400),
         source: str | None = None) -> dict:
    """Candles for one symbol, plus two simple moving averages if asked for."""
    sym = symbol.strip().upper()
    src, _pinned = resolve_source(source)

    # Enough history to warm the longer average up before the first drawn bar,
    # otherwise the overlay starts partway across the chart for no visible
    # reason.
    warmup = max(short, long)
    need = min(count + warmup + 5, MAX_BARS + 400)

    try:
        if src == "kite":
            panels = load_panel_kite(SESSION.client(), [sym], need, interval)
        else:
            panels = load_panel_yf([sym], need, interval)
    except KiteNotAuthenticated as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except Exception as e:                                      # noqa: BLE001
        raise HTTPException(status_code=502,
                            detail=f"could not load bars for {sym}: {e}") from e

    close = panels.get("close")
    if close is None or sym not in close.columns or close[sym].dropna().empty:
        raise HTTPException(
            status_code=404,
            detail=f"no price history for {sym} from {src}. Check the symbol, "
                   f"or try the other price source.")

    df = pd.DataFrame({k: panels[k][sym] for k in
                       ("open", "high", "low", "close") if k in panels})
    df = df.dropna(how="all")

    sma_s = close[sym].rolling(short, min_periods=short).mean() if short else None
    sma_l = close[sym].rolling(long, min_periods=long).mean() if long else None

    tail = df.index[-count:]
    out = []
    for t in tail:
        row = {"time": pd.Timestamp(t).strftime("%Y-%m-%d"),
               "open": _clean(df.at[t, "open"]) if "open" in df else None,
               "high": _clean(df.at[t, "high"]) if "high" in df else None,
               "low": _clean(df.at[t, "low"]) if "low" in df else None,
               "close": _clean(df.at[t, "close"])}
        # lightweight-charts refuses a candle with a missing field; drop the
        # bar rather than inventing a price for it.
        if any(row[k] is None for k in ("open", "high", "low", "close")):
            continue
        out.append(row)

    def series(s):
        if s is None:
            return []
        return [{"time": pd.Timestamp(t).strftime("%Y-%m-%d"), "value": v}
                for t in tail
                if (v := _clean(s.get(t))) is not None]

    return {
        "symbol": sym, "interval": interval, "source": src,
        "bars": out,
        "short": {"period": short, "points": series(sma_s)} if short else None,
        "long": {"period": long, "points": series(sma_l)} if long else None,
    }
