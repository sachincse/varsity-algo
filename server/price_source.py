"""Where candles come from — resolved in exactly one place.

This used to be decided twice. The scanner read ``PRICE_SOURCE`` with a default
of ``""`` and fell back to "kite if a session is live, else yfinance"; the
config endpoint read the same variable with a default of ``"yfinance"`` and
never looked at the session at all. So the settings panel could tell you it was
using Yahoo while every scan was pulling from your broker — and with
``PRICE_SOURCE=`` set but empty, which is what .env.example ships, it reported
an empty string and the UI rendered a blank.

One function now answers the question for both.
"""
from __future__ import annotations

import os

VALID = ("yfinance", "kite")


def resolve(explicit: str | None = None) -> tuple[str, bool]:
    """Return ``(source, pinned)``.

    ``pinned`` is True when the choice was forced — by the caller or by
    PRICE_SOURCE in .env — and False when it was inferred from whether a Kite
    session happens to be live. The UI needs that distinction to explain
    itself: "Kite" and "Kite, because you are connected" are different claims.
    """
    from server.kite_client import SESSION

    if explicit and explicit.strip():
        return explicit.strip().lower(), True

    env = os.getenv("PRICE_SOURCE", "").strip().lower()
    if env:
        return env, True

    # The video pulls candles from Kite. Once a session is live we do the same,
    # so prices match the broker's own chart. Without one, fall back to the
    # free end-of-day feed rather than refusing to run.
    return ("kite" if SESSION.is_live() else "yfinance"), False
