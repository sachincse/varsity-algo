"""Turn a compiled strategy back into English, and flag what looks wrong.

`StrategySpec.describe()` prints the spec compactly, which is useful for a
developer and close to useless as a confirmation step. Showing someone

    entry      SMA(6) crosses above SMA(30)

asks them to check the notation they just typed. Showing them

    Buy a stock on the day its 6-day average price crosses above its 30-day
    average.

asks them to check the MEANING, which is the thing that can be wrong. A model
that misreads "under 70" as "over 70" produces a spec that validates perfectly
and describes itself in notation the user will nod along to.

So this is a decompiler, not a formatter. Round-tripping through plain English
is what catches a misunderstanding, and it is deliberately worded differently
from the prompt so agreement means something.

`lint()` is a separate pass. Schema validation asks whether a strategy is
well-formed; linting asks whether it is sensible. A rule that can never fire,
or that buys and sells on the same condition, is valid and useless.
"""
from __future__ import annotations

from dataclasses import dataclass

from .spec import StrategySpec

UNIVERSE_ENGLISH = {
    "nifty50": "the 50 largest stocks on the NSE",
    "nifty100": "the 100 largest stocks on the NSE",
    "nifty200": "the 200 largest stocks on the NSE",
    "nifty500": "the 500 largest stocks on the NSE",
}

INTERVAL_ENGLISH = {
    "day": "daily",
    "60minute": "hourly",
    "30minute": "half-hourly",
    "15minute": "15-minute",
    "5minute": "5-minute",
}

BAR_WORD = {"day": "day", "60minute": "hour", "30minute": "half-hour",
            "15minute": "15 minutes", "5minute": "5 minutes"}


def _operand(o) -> str:
    kind = getattr(o, "kind", None)
    if kind == "sma":
        return f"its {o.period}-{'day' if o.period != 1 else 'day'} average price"
    if kind == "ema":
        return f"its {o.period}-day weighted average price"
    if kind == "rsi":
        return f"its {o.period}-day RSI (a 0-100 momentum gauge)"
    if kind == "price":
        return {"close": "its closing price", "open": "its opening price",
                "high": "its high", "low": "its low"}[o.field]
    if kind == "const":
        v = o.value
        return f"{v:g}"
    if kind == "donchian_high":
        return f"its highest price of the last {o.period} days"
    if kind == "donchian_low":
        return f"its lowest price of the last {o.period} days"
    return getattr(o, "label", str(o))


def _condition(c, top: bool = True) -> str:
    t = getattr(c, "type", None)
    if t == "crossover":
        verb = "rises above" if c.direction == "above" else "falls below"
        return f"{_operand(c.left)} {verb} {_operand(c.right)}"
    if t == "comparison":
        words = {"<": "is below", "<=": "is at or below",
                 ">": "is above", ">=": "is at or above"}[c.op]
        return f"{_operand(c.left)} {words} {_operand(c.right)}"
    if t == "and":
        parts = [_condition(x, top=False) for x in c.conditions]
        return " and ".join(parts) if len(parts) == 2 else \
            ", ".join(parts[:-1]) + f", and {parts[-1]}"
    if t == "or":
        parts = [_condition(x, top=False) for x in c.conditions]
        return " or ".join(parts) if len(parts) == 2 else \
            ", ".join(parts[:-1]) + f", or {parts[-1]}"
    return str(c)


