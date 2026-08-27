"""The round trip back to English, and the linter.

A confirmation step that restates the user's own notation confirms nothing. The
failure it needs to catch is the model producing a valid spec that means
something OTHER than what was asked — "under 70" read as "over 70" validates
perfectly and describes itself in notation the user will nod along to.

So the tests here care about MEANING: that direction survives, that a
comparison is not silently flipped, and that the wording differs enough from
the notation to be a real second look.
"""
from __future__ import annotations

import pytest

from core.explain import explain, lint
from core.spec import VARSITY_DEFAULT, StrategySpec


def spec(**over):
    base = {
        "name": "t", "universe": "nifty100", "interval": "day",
        "entry": {"type": "crossover",
                  "left": {"kind": "sma", "period": 6},
                  "right": {"kind": "sma", "period": 30},
                  "direction": "above"},
        "exit": {"type": "crossover",
                 "left": {"kind": "sma", "period": 6},
                 "right": {"kind": "sma", "period": 30},
                 "direction": "below"},
    }
    base.update(over)
    return StrategySpec.model_validate(base)


# --------------------------------------------------------------------------
# meaning
# --------------------------------------------------------------------------

def test_it_reads_as_english_not_notation():
    text = explain(VARSITY_DEFAULT)
    assert "SMA(" not in text and "crosses" not in text
    assert "6-day average price" in text
    assert text.endswith(".")


def test_direction_is_not_lost():
    up = explain(spec())
    assert "rises above" in up
    down = explain(spec(entry={"type": "crossover",
                               "left": {"kind": "sma", "period": 6},
                               "right": {"kind": "sma", "period": 30},
                               "direction": "below"}))
    assert "falls below" in down
    assert up != down


@pytest.mark.parametrize("op,phrase", [
    ("<", "is below"), ("<=", "is at or below"),
    (">", "is above"), (">=", "is at or above"),
])
def test_every_comparison_reads_correctly(op, phrase):
    """The exact bug this exists to catch: a flipped inequality."""
    s = spec(entry={"type": "comparison",
                    "left": {"kind": "rsi", "period": 14},
                    "op": op, "right": {"kind": "const", "value": 70}})
    text = explain(s)
    assert phrase in text
    for other_op, other in [("<", "is below"), (">", "is above")]:
        if other != phrase and other_op != op:
            assert f"RSI (a 0-100 momentum gauge) {other}" not in text


def test_and_reads_as_and():
    s = spec(entry={"type": "and", "conditions": [
        {"type": "crossover", "left": {"kind": "sma", "period": 50},
         "right": {"kind": "sma", "period": 200}, "direction": "above"},
        {"type": "comparison", "left": {"kind": "rsi", "period": 14},
         "op": "<", "right": {"kind": "const", "value": 70}}]})
    text = explain(s)
    assert " and " in text
    assert "50-day average price rises above" in text
    assert "is below 70" in text


def test_selling_is_described_as_closing_not_shorting():
    """A user reading "sell" as "short" is the single most dangerous
    misunderstanding this app can permit."""
    assert "never a short" in explain(spec())


def test_a_strategy_with_no_exit_says_so_plainly():
    text = explain(spec(exit=None))
    assert "No exit rule" in text
    assert "You decide when to sell" in text


# --------------------------------------------------------------------------
# lint
# --------------------------------------------------------------------------

def test_identical_buy_and_sell_is_flagged():
    s = spec(exit={"type": "crossover",
                   "left": {"kind": "sma", "period": 6},
                   "right": {"kind": "sma", "period": 30},
                   "direction": "above"})
    msgs = [n.message for n in lint(s) if n.level == "warn"]
    assert any("identical" in m for m in msgs), msgs


def test_an_impossible_rsi_threshold_is_flagged():
    """RSI is bounded 0-100. A threshold outside that never fires, and the
    schema has no reason to object."""
    s = spec(entry={"type": "comparison",
                    "left": {"kind": "rsi", "period": 14},
                    "op": ">", "right": {"kind": "const", "value": 150}})
    msgs = [n.message for n in lint(s) if n.level == "warn"]
    assert any("never be met" in m for m in msgs), msgs


def test_a_truncated_wide_scan_is_flagged():
    s = spec(universe="nifty500", max_signals=5)
    msgs = [n.message for n in lint(s)]
    assert any("truncated" in m for m in msgs), msgs


def test_the_video_default_lints_clean():
    """If the shipped default trips its own linter, the linter is wrong."""
    assert [n for n in lint(VARSITY_DEFAULT) if n.level == "warn"] == []
