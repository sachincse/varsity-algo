"""Prove the engine cannot see the future.

A leak in a backtest gives you a wrong number. A leak in a live scanner gives
you a signal that could not have existed, and you place a real order against it.
So the same three arguments the backtest used are made here, against the DSL
engine that actually drives the dashboard:

1. TRUNCATION      Signals computed on data[:t] equal signals computed on the
                   full sample and then sliced to t.
2. FUTURE SCRAMBLE Replace every bar after T with noise. Everything at or
                   before T must be bit-identical.
3. NO SELF-REFERENCE  A breakout must clear the PRIOR range, never its own bar.

Run:  python -m pytest tests/ -v
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import (bars_since, evaluate_condition,  # noqa: E402
                         evaluate_operand, run_spec)
from core.spec import (And, Comparison, Constant, Crossover,  # noqa: E402
                       DonchianHigh, EMA, Or, Price, RSI, SMA, StrategySpec,
                       VARSITY_DEFAULT)


# --------------------------------------------------------------------------
def make_panel(n_days=500, n_syms=8, seed=11, gaps=True) -> dict:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n_days)
    syms = [f"SYM{i}" for i in range(n_syms)]

    close = pd.DataFrame(
        {s: 800 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, n_days))) for s in syms},
        index=dates)

    if gaps:
        # Punch holes so the per-symbol-calendar logic is actually exercised.
        for k, s in enumerate(syms[:3]):
            close.iloc[[60 + k * 7, 140 + k * 11, 300 + k * 5], close.columns.get_loc(s)] = np.nan

    op = close.shift(1).fillna(close.iloc[0]) * (1 + rng.normal(0, 0.003, close.shape))
    hi = np.maximum(close, op) * (1 + abs(rng.normal(0, 0.004, close.shape)))
    lo = np.minimum(close, op) * (1 - abs(rng.normal(0, 0.004, close.shape)))
    vol = pd.DataFrame(rng.integers(3_000_000, 9_000_000, close.shape),
                       index=dates, columns=syms).astype(float)
    vol = vol.where(close.notna())

    return {"open": pd.DataFrame(op, index=dates, columns=syms),
            "high": pd.DataFrame(hi, index=dates, columns=syms).where(close.notna()),
            "low": pd.DataFrame(lo, index=dates, columns=syms).where(close.notna()),
            "close": close,
            "volume": vol}


def slice_panel(panel: dict, end) -> dict:
    return {k: v.loc[:end] for k, v in panel.items()}


SPECS = {
    "varsity_6_30": VARSITY_DEFAULT,
    "ema_cross": StrategySpec(
        name="EMA", entry=Crossover(left=EMA(period=9), right=EMA(period=21),
                                    direction="above")),
    "rsi_oversold": StrategySpec(
        name="RSI", entry=Comparison(left=RSI(period=14), op="<",
                                     right=Constant(value=30)),
        exit=Comparison(left=RSI(period=14), op=">", right=Constant(value=70))),
    "breakout": StrategySpec(
        name="Breakout",
        entry=Comparison(left=Price(field="close"), op=">",
                         right=DonchianHigh(period=20)),
        exit=Comparison(left=Price(field="close"), op="<", right=SMA(period=20))),
    "compound": StrategySpec(
        name="Compound",
        entry=And(conditions=[
            Crossover(left=SMA(period=6), right=SMA(period=30), direction="above"),
            Comparison(left=RSI(period=14), op="<", right=Constant(value=70)),
        ]),
        exit=Or(conditions=[
            Crossover(left=SMA(period=6), right=SMA(period=30), direction="below"),
            Comparison(left=RSI(period=14), op=">", right=Constant(value=80)),
        ])),
}


# --------------------------------------------------------------------------
# 1. TRUNCATION
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", list(SPECS))
@pytest.mark.parametrize("cut", [200, 350, 440])
def test_conditions_causal_under_truncation(name, cut):
    spec = SPECS[name]
    panel = make_panel()
    t = panel["close"].index[cut]

    full = evaluate_condition(spec.entry, panel).loc[:t]
    part = evaluate_condition(spec.entry, slice_panel(panel, t))
    pd.testing.assert_frame_equal(part, full, obj=f"{name} entry @ {t.date()}")

    if spec.exit is not None:
        full_x = evaluate_condition(spec.exit, panel).loc[:t]
        part_x = evaluate_condition(spec.exit, slice_panel(panel, t))
        pd.testing.assert_frame_equal(part_x, full_x, obj=f"{name} exit")


@pytest.mark.parametrize("name", list(SPECS))
def test_signal_table_causal_under_truncation(name):
    spec = SPECS[name]
    panel = make_panel()
    t = panel["close"].index[400]
    from_full = run_spec(spec, panel, asof=t)
    from_part = run_spec(spec, slice_panel(panel, t), asof=t)
    pd.testing.assert_frame_equal(from_full, from_part, obj=name)


# --------------------------------------------------------------------------
# 2. FUTURE SCRAMBLE
# --------------------------------------------------------------------------
def scramble_after(panel: dict, cut: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    out = {}
    for k, v in panel.items():
        v2 = v.copy()
        tail = v2.iloc[cut + 1:]
        if k == "volume":
            v2.iloc[cut + 1:] = rng.integers(1e6, 2e7, tail.shape).astype(float)
        else:
            v2.iloc[cut + 1:] = tail.to_numpy() * rng.uniform(0.3, 3.0, tail.shape)
        out[k] = v2
    return out


@pytest.mark.parametrize("name", list(SPECS))
@pytest.mark.parametrize("seed", [1, 2])
def test_future_scramble_leaves_past_untouched(name, seed):
    spec = SPECS[name]
    base = make_panel()
    cut = 350
    t = base["close"].index[cut]
    wrecked = scramble_after(base, cut, seed)

    a = evaluate_condition(spec.entry, base).loc[:t]
    b = evaluate_condition(spec.entry, wrecked).loc[:t]
    pd.testing.assert_frame_equal(a, b, obj=f"{name} survived scramble")

    pd.testing.assert_frame_equal(run_spec(spec, base, asof=t),
                                  run_spec(spec, wrecked, asof=t), obj=name)


# --------------------------------------------------------------------------
# 3. NO SELF-REFERENCE IN BREAKOUTS
# --------------------------------------------------------------------------
def test_donchian_excludes_the_current_bar():
    """If the N-bar high included today, today's high would always equal it and
    a 'close > N-bar high' rule would fire on nearly every bar."""
    panel = make_panel(n_days=200, n_syms=2, gaps=False)
    dh = evaluate_operand(DonchianHigh(period=20), panel)
    high = panel["high"]
    idx = high.index
    for sym in high.columns:
        for i in range(60, 120):
            expected = high[sym].iloc[i - 20:i].max()
            got = dh.at[idx[i], sym]
            assert got == pytest.approx(expected), (
                f"{sym} bar {i}: donchian used the current bar")


def test_breakout_does_not_fire_on_every_bar():
    spec = SPECS["breakout"]
    panel = make_panel(n_days=400, n_syms=4, gaps=False)
    fired = evaluate_condition(spec.entry, panel)
    rate = fired.to_numpy().mean()
    assert 0.0 < rate < 0.25, f"breakout fires on {rate:.1%} of bars — suspicious"


# --------------------------------------------------------------------------
# 4. CROSSOVER SEMANTICS
# --------------------------------------------------------------------------
def test_crossover_fires_once_per_crossing():
    idx = pd.bdate_range("2024-01-01", periods=12)
    fast = [1, 2, 3, 6, 7, 8, 7, 4, 3, 2, 5, 9]
    slow = [5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5]
    panel = {"close": pd.DataFrame({"A": fast}, index=idx),
             "open": pd.DataFrame({"A": fast}, index=idx),
             "high": pd.DataFrame({"A": fast}, index=idx),
             "low": pd.DataFrame({"A": fast}, index=idx),
             "volume": pd.DataFrame({"A": [1e6] * 12}, index=idx)}
    up = evaluate_condition(
        Crossover(left=Price(field="close"), right=Constant(value=5),
                  direction="above"), panel)
    # 1,2,3 below; 6 crosses up; 7,8 stay above; 7 above; 4 crosses down;
    # 3,2 below; 5 is not > 5; 9 crosses up.
    assert up["A"].tolist() == [False, False, False, True, False, False,
                                False, False, False, False, False, True]

    down = evaluate_condition(
        Crossover(left=Price(field="close"), right=Constant(value=5),
                  direction="below"), panel)
    assert down["A"].sum() == 1 and bool(down["A"].iloc[7])


def test_bars_since_counts_backwards_only():
    idx = pd.bdate_range("2024-01-01", periods=9)
    flag = pd.DataFrame({"A": [False, True, False, False, True, False, False,
                               False, False]}, index=idx)
    got = bars_since(flag)["A"].tolist()
    assert np.isnan(got[0])
    assert got[1:] == [0, 1, 2, 0, 1, 2, 3, 4]


# --------------------------------------------------------------------------
# 5. SPEC VALIDATION — the LLM's output must be refused when it is wrong
# --------------------------------------------------------------------------
def test_spec_rejects_out_of_range_period():
    with pytest.raises(Exception):
        SMA(period=10_000)
    with pytest.raises(Exception):
        SMA(period=0)


def test_spec_rejects_unknown_fields():
    with pytest.raises(Exception):
        StrategySpec(name="x", entry=VARSITY_DEFAULT.entry,
                     shell_command="rm -rf /")


def test_spec_rejects_unknown_indicator():
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        StrategySpec.model_validate({
            "name": "bad",
            "entry": {"type": "crossover", "direction": "above",
                      "left": {"kind": "exec", "code": "import os"},
                      "right": {"kind": "sma", "period": 30}}})


def test_spec_is_long_only():
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        StrategySpec.model_validate({
            "name": "short it", "direction": "short",
            "entry": {"type": "crossover", "direction": "below",
                      "left": {"kind": "sma", "period": 6},
                      "right": {"kind": "sma", "period": 30}}})


def test_warmup_reflects_longest_period():
    from core.engine import warmup_bars
    s = StrategySpec(name="slow",
                     entry=Crossover(left=SMA(period=20), right=SMA(period=200),
                                     direction="above"))
    assert s.max_period() == 200
    assert warmup_bars(s) >= 600


def test_varsity_default_round_trips_through_json():
    raw = VARSITY_DEFAULT.model_dump_json()
    back = StrategySpec.model_validate_json(raw)
    assert back == VARSITY_DEFAULT
    assert "SMA(6) crosses above SMA(30)" in back.entry.describe()


# --------------------------------------------------------------------------
# 6. THE CAP MUST NOT LIE
# --------------------------------------------------------------------------
def test_truncation_is_reported_not_silent():
    """max_signals caps the rows returned. The counts must still describe ALL
    signals found, and the number dropped must be stated.

    Regression: the counts were computed from the truncated table, so a scan
    that found 20 entries reported 4 and the order sheet sized from those 4.
    """
    store = make_panel(n_days=600, n_syms=14, seed=5, gaps=False)
    loose = StrategySpec(name="loose", lookback_bars=200, max_signals=500,
                         min_median_turnover=0,
                         entry=Crossover(left=SMA(period=6), right=SMA(period=30),
                                         direction="above"))
    full = run_spec(loose, store)
    assert len(full) > 4, "fixture did not produce enough signals to test the cap"

    capped = run_spec(loose.model_copy(update={"max_signals": 3}), store)
    a = capped.attrs
    assert len(capped) == 3
    assert a["total"] == len(full)
    assert a["shown"] == 3
    assert a["dropped"] == len(full) - 3
    # the headline counts describe everything found, not just what is shown
    assert a["total_entry"] == int((full["side"] == "ENTRY").sum())
    assert a["total_exit"] == int((full["side"] == "EXIT").sum())


def test_uncapped_scan_reports_zero_dropped():
    store = make_panel(n_days=600, n_syms=8, seed=6, gaps=False)
    spec = StrategySpec(name="x", max_signals=500, min_median_turnover=0,
                        entry=Crossover(left=SMA(period=6), right=SMA(period=30),
                                        direction="above"))
    t = run_spec(spec, store)
    assert t.attrs["dropped"] == 0
    assert t.attrs["shown"] == t.attrs["total"] == len(t)


def test_empty_result_still_carries_counts():
    """An empty table must not KeyError the caller."""
    store = make_panel(n_days=120, n_syms=4, gaps=False)
    spec = StrategySpec(name="impossible", lookback_bars=1,
                        entry=Comparison(left=RSI(period=14), op="<",
                                         right=Constant(value=-999)))
    t = run_spec(spec, store)
    assert t.empty
    for k in ("total", "total_entry", "total_exit", "shown", "dropped"):
        assert k in t.attrs


def test_spread_rank_mode_is_gone():
    """The DSL advertised rank_by='spread' but the engine treated it as
    recency. A closed language must not offer a mode it does not implement."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        StrategySpec.model_validate({
            "name": "x", "rank_by": "spread",
            "entry": {"type": "crossover", "direction": "above",
                      "left": {"kind": "sma", "period": 6},
                      "right": {"kind": "sma", "period": 30}}})