def explain(spec: StrategySpec) -> str:
    """The strategy as a short paragraph, in the words a person would use."""
    uni = UNIVERSE_ENGLISH.get(spec.universe, spec.universe)
    freq = INTERVAL_ENGLISH.get(spec.interval, spec.interval)
    bar = BAR_WORD.get(spec.interval, "bar")

    lines = [f"Every {'day' if spec.interval == 'day' else bar}, look at {uni}, "
             f"using {freq} prices."]

    lines.append(f"Buy a stock when {_condition(spec.entry)}.")

    if spec.exit is not None:
        lines.append(f"Sell it again when {_condition(spec.exit)}. "
                     f"Selling here means closing a position you already hold "
                     f"— it is never a short.")
    else:
        lines.append("No exit rule is set, so this only ever tells you what to "
                     "buy. You decide when to sell.")

    rank = ("the most recent crossovers first" if spec.rank_by == "recency"
            else "the most heavily traded stocks first")
    lines.append(f"Show {rank}, counting only signals from the last "
                 f"{spec.lookback_bars} {bar}s, and list at most "
                 f"{spec.max_signals}.")

    skips = []
    if spec.min_price:
        skips.append(f"cheaper than Rs {spec.min_price:g}")
    if getattr(spec, "min_median_turnover", 0):
        skips.append(f"trading less than Rs {spec.min_median_turnover / 1e7:.1f} "
                     f"crore a day")
    if skips:
        lines.append(f"Skip anything { ' or '.join(skips) }.")

    return " ".join(lines)


# --------------------------------------------------------------------------
# lint
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Note:
    level: str          # "warn" | "info"
    message: str


def _periods(c, out: list) -> None:
    for side in ("left", "right"):
        o = getattr(c, side, None)
        if o is not None and hasattr(o, "period"):
            out.append((getattr(o, "kind", "?"), o.period))
    for sub in getattr(c, "conditions", []) or []:
        _periods(sub, out)


def _consts(c, out: list) -> None:
    for side in ("left", "right"):
        o = getattr(c, side, None)
        if o is not None and getattr(o, "kind", None) == "const":
            out.append((getattr(getattr(c, "left", None), "kind", "?"), o.value))
    for sub in getattr(c, "conditions", []) or []:
        _consts(sub, out)


def lint(spec: StrategySpec) -> list[Note]:
    """Well-formed is not the same as sensible.

    The schema stops a strategy that cannot be parsed. Nothing stops one that
    parses perfectly and can never fire, or that buys and sells on the same
    condition, or that asks for 500 stocks and shows 5 of them.
    """
    notes: list[Note] = []

    if spec.exit is not None and spec.entry.describe() == spec.exit.describe():
        notes.append(Note("warn",
                          "The buy and sell rules are identical, so every "
                          "position would close the moment it opens."))

    if spec.exit is None:
        notes.append(Note("info",
                          "No exit rule. The scanner will tell you what to buy "
                          "and never what to sell."))

    # An RSI threshold outside 0-100 can never be crossed.
    consts: list = []
    _consts(spec.entry, consts)
    if spec.exit is not None:
        _consts(spec.exit, consts)
    for kind, value in consts:
        if kind == "rsi" and not (0 <= value <= 100):
            notes.append(Note("warn",
                              f"RSI only ever sits between 0 and 100, so a "
                              f"threshold of {value:g} can never be met."))

    periods: list = []
    _periods(spec.entry, periods)
    if spec.exit is not None:
        _periods(spec.exit, periods)
    longest = max((p for _, p in periods), default=0)
    if longest and spec.lookback_bars and longest > spec.lookback_bars * 6:
        notes.append(Note("info",
                          f"The longest average is {longest} bars but you are "
                          f"only looking back {spec.lookback_bars}. That is "
                          f"fine, just expect very few signals."))

    if spec.universe in ("nifty200", "nifty500") and spec.max_signals < 25:
        notes.append(Note("info",
                          f"Scanning {spec.universe} but showing at most "
                          f"{spec.max_signals} rows — you will likely be seeing "
                          f"a truncated list."))

    if spec.interval != "day":
        notes.append(Note("info",
                          "Intraday intervals need a live Kite session; the "
                          "free end-of-day feed cannot supply them."))

    if getattr(spec, "min_median_turnover", 0) == 0:
        notes.append(Note("warn",
                          "No liquidity filter. Thinly traded stocks will "
                          "appear, and a market order in one of those can move "
                          "the price against you."))

    return notes
