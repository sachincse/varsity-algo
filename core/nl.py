"""Natural language -> validated StrategySpec.

This is the video's central promise — "describe your algo in English" — done in
a way that is safe to point at a funded account.

TWO SCHEMAS, ON PURPOSE
``StrategySpec`` (core/spec.py) is expressive: conditions nest, AND/OR compose
recursively, operands are a discriminated union. That is a good internal
representation and a *terrible* thing to ask a language model for. Recursive
JSON schemas with ``$ref`` and discriminated unions are the first thing that
breaks when you leave the frontier models — a 7B model running locally through
Ollama will not produce one reliably, and strict-schema modes on several
providers reject recursion outright.

So the model fills in ``FlatStrategy`` instead: no nesting, no recursion, no
unions, just enums and numbers, one level deep. Then ``compile_flat`` turns it
into a real ``StrategySpec`` and every constraint is re-checked. If the model
hallucinates an indicator, inverts an operator, or invents a field, compilation
fails loudly and nothing runs.

The model never emits code, and never emits anything that is executed.
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .spec import (And, Comparison, Constant, Crossover, DonchianHigh,
                   DonchianLow, EMA, Or, Price, RSI, SMA, StrategySpec)

# --------------------------------------------------------------------------
# The flat schema the model actually sees
# --------------------------------------------------------------------------
IndicatorName = Literal[
    "sma", "ema", "rsi",
    "close", "open", "high", "low",
    "highest_high", "lowest_low",
    "number",
]

NEEDS_PERIOD = {"sma", "ema", "rsi", "highest_high", "lowest_low"}
NEEDS_VALUE = {"number"}


class Operand(BaseModel):
    """One side of a rule."""
    model_config = {"extra": "forbid"}

    indicator: IndicatorName = Field(
        description="sma/ema/rsi need a period. highest_high and lowest_low are "
                    "the extreme of the previous N bars, excluding today. "
                    "number needs a value. close/open/high/low need neither.")
    period: int | None = Field(
        default=None, ge=1, le=400,
        description="Bar count for sma, ema, rsi, highest_high, lowest_low.")
    value: float | None = Field(
        default=None,
        description="The literal number, only when indicator is 'number'.")

    @model_validator(mode="after")
    def _check(self) -> "Operand":
        if self.indicator in NEEDS_PERIOD and self.period is None:
            raise ValueError(f"'{self.indicator}' requires a period")
        if self.indicator in NEEDS_VALUE and self.value is None:
            raise ValueError("'number' requires a value")
        return self


class Rule(BaseModel):
    model_config = {"extra": "forbid"}

    comparison: Literal["crosses_above", "crosses_below",
                        "is_above", "is_below"] = Field(
        description="crosses_* fires only on the bar the crossing happens. "
                    "is_* is true on every bar the state holds.")
    left: Operand
    right: Operand


class FlatStrategy(BaseModel):
    """What the LLM returns. Deliberately boring."""
    model_config = {"extra": "forbid"}

    name: str = Field(max_length=80, description="Short human name.")
    summary: str = Field(default="", max_length=300,
                         description="One sentence restating the rule in plain English.")
    universe: Literal["nifty50", "nifty100", "nifty200", "nifty500"] = "nifty100"
    interval: Literal["day", "60minute", "30minute", "15minute", "5minute"] = "day"

    entry_rules: list[Rule] = Field(min_length=1, max_length=4)
    entry_combine: Literal["all", "any"] = "all"

    exit_rules: list[Rule] = Field(default_factory=list, max_length=4)
    exit_combine: Literal["all", "any"] = "any"

    rank_by: Literal["recency", "turnover"] = "recency"
    lookback_bars: int = Field(default=15, ge=1, le=250)

    unsupported_request: str = Field(
        default="",
        description="If the user asked for something this schema cannot express "
                    "(options, shorting, fundamentals, news, order placement), "
                    "say so here in one sentence instead of approximating it.")


# --------------------------------------------------------------------------
# Compilation
# --------------------------------------------------------------------------
def _operand(o: Operand):
    if o.indicator == "sma":
        return SMA(period=o.period)
    if o.indicator == "ema":
        return EMA(period=o.period)
    if o.indicator == "rsi":
        return RSI(period=o.period)
    if o.indicator in ("close", "open", "high", "low"):
        return Price(field=o.indicator)
    if o.indicator == "highest_high":
        return DonchianHigh(period=o.period)
    if o.indicator == "lowest_low":
        return DonchianLow(period=o.period)
    if o.indicator == "number":
        return Constant(value=o.value)
    raise ValueError(f"unknown indicator {o.indicator!r}")


def _rule(r: Rule):
    left, right = _operand(r.left), _operand(r.right)
    if r.comparison == "crosses_above":
        return Crossover(left=left, right=right, direction="above")
    if r.comparison == "crosses_below":
        return Crossover(left=left, right=right, direction="below")
    if r.comparison == "is_above":
        return Comparison(left=left, op=">", right=right)
    if r.comparison == "is_below":
        return Comparison(left=left, op="<", right=right)
    raise ValueError(f"unknown comparison {r.comparison!r}")


def _combine(rules: list[Rule], how: str):
    parts = [_rule(r) for r in rules]
    if len(parts) == 1:
        return parts[0]
    return And(conditions=parts) if how == "all" else Or(conditions=parts)


def compile_flat(flat: FlatStrategy) -> StrategySpec:
    """Turn the model's flat answer into a validated, executable spec."""
    if flat.unsupported_request:
        raise UnsupportedStrategy(flat.unsupported_request)

    return StrategySpec(
        name=flat.name,
        description=flat.summary,
        universe=flat.universe,
        interval=flat.interval,
        entry=_combine(flat.entry_rules, flat.entry_combine),
        exit=_combine(flat.exit_rules, flat.exit_combine) if flat.exit_rules else None,
        rank_by=flat.rank_by,
        lookback_bars=flat.lookback_bars,
    )


