"""Check YOUR strategy for look-ahead bias, not just the one that shipped.

The engine's causality is covered by tests. Those tests use fixed strategies,
so they say nothing about a rule you invented this morning — and a strategy is
where look-ahead most easily creeps in, because the temptation is always to
reference something the bar has not finished doing yet.

Four checks, each a different argument:

  TRUNCATION   Signals computed on data[:t] must equal signals computed on the
               full history and then sliced to t. If anything reads forward,
               removing the future changes the past.

  SCRAMBLE     Replace every bar after date T with noise. Signals up to T must
               be identical. This catches leakage through channels nobody
               thought to look for, including ones inside your own indicators.

  INDICATORS   Compare the indicator series itself at the as-of bar, for
               every symbol, with and without the future present. Nothing has
               to fire for this to detect a leak — which matters, because a
               shift of one bar moves the NUMBERS without moving the crossover
               days, and the signal-level checks above sail straight past it.

  RECURSIVE    Recompute the indicators from several different start dates and
               compare the tail. A rule whose value at t depends on how much
               history preceded it is not stable, which is a milder problem
               than look-ahead but produces backtests that cannot be
               reproduced. (freqtrade calls this recursive-analysis.)

    python tools/lookahead_check.py                     # the shipped default
    python tools/lookahead_check.py --spec my.json
    python tools/lookahead_check.py --text "golden cross on the nifty 500"

Exits non-zero if any check fails, so it can gate a change.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.data import load_panel_yf                        # noqa: E402
from core.engine import (_rule_operands, evaluate_operand,      # noqa: E402
                         run_spec, warmup_bars)
from core.spec import VARSITY_DEFAULT, StrategySpec        # noqa: E402

OK, BAD = "  PASS  ", "  FAIL  "
_failed = 0


def check(name: str, passed: bool, note: str = "") -> None:
    global _failed
    if not passed:
        _failed += 1
    print(f"{OK if passed else BAD}{name}" + (f"  — {note}" if note else ""))


def _slice_panel(panel: dict, upto: int) -> dict:
    return {k: (v.iloc[:upto] if isinstance(v, pd.DataFrame) else v)
            for k, v in panel.items()}


def _scramble_after(panel: dict, cut: int, seed: int = 5) -> dict:
    """Mangle every bar after `cut`, keeping the index and column set."""
    rng = np.random.default_rng(seed)
    out = {}
    for k, v in panel.items():
        if not isinstance(v, pd.DataFrame):
            out[k] = v
            continue
        d = v.copy()
        tail = d.iloc[cut + 1:]
        if len(tail):
            if k == "volume":
                d.iloc[cut + 1:] = rng.integers(1e5, 1e7, tail.shape).astype(float)
            else:
                d.iloc[cut + 1:] = tail.to_numpy() * rng.uniform(0.4, 2.5, tail.shape)
        out[k] = d
    return out


def _signal_key(df: pd.DataFrame) -> list:
    """Signals reduced to something comparable across runs.

    The INDICATOR VALUES are part of the key, not just which rows appeared.
    Comparing only (symbol, side, date) misses a whole class of leak: shift an
    average one bar forward and the same crossovers still fire on the same
    days, because the shift applies to both runs equally. What changes is the
    number the row is built from. The self-test below is what surfaced this —
    with an identity-only key it reported a clean bill of health on an engine
    that had been deliberately broken.
    """
    if df is None or df.empty:
        return []
    ident = [c for c in ("symbol", "side", "signal_date") if c in df.columns]
    vals = [c for c in ("price", "left_value", "right_value") if c in df.columns]

    def cell(r, c):
        v = r[c]
        if c in vals:
            try:
                return "nan" if pd.isna(v) else f"{float(v):.6f}"
            except (TypeError, ValueError):
                return str(v)
        return str(v)

    return sorted(tuple(cell(r, c) for c in ident + vals)
                  for _, r in df.iterrows())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", help="path to a strategy JSON file")
    ap.add_argument("--text", help="plain English; needs a configured LLM")
    ap.add_argument("--universe", default=None,
                    help="override the spec's universe (fewer symbols is faster)")
    ap.add_argument("--symbols", type=int, default=40,
                    help="how many symbols to test with")
    ap.add_argument("--bars", type=int, default=500)
    ap.add_argument("--selftest", action="store_true",
                    help="deliberately make the engine look ahead and confirm "
                         "these checks go red")
    args = ap.parse_args()

    if args.spec:
        spec = StrategySpec.model_validate(
            json.loads(Path(args.spec).read_text(encoding="utf-8")))
    elif args.text:
        from core.nl import build_messages, compile_flat, flat_schema
        from server.llm.base import generate_with_repair
        from server.llm.registry import build_provider
        system, messages = build_messages(args.text)
        spec = compile_flat(
            generate_with_repair(build_provider(), system, messages,
                                 flat_schema()).strategy)
    else:
        spec = VARSITY_DEFAULT

    if args.universe:
        spec = spec.model_copy(update={"universe": args.universe})

    if args.selftest:
        # A checker nobody has tried to fool is not evidence. Shift every
        # moving average one bar into the future and the checks below MUST
        # fail; if they still pass, they are not testing anything.
        import core.engine as eng
        _real_sma = eng._sma
        eng._sma = lambda panel, n: _real_sma(panel, n).shift(-1)
        print("  SELFTEST: moving averages deliberately shifted one bar "
              "forward — every causality check below should FAIL\n")

    print(f"\n  strategy: {spec.name}")
    print(f"  {spec.describe().splitlines()[1].strip()}")
    print(f"  entry: {spec.entry.describe()}")
    print()

    from core.data import fetch_universe
    symbols = fetch_universe(spec.universe)[:args.symbols]
    need = args.bars + warmup_bars(spec) + 10
    print(f"  loading {len(symbols)} symbols x {need} bars ...", flush=True)
    panel = load_panel_yf(symbols, need, spec.interval)

    n = len(panel["close"])
    if n < 200:
        print(f"  only {n} bars available — not enough to test causality")
        return 2
    print(f"  {n} bars\n")

    full = run_spec(spec, panel)
    full_keys = _signal_key(full)
    print(f"  baseline: {len(full_keys)} signals\n")
    if not full_keys:
        print("  this strategy produces no signals at all, so there is nothing "
              "to test. Loosen it and re-run.")
        return 2

    # ---- 1. truncation ----------------------------------------------------
    # run_spec only ever returns signals inside the lookback window, so the
    # comparison has to be "truncated data, asked at t" against "full data,
    # asked at t" — NOT against the full run sliced to t, which is a different
    # window and would report a leak on a perfectly causal engine.
    for frac in (0.6, 0.8):
        cut = int(n * frac)
        asof = panel["close"].index[cut - 1]
        part = run_spec(spec, _slice_panel(panel, cut))
        same_asof = run_spec(spec, panel, asof=asof)
        a, b = _signal_key(part), _signal_key(same_asof)
        if not a and not b:
            check(f"truncating at {asof.date()} leaves earlier signals unchanged",
                  False, "no signals on either side — the comparison proves "
                         "nothing; widen --bars or loosen the rule")
        else:
            check(f"truncating at {asof.date()} leaves earlier signals unchanged",
                  a == b,
                  f"{len(a)} vs {len(b)} signals" if a != b
                  else f"{len(a)} signals identical")

    # ---- 2. future scramble ----------------------------------------------
    for cut_frac, seed in ((0.6, 5), (0.75, 11)):
        cut = int(n * cut_frac)
        asof = panel["close"].index[cut]
        a = _signal_key(run_spec(spec, _scramble_after(panel, cut, seed), asof=asof))
        b = _signal_key(run_spec(spec, panel, asof=asof))
        if not a and not b:
            check(f"scrambling everything after {asof.date()} leaves the past alone",
                  False, "no signals on either side — this would pass whatever "
                         "the engine did, so it is not evidence")
        else:
            check(f"scrambling everything after {asof.date()} leaves the past alone",
                  a == b,
                  "the future changed the past — this rule looks ahead"
                  if a != b else f"{len(b)} signals identical")

    # ---- 3. the indicator series itself ----------------------------------
    # The checks above only inspect rows where a signal fired. A leak that
    # shifts an average one bar forward moves the NUMBERS without moving the
    # crossover days, and it only diverges at the final bar — where a signal
    # usually is not. The self-test caught exactly that hole: it reported a
    # clean bill of health on an engine that had been deliberately broken.
    #
    # So compare the indicator values directly, for every symbol, at the
    # as-of bar. Nothing has to fire for this to detect a leak.
    left, right = _rule_operands(spec.entry)
    if left is not None:
        for frac in (0.7, 0.85):
            cut = int(n * frac)
            asof = panel["close"].index[cut - 1]
            trunc = _slice_panel(panel, cut)
            worst, where = 0.0, ""
            for operand in (o for o in (left, right) if o is not None):
                a = evaluate_operand(operand, trunc)
                b = evaluate_operand(operand, panel).loc[:asof]
                if a.empty or b.empty:
                    continue
                ra, rb = a.iloc[-1], b.iloc[-1]
                cols = [c for c in ra.index if c in rb.index]
                for c in cols:
                    va, vb = ra[c], rb[c]
                    if pd.isna(va) and pd.isna(vb):
                        continue
                    if pd.isna(va) != pd.isna(vb):
                        worst, where = float("inf"), f"{c} ({operand.label})"
                        break
                    d = abs(float(va) - float(vb))
                    scale = max(abs(float(vb)), 1e-9)
                    if d / scale > worst:
                        worst, where = d / scale, f"{c} ({operand.label})"
            check(f"indicator values at {asof.date()} use no later bar",
                  worst < 1e-9,
                  f"{where} differs once the future is removed"
                  if worst >= 1e-9 else
                  f"identical across {len(panel['close'].columns)} symbols")

    # ---- 4. recursive stability ------------------------------------------
    tails = []
    for drop in (0, 60, 120):
        sub = {k: (v.iloc[drop:] if isinstance(v, pd.DataFrame) else v)
               for k, v in panel.items()}
        r = run_spec(spec, sub)
        last = panel["close"].index[-1]
        recent = r[pd.to_datetime(r["signal_date"]) > last - pd.Timedelta(days=60)] \
            if not r.empty else r
        tails.append(_signal_key(recent))

    stable = all(t == tails[0] for t in tails)
    check("recent signals do not depend on how much history preceded them",
          stable,
          "indicators have not converged — results will not reproduce"
          if not stable else f"{len(tails[0])} recent signals, identical from "
                             f"3 different start dates")

    print()
    if args.selftest:
        # A one-bar shift is only visible to the indicator comparison: it moves
        # the numbers, not the crossover days, so the signal-level checks
        # legitimately stay green. Demanding that all of them fail would be a
        # false standard. Two is the honest bar, and reaching it is what proves
        # this suite is not merely agreeing with itself.
        if _failed >= 2:
            print(f"  SELFTEST PASSED: {_failed} checks caught the injected "
                  f"look-ahead.\n")
            return 0
        print(f"  SELFTEST FAILED: only {_failed} checks noticed a moving "
              f"average reading one bar into the future. These checks are not "
              f"testing what they claim to.\n")
        return 1

    if _failed:
        print(f"  {_failed} check(s) FAILED. This strategy can see the future, "
              f"or its indicators have not settled.\n")
        return 1
    print("  All checks passed. Nothing in this strategy reads a bar that had "
          "not happened yet.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
