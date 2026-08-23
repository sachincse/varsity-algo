"""Price data, from either of two backends.

The video requires a Kite Connect subscription because it pulls historical
candles from the broker. That is the right source if you have it, but it is not
required for a daily-timeframe scanner, and making it mandatory stops people
running the thing at all. So there are two backends behind one interface:

  yfinance  free, end-of-day, no Kite subscription, no API key.  Default.
  kite      Kite Connect historical candles. Needed for intraday intervals and
            for prices that match your broker's chart exactly.

PRICE BASIS — this matters, so it is spelled out.
yfinance with ``auto_adjust=False`` returns OHLC already adjusted for splits and
bonuses but NOT dividends. Split adjustment cannot move a crossover: it scales
every price in the pre-event window by the same constant, so both moving
averages scale identically and the crossing lands on the same bar. Dividend
adjustment is different — it retroactively erases an ex-date gap that a real
trader actually saw — so it is never used for signals.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta

import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

FIELDS = ["open", "high", "low", "close", "volume"]

# Kite's own per-request limits, by interval. Exceeding these returns an error
# rather than truncating, so long ranges must be chunked.
KITE_MAX_DAYS = {
    "minute": 60, "3minute": 100, "5minute": 100, "10minute": 100,
    "15minute": 200, "30minute": 200, "60minute": 400, "day": 2000,
}


# --------------------------------------------------------------------------
# universe lists
# --------------------------------------------------------------------------
NIFTY_CSV = {
    "nifty50": "ind_nifty50list.csv",
    "nifty100": "ind_nifty100list.csv",
    "nifty200": "ind_nifty200list.csv",
    "nifty500": "ind_nifty500list.csv",
}
NIFTY_URL = "https://niftyindices.com/IndexConstituent/{}"


def fetch_universe(name: str, refresh: bool = False) -> list[str]:
    """NSE index constituents, cached on disk.

    NOTE: this is TODAY's membership. Using it to reason about the past is
    survivorship bias — see the backtest study for how large that is. For a
    live scanner, today's membership is exactly right.
    """
    fn = NIFTY_CSV[name]
    path = os.path.join(os.path.dirname(CACHE_DIR), fn)
    if refresh or not os.path.exists(path):
        import requests
        r = requests.get(NIFTY_URL.format(fn), timeout=40, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        r.raise_for_status()
        if "Symbol" not in r.text:
            raise RuntimeError(f"unexpected response for {name}")
        with open(path, "w", encoding="utf-8") as f:
            f.write(r.text)
    df = pd.read_csv(path)
    return sorted(df["Symbol"].astype(str).str.strip().unique().tolist())


# --------------------------------------------------------------------------
# yfinance backend
# --------------------------------------------------------------------------
def _cache_path(symbol: str, interval: str) -> str:
    safe = symbol.replace("/", "_").replace("&", "_")
    return os.path.join(CACHE_DIR, f"{safe}__{interval}.csv")


def _read_cache(path: str) -> pd.DataFrame | None:
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df if len(df) else None
    except Exception:
        return None


def yf_symbol_history(symbol: str, start: str, end: str,
                      interval: str = "day", force: bool = False) -> pd.DataFrame | None:
    """One NSE symbol from Yahoo. The cache is MERGED, never replaced, so a
    short refresh can never truncate a long history."""
    import yfinance as yf

    yf_interval = {"day": "1d", "60minute": "60m", "30minute": "30m",
                   "15minute": "15m", "5minute": "5m"}[interval]
    path = _cache_path(symbol, interval)
    cached = _read_cache(path)

    if cached is not None and not force:
        covers = (cached.index.min() <= pd.Timestamp(start) + pd.Timedelta(days=10)
                  and cached.index.max() >= pd.Timestamp(end) - pd.Timedelta(days=5))
        if covers:
            return cached.loc[str(start):str(end)]

    for attempt in range(3):
        try:
            df = yf.Ticker(f"{symbol}.NS").history(
                start=start, end=end, interval=yf_interval,
                auto_adjust=False, actions=False, timeout=30)
            if df is None or df.empty:
                return cached.loc[str(start):str(end)] if cached is not None else None
            df.index = pd.to_datetime(df.index)
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            if interval == "day":
                df.index = df.index.normalize()
            df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
            if cached is not None:
                cached = cached.reindex(columns=df.columns)
                df = pd.concat([cached[~cached.index.isin(df.index)], df]).sort_index()
            df.to_csv(path)
            return df.loc[str(start):str(end)]
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return cached.loc[str(start):str(end)] if cached is not None else None


def load_panel_yf(symbols: list[str], bars_needed: int, interval: str = "day",
                  force: bool = False, progress=None) -> dict:
    """Wide panel of open/high/low/close/volume for ``symbols``."""
    per_year = {"day": 250, "60minute": 1500, "30minute": 3000,
                "15minute": 6000, "5minute": 18000}[interval]
    days_back = int(bars_needed / per_year * 365) + 40
    # Yahoo only serves ~60 days of intraday history.
    if interval != "day":
        days_back = min(days_back, 58)
    start = (date.today() - timedelta(days=days_back)).isoformat()
    end = (date.today() + timedelta(days=1)).isoformat()

    frames, missing = {}, []
    for i, s in enumerate(symbols, 1):
        df = yf_symbol_history(s, start, end, interval, force=force)
        if df is None or df.empty:
            missing.append(s)
        else:
            frames[s] = df
        if progress and i % 20 == 0:
            progress(i, len(symbols), len(missing))

    if not frames:
        raise RuntimeError("no price data returned for any symbol")

    panel = {f: pd.DataFrame({s: d[f] for s, d in frames.items()}).sort_index()
             for f in FIELDS}
    cal = panel["close"].index
    # Reindex onto the union calendar. Missing bars stay NaN — never forward
    # filled, because a filled bar is a price nobody could have traded.
    panel = {f: v.reindex(cal) for f, v in panel.items()}
    panel["_missing"] = missing
    return panel


# --------------------------------------------------------------------------
# Kite backend
# --------------------------------------------------------------------------
def load_panel_kite(kite, symbols: list[str], bars_needed: int,
                    interval: str = "day", exchange: str = "NSE",
                    progress=None) -> dict:
    """Wide panel from Kite Connect historical candles.

    Requires an authenticated ``KiteConnect`` and a Connect subscription.
    Chunks requests to respect the per-interval range limit and sleeps to stay
    inside the historical-endpoint rate limit.
    """
    tokens = instrument_tokens(kite, symbols, exchange)
    per_year = {"day": 250, "60minute": 1500, "30minute": 3000,
                "15minute": 6000, "5minute": 18000}[interval]
    days_back = int(bars_needed / per_year * 365) + 40
    max_span = KITE_MAX_DAYS.get(interval, 100)

    frames, missing = {}, []
    for i, sym in enumerate(symbols, 1):
        tok = tokens.get(sym)
        if tok is None:
            missing.append(sym)
            continue
        rows = []
        to_dt = datetime.now()
        remaining = days_back
        try:
            while remaining > 0:
                span = min(remaining, max_span)
                frm = to_dt - timedelta(days=span)
                chunk = kite.historical_data(tok, frm, to_dt, interval)
                if not chunk:
                    break
                rows = list(chunk) + rows
                to_dt = frm - timedelta(days=1)
                remaining -= span
                time.sleep(0.35)          # historical endpoint is ~3 req/s
        except Exception:
            pass
        if not rows:
            missing.append(sym)
            continue
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        if df["date"].dt.tz is not None:
            df["date"] = df["date"].dt.tz_localize(None)
        df = df.set_index("date").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        if interval == "day":
            df.index = df.index.normalize()
        frames[sym] = df[["open", "high", "low", "close", "volume"]]
        if progress and i % 10 == 0:
            progress(i, len(symbols), len(missing))

    if not frames:
        raise RuntimeError("Kite returned no candles. Is the Connect "
                           "subscription active and the session valid?")

    panel = {f: pd.DataFrame({s: d[f] for s, d in frames.items()}).sort_index()
             for f in FIELDS}
    cal = panel["close"].index
    panel = {f: v.reindex(cal) for f, v in panel.items()}
    panel["_missing"] = missing
    return panel


_INSTRUMENT_CACHE: dict[str, dict] = {}


def instrument_tokens(kite, symbols: list[str], exchange: str = "NSE") -> dict[str, int]:
    """Map tradingsymbol -> instrument_token using the daily instruments dump.

    The dump is several megabytes and changes once a day, so it is cached in
    memory for the life of the process.
    """
    key = f"{exchange}"
    if key not in _INSTRUMENT_CACHE:
        rows = kite.instruments(exchange)
        _INSTRUMENT_CACHE[key] = {
            r["tradingsymbol"]: r["instrument_token"] for r in rows
        }
    table = _INSTRUMENT_CACHE[key]
    return {s: table[s] for s in symbols if s in table}


def clear_instrument_cache() -> None:
    _INSTRUMENT_CACHE.clear()
