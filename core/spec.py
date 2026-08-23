"""The strategy DSL — a small, closed language that the LLM writes and the
engine executes.

WHY A DSL AND NOT GENERATED CODE
The video has an AI coding agent write a Python file and then runs it. That is
fine for a demo and unacceptable for anything touching a funded brokerage
account: a language model that can emit arbitrary code into a process holding
your access token is a remote-code-execution path with a natural-language
prompt as its input. Prompt injection through a stock name, a news headline, or
a pasted strategy description is enough.

So the model never writes code here. It fills in this schema. Every field is
validated, every enum is closed, every number is range-checked, and anything
that does not parse is rejected before it reaches the engine. The worst a
hostile or confused model can do is produce a strategy that is refused, or one
that generates signals you then have to approve by hand.

The language is deliberately small. It covers the video's SMA crossover and a
useful neighbourhood around it, and nothing else.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator

# --------------------------------------------------------------------------
# Indicators
# --------------------------------------------------------------------------
MAX_PERIOD = 400
MIN_PERIOD = 1


class SMA(BaseModel):
    kind: Literal["sma"] = "sma"
    period: int = Field(ge=MIN_PERIOD, le=MAX_PERIOD)

    @property
    def label(self) -> str:
        return f"SMA({self.period})"


class EMA(BaseModel):
    kind: Literal["ema"] = "ema"
    period: int = Field(ge=MIN_PERIOD, le=MAX_PERIOD)

    @property
    def label(self) -> str:
        return f"EMA({self.period})"


class RSI(BaseModel):
    kind: Literal["rsi"] = "rsi"
    period: int = Field(default=14, ge=2, le=MAX_PERIOD)

    @property
    def label(self) -> str:
        return f"RSI({self.period})"


class Price(BaseModel):
    """The bar itself, so you can say 'close crosses above SMA(50)'."""
    kind: Literal["price"] = "price"
    field: Literal["open", "high", "low", "close"] = "close"

    @property
    def label(self) -> str:
        return self.field


class Constant(BaseModel):
    kind: Literal["const"] = "const"
    value: float

    @property
    def label(self) -> str:
        return str(self.value)


class DonchianHigh(BaseModel):
    """Highest high of the last N bars, excluding the current bar."""
    kind: Literal["donchian_high"] = "donchian_high"
    period: int = Field(default=20, ge=2, le=MAX_PERIOD)

    @property
    def label(self) -> str:
        return f"{self.period}-bar high"


class DonchianLow(BaseModel):
    kind: Literal["donchian_low"] = "donchian_low"
    period: int = Field(default=20, ge=2, le=MAX_PERIOD)

    @property
    def label(self) -> str:
        return f"{self.period}-bar low"


Operand = Annotated[
    Union[SMA, EMA, RSI, Price, Constant, DonchianHigh, DonchianLow],
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------
# Conditions
# --------------------------------------------------------------------------
class Crossover(BaseModel):
    """``left`` crosses ``direction`` ``right`` on this bar.

    True only on the bar the cross completes, which is what makes it a signal
    rather than a state.
    """
    type: Literal["crossover"] = "crossover"
    left: Operand
    right: Operand
    direction: Literal["above", "below"]

    def describe(self) -> str:
        return f"{self.left.label} crosses {self.direction} {self.right.label}"


class Comparison(BaseModel):
    """A persistent state, e.g. RSI below 30. True on every bar it holds."""
    type: Literal["comparison"] = "comparison"
    left: Operand
    op: Literal["<", "<=", ">", ">="]
    right: Operand

    def describe(self) -> str:
        return f"{self.left.label} {self.op} {self.right.label}"


class And(BaseModel):
    type: Literal["and"] = "and"
    conditions: list["Condition"] = Field(min_length=1, max_length=6)

    def describe(self) -> str:
        return " AND ".join(f"({c.describe()})" for c in self.conditions)


class Or(BaseModel):
    type: Literal["or"] = "or"
    conditions: list["Condition"] = Field(min_length=1, max_length=6)

    def describe(self) -> str:
        return " OR ".join(f"({c.describe()})" for c in self.conditions)


Condition = Annotated[
    Union[Crossover, Comparison, And, Or],
    Field(discriminator="type"),
]

And.model_rebuild()
Or.model_rebuild()


# --------------------------------------------------------------------------
# The strategy
# --------------------------------------------------------------------------
class StrategySpec(BaseModel):
    """A complete, executable strategy. This is the LLM's output contract."""

    model_config = {"extra": "forbid"}

    name: str = Field(default="Untitled strategy", max_length=80)
    description: str = Field(default="", max_length=400)

    universe: Literal["nifty50", "nifty100", "nifty200", "nifty500"] = "nifty100"
    interval: Literal["day", "60minute", "30minute", "15minute", "5minute"] = "day"

    entry: Condition
    exit: Condition | None = Field(
        default=None,
        description="If omitted, the inverse of a crossover entry is used.")

    direction: Literal["long"] = Field(
        default="long",
        description="Long only. Retail cannot hold short equity overnight in India.")

    rank_by: Literal["recency", "spread", "turnover"] = "recency"
    max_signals: int = Field(default=25, ge=1, le=100)
    lookback_bars: int = Field(
        default=15, ge=1, le=250,
        description="Only report signals that fired within this many bars.")

    min_price: float = Field(default=20.0, ge=0)
    min_median_turnover: float = Field(
        default=5e7, ge=0,
        description="Rupees. Trailing 60-bar median of close x volume.")

    @model_validator(mode="after")
    def _check_warmup(self) -> "StrategySpec":
        if self.max_period() > 400:
            raise ValueError("indicator period exceeds the 400-bar limit")
        return self

    def max_period(self) -> int:
        """Longest lookback any indicator needs, for warm-up sizing."""
        longest = 1

        def walk(node) -> None:
            nonlocal longest
            if isinstance(node, (And, Or)):
                for c in node.conditions:
                    walk(c)
            elif isinstance(node, (Crossover, Comparison)):
                for side in (node.left, node.right):
                    longest = max(longest, getattr(side, "period", 1))

        walk(self.entry)
        if self.exit is not None:
            walk(self.exit)
        return longest

    def describe(self) -> str:
        lines = [f"{self.name}",
                 f"  universe   {self.universe}, {self.interval} bars",
                 f"  entry      {self.entry.describe()}"]
        lines.append(f"  exit       "
                     + (self.exit.describe() if self.exit
                        else "inverse of the entry crossover"))
        lines.append(f"  rank by    {self.rank_by}, "
                     f"newest {self.lookback_bars} bars, "
                     f"max {self.max_signals} rows")
        return "\n".join(lines)


# The canonical example: exactly the strategy from the video.
VARSITY_DEFAULT = StrategySpec(
    name="Varsity SMA 6/30 crossover",
    description="The strategy built in the Zerodha Varsity video.",
    universe="nifty100",
    interval="day",
    entry=Crossover(left=SMA(period=6), right=SMA(period=30), direction="above"),
    exit=Crossover(left=SMA(period=6), right=SMA(period=30), direction="below"),
    rank_by="recency",
)


def json_schema() -> dict:
    """The schema handed to the LLM. Kept in one place so the prompt and the
    validator can never drift apart."""
    return StrategySpec.model_json_schema()
