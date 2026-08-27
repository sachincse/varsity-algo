"""Executes a StrategySpec against a price panel.

CAUSALITY CONTRACT
Every value produced for bar ``t`` is a function of bars at index <= t only.
There is no ``shift(-1)``, no ``center=True``, no ``bfill``, and nothing is
computed over the full sample. ``tests/test_causality.py`` enforces this by
truncating the input and asserting the output is unchanged, and by scrambling
all future bars and asserting the past is untouched.

This matters more here than in a backtest. A leak in a backtest gives you a
wrong number; a leak in a live scanner gives you a signal that could not have
existed, and you trade on it.

PER-SYMBOL CALENDARS
The panel is indexed on the union of every symbol's trading days, so a symbol
that did not print a bar carries NaN there. Rolling straight across that panel
would blank N days of signal for one missing bar and silently drop the name
from the candidate list. Every rolling quantity is therefore computed on the
symbol's own bar sequence and reindexed back. Removing rows cannot introduce
lookahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .spec import (And, Comparison, Constant, Crossover, DonchianHigh,
                   DonchianLow, EMA, Or, Price, RSI, SMA, StrategySpec)


# --------------------------------------------------------------------------
# Indicators — each returns a frame aligned to the panel index
# --------------------------------------------------------------------------
def _per_symbol(close: pd.DataFrame, fn) -> pd.DataFrame:
    out = {}
    for col in close.columns:
        s = close[col].dropna()
        out[col] = fn(s).reindex(close.index) if len(s) else pd.Series(
            np.nan, index=close.index)
    return pd.DataFrame(out, index=close.index, columns=close.columns)


def _sma(panel: dict, n: int) -> pd.DataFrame:
    return _per_symbol(panel["close"], lambda s: s.rolling(n, min_periods=n).mean())


def _ema(panel: dict, n: int) -> pd.DataFrame:
    # adjust=False gives the recursive form, which is what a chart shows.
    return _per_symbol(panel["close"],
                       lambda s: s.ewm(span=n, adjust=False, min_periods=n).mean())


def _rsi(panel: dict, n: int) -> pd.DataFrame:
    def calc(s: pd.Series) -> pd.Series:
        d = s.diff()
        gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        rs = gain / loss.replace(0, np.nan)
        out = 100 - 100 / (1 + rs)
        return out.where(loss != 0, 100.0)
    return _per_symbol(panel["close"], calc)


def _donchian(panel: dict, n: int, high: bool) -> pd.DataFrame:
    src = panel["high"] if high else panel["low"]
    # shift(1) excludes the current bar: a breakout must clear the PRIOR range,
    # otherwise the bar trivially equals its own extreme and every bar signals.
    if high:
        return _per_symbol(src, lambda s: s.rolling(n, min_periods=n).max().shift(1))
    return _per_symbol(src, lambda s: s.rolling(n, min_periods=n).min().shift(1))


def evaluate_operand(node, panel: dict) -> pd.DataFrame:
    idx, cols = panel["close"].index, panel["close"].columns
    if isinstance(node, SMA):
        return _sma(panel, node.period)
    if isinstance(node, EMA):
        return _ema(panel, node.period)
    if isinstance(node, RSI):
        return _rsi(panel, node.period)
    if isinstance(node, Price):
        return panel[node.field]
    if isinstance(node, Constant):
        return pd.DataFrame(node.value, index=idx, columns=cols)
    if isinstance(node, DonchianHigh):
        return _donchian(panel, node.period, high=True)
    if isinstance(node, DonchianLow):
        return _donchian(panel, node.period, high=False)
    raise ValueError(f"unknown operand {type(node).__name__}")


# --------------------------------------------------------------------------
# Conditions
# --------------------------------------------------------------------------
def _prev_valid(df: pd.DataFrame) -> pd.DataFrame:
    """Previous value on each symbol's OWN bar sequence.

    A plain ``shift(1)`` on the union calendar would compare against a day the
    symbol did not trade, which manufactures crossings out of gaps.
    """
    out = {}
    for col in df.columns:
        s = df[col].dropna()
        out[col] = s.shift(1).reindex(df.index)
    return pd.DataFrame(out, index=df.index, columns=df.columns)


def evaluate_condition(node, panel: dict) -> pd.DataFrame:
    if isinstance(node, And):
        parts = [evaluate_condition(c, panel) for c in node.conditions]
        acc = parts[0]
        for p in parts[1:]:
            acc = acc & p
        return acc

    if isinstance(node, Or):
        parts = [evaluate_condition(c, panel) for c in node.conditions]
        acc = parts[0]
        for p in parts[1:]:
            acc = acc | p
        return acc

    if isinstance(node, Comparison):
        left = evaluate_operand(node.left, panel)
        right = evaluate_operand(node.right, panel)
        valid = left.notna() & right.notna()
        ops = {"<": left < right, "<=": left <= right,
               ">": left > right, ">=": left >= right}
        return ops[node.op] & valid

    if isinstance(node, Crossover):
        left = evaluate_operand(node.left, panel)
        right = evaluate_operand(node.right, panel)
        above = left > right
        valid = left.notna() & right.notna()

        prev_above = _prev_valid(above.where(valid))
        prev_known = prev_above.notna()
        prev_bool = prev_above.fillna(False).astype(bool)

        if node.direction == "above":
            fired = above & (~prev_bool)
        else:
            fired = (~above) & prev_bool
        return fired & valid & prev_known

    raise ValueError(f"unknown condition {type(node).__name__}")


# --------------------------------------------------------------------------
# Signals
# --------------------------------------------------------------------------
def bars_since(flag: pd.DataFrame) -> pd.DataFrame:
    """Bars elapsed since the last True at or before t. NaN before the first."""
    idx = np.arange(len(flag))
    out = {}
    for col in flag.columns:
        f = flag[col].to_numpy(dtype=bool)
        last = np.maximum.accumulate(np.where(f, idx, -1))
        out[col] = np.where(last >= 0, idx - last, np.nan)
    return pd.DataFrame(out, index=flag.index, columns=flag.columns)


def _rule_operands(node):
    """The two sides of the entry rule, if it is a simple comparison.

    The video's table shows the close alongside SMA(6) and SMA(30) — the actual
    indicator values behind the signal, so you can eyeball whether it is real.
    Reporting them generically means the same column works for an EMA cross, an
    RSI threshold, or a breakout.
    """
    if isinstance(node, (Crossover, Comparison)):
        return node.left, node.right
    if isinstance(node, (And, Or)) and node.conditions:
        return _rule_operands(node.conditions[0])
    return None, None


def _default_exit(spec: StrategySpec):
    """If no exit was given and the entry is a crossover, the exit is the
    opposite crossing. Anything else needs an explicit exit."""
    if spec.exit is not None:
        return spec.exit
    if isinstance(spec.entry, Crossover):
        return Crossover(left=spec.entry.left, right=spec.entry.right,
                         direction="below" if spec.entry.direction == "above"
                                   else "above")
    return None


def run_spec(spec: StrategySpec, panel: dict,
             asof: pd.Timestamp | None = None) -> pd.DataFrame:
    """Return the ranked signal table as of ``asof``.

    ``panel`` is a dict of wide frames: open, high, low, close, volume.
    Only rows with index <= asof are read.
    """
    close = panel["close"]
    if asof is None:
        asof = close.index[-1]
    # The loader attaches metadata alongside the price frames — "_missing" is
    # a plain list of symbols it could not fetch. Slicing blindly assumed every
    # value was a frame and crashed on it, which nothing noticed because the
    # scan path leaves asof unset and skips this line entirely.
    panel = {k: (v.loc[:asof] if isinstance(v, pd.DataFrame) else v)
             for k, v in panel.items()}
    close = panel["close"]
    if close.empty:
        return pd.DataFrame()

    last = close.index[-1]

    entry = evaluate_condition(spec.entry, panel)

    # Indicator values for the table, so a signal can be checked by eye.
    left_op, right_op = _rule_operands(spec.entry)
    left_vals = evaluate_operand(left_op, panel) if left_op is not None else None
    right_vals = evaluate_operand(right_op, panel) if right_op is not None else None
    left_label = left_op.label if left_op is not None else ""
    right_label = right_op.label if right_op is not None else ""
    exit_node = _default_exit(spec)
    exit_ = (evaluate_condition(exit_node, panel) if exit_node is not None
             else pd.DataFrame(False, index=close.index, columns=close.columns))

    since_entry = bars_since(entry)
    since_exit = bars_since(exit_)

    # Liquidity filter, causal: trailing 60-bar median of traded value.
    turnover = _per_symbol(
        close * panel["volume"],
        lambda s: s.rolling(60, min_periods=20).median())

    rows = []
    for sym in close.columns:
        se = since_entry.at[last, sym]
        sx = since_exit.at[last, sym]

        # Which fired most recently? NaN means never.
        e_ok = pd.notna(se) and se <= spec.lookback_bars
        x_ok = pd.notna(sx) and sx <= spec.lookback_bars
        if not e_ok and not x_ok:
            continue
        if e_ok and (not x_ok or se <= sx):
            side, since = "ENTRY", int(se)
        else:
            side, since = "EXIT", int(sx)

        bar = close[sym].last_valid_index()
        if bar is None:
            continue
        px = float(close.at[bar, sym])
        if px < spec.min_price:
            continue
        tv = turnover.at[last, sym]
        if pd.isna(tv) or float(tv) < spec.min_median_turnover:
            continue

        fired_on = close.index[close.index.get_loc(last) - since]
        def at_last(frame):
            if frame is None:
                return None
            v = frame[sym].loc[:last].dropna()
            return round(float(v.iloc[-1]), 2) if len(v) else None

        rows.append({
            "symbol": sym,
            "side": side,
            "signal_date": fired_on.date(),
            "bars_since": since,
            "price": round(px, 2),
            "price_date": bar.date(),
            "left_label": left_label,
            "left_value": at_last(left_vals),
            "right_label": right_label,
            "right_value": at_last(right_vals),
            "median_turnover_cr": round(float(tv) / 1e7, 2),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        empty = pd.DataFrame(columns=["symbol", "side", "signal_date",
                                      "bars_since", "price", "price_date",
                                      "left_label", "left_value",
                                      "right_label", "right_value",
                                      "median_turnover_cr"])
        empty.attrs.update(total=0, total_entry=0, total_exit=0,
                           shown=0, dropped=0)
        return empty

    if spec.rank_by == "turnover":
        df = df.sort_values(["median_turnover_cr", "bars_since"],
                            ascending=[False, True])
    else:                                    # recency
        df = df.sort_values(["bars_since", "symbol"])

    # Record the FULL counts before the cap. Reporting counts from the
    # truncated table is how a scanner quietly tells you there are 4 buy
    # candidates when there are 20 — the cap has to be visible or it is a lie.
    total = len(df)
    total_entry = int((df["side"] == "ENTRY").sum())
    total_exit = int((df["side"] == "EXIT").sum())

    out = df.head(spec.max_signals).reset_index(drop=True)
    out.attrs.update(total=total, total_entry=total_entry,
                     total_exit=total_exit, shown=len(out),
                     dropped=total - len(out))
    return out


def warmup_bars(spec: StrategySpec) -> int:
    """How much history to fetch before the first bar you want a signal on."""
    return max(spec.max_period() * 3, 120) + spec.lookback_bars