class UnsupportedStrategy(Exception):
    """The model correctly reported that the request is out of scope."""


# --------------------------------------------------------------------------
# The prompt
# --------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You convert a trader's plain-English description into a strict JSON strategy \
object. You do not write code. You only fill in the schema.

WHAT THE SCHEMA CAN EXPRESS
- Indicators: simple moving average (sma), exponential moving average (ema), \
RSI (rsi), the raw bar (close/open/high/low), the highest high or lowest low of \
the previous N bars (highest_high / lowest_low), and literal numbers (number).
- Comparisons: crosses_above and crosses_below fire ONLY on the bar the \
crossing completes. is_above and is_below are true on every bar the state holds.
- Up to 4 entry rules and 4 exit rules, combined with "all" (AND) or "any" (OR).
- Universes: nifty50, nifty100, nifty200, nifty500. Intervals: day, 60minute, \
30minute, 15minute, 5minute.

RULES YOU MUST FOLLOW
1. If the user does not say otherwise, assume the Nifty 100 on daily bars.
2. "Golden cross" means the faster average crosses ABOVE the slower one. \
"Death cross" is the reverse. The faster average is the one with the SMALLER \
period; put it on the left.
3. If the user gives an entry but no exit, supply the natural inverse: for a \
crossover entry, the opposite crossing; for an RSI-oversold entry, an \
RSI-overbought exit.
4. RSI oversold is conventionally below 30 and overbought above 70 unless the \
user names different levels.
5. A "breakout above the 20-day high" means close is_above highest_high with \
period 20.
6. This system is LONG ONLY. It scans for stocks to buy and for held positions \
to sell. A retail trader in India cannot hold a short equity position overnight, \
so never try to express shorting. If the user asks to short, put that in \
unsupported_request.
7. If the user asks for anything the schema cannot express -- options, futures, \
fundamentals, news sentiment, earnings dates, order placement, position sizing, \
stop-losses, or any indicator not listed above -- do NOT approximate it. Write \
one sentence in unsupported_request naming exactly what is missing, and still \
fill in the closest valid strategy you can for the parts that ARE supported.
8. Keep summary to one sentence that restates the rule, so the trader can check \
you understood.

Return only the JSON object."""


FEW_SHOT = [
    (
        "scan the nifty 100 for stocks where the 6 day moving average crosses "
        "over the 30 day, rank the most recent first",
        {
            "name": "SMA 6/30 crossover",
            "summary": "Buy when the 6-day simple moving average crosses above "
                       "the 30-day, sell when it crosses back below.",
            "universe": "nifty100", "interval": "day",
            "entry_rules": [{"comparison": "crosses_above",
                             "left": {"indicator": "sma", "period": 6},
                             "right": {"indicator": "sma", "period": 30}}],
            "entry_combine": "all",
            "exit_rules": [{"comparison": "crosses_below",
                            "left": {"indicator": "sma", "period": 6},
                            "right": {"indicator": "sma", "period": 30}}],
            "exit_combine": "any",
            "rank_by": "recency", "lookback_bars": 15,
            "unsupported_request": "",
        },
    ),
    (
        "golden cross on the nifty 500 but only if rsi is under 70 so i am not "
        "buying something already overbought",
        {
            "name": "Golden cross with RSI filter",
            "summary": "Buy when the 50-day average crosses above the 200-day "
                       "and RSI(14) is below 70.",
            "universe": "nifty500", "interval": "day",
            "entry_rules": [
                {"comparison": "crosses_above",
                 "left": {"indicator": "sma", "period": 50},
                 "right": {"indicator": "sma", "period": 200}},
                {"comparison": "is_below",
                 "left": {"indicator": "rsi", "period": 14},
                 "right": {"indicator": "number", "value": 70}},
            ],
            "entry_combine": "all",
            "exit_rules": [{"comparison": "crosses_below",
                            "left": {"indicator": "sma", "period": 50},
                            "right": {"indicator": "sma", "period": 200}}],
            "exit_combine": "any",
            "rank_by": "recency", "lookback_bars": 20,
            "unsupported_request": "",
        },
    ),
    (
        "short any stock that gaps down more than 3% on high volume and buy me "
        "puts on it",
        {
            "name": "Gap-down short (not supported)",
            "summary": "Requested a short with options, which this scanner "
                       "cannot express.",
            "universe": "nifty100", "interval": "day",
            "entry_rules": [{"comparison": "is_below",
                             "left": {"indicator": "close"},
                             "right": {"indicator": "lowest_low", "period": 5}}],
            "entry_combine": "all",
            "exit_rules": [], "exit_combine": "any",
            "rank_by": "recency", "lookback_bars": 15,
            "unsupported_request": "Shorting, options, and gap/volume "
                                   "conditions are not supported. Shown instead: "
                                   "stocks closing below their 5-day low.",
        },
    ),
]


def build_messages(request: str) -> tuple[str, list[dict]]:
    """Return (system_prompt, messages) with the worked examples inlined."""
    msgs: list[dict] = []
    for user_text, answer in FEW_SHOT:
        msgs.append({"role": "user", "content": user_text})
        msgs.append({"role": "assistant",
                     "content": json.dumps(answer, separators=(",", ":"))})
    msgs.append({"role": "user", "content": request.strip()})
    return SYSTEM_PROMPT, msgs


def flat_schema() -> dict:
    """JSON Schema handed to whichever provider is in use."""
    return FlatStrategy.model_json_schema()
