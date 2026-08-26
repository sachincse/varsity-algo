"""Each order guard must fire on its own, for its own reason.

WHY THIS FILE EXISTS. The end-to-end check asserted that a tampered order was
refused and that a wrong confirmation word was refused, and both passed. Both
were worthless. ENABLE_TRADING is checked first and defaults to false, so every
one of those requests came back with "Order placement is disabled" — the same
response an empty request would get. The signature and confirmation guards were
never reached, never exercised, and could have been deleted entirely without
failing a single test.

So these tests turn trading ON. That is safe here precisely because there is no
Kite session: a request that clears every guard stops at SESSION.client() with
a 401 and never reaches the broker. Nothing can be placed.

The important assertion is not just that each request fails — it is that each
one fails with its OWN distinct message. Identical failures are how the
original hole hid.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from server.main import app
from server.routes import trade

ORDER = {
    "tradingsymbol": "INFY",
    "exchange": "NSE",
    "transaction_type": "BUY",
    "quantity": 10,
    "product": "CNC",
    "order_type": "MARKET",
}


@pytest.fixture
def armed(monkeypatch):
    """Trading enabled, broker absent."""
    monkeypatch.setenv("ENABLE_TRADING", "true")
    monkeypatch.setattr(trade.SESSION, "is_live", lambda: False, raising=False)
    return TestClient(app)


def payload(**over):
    body = dict(ORDER)
    body["confirm_token"] = trade._mint(dict(ORDER))
    body["confirm"] = "CONFIRM"
    body.update(over)
    return body


def detail(r) -> str:
    d = r.json().get("detail", "")
    return d if isinstance(d, str) else str(d)


# --------------------------------------------------------------------------
# the outer gate
# --------------------------------------------------------------------------

def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_TRADING", raising=False)
    r = TestClient(app).post("/api/trade/place", json=payload())
    assert r.status_code == 403
    assert "disabled" in detail(r).lower()


# --------------------------------------------------------------------------
# the guards behind it — each reached only because trading is on
# --------------------------------------------------------------------------

def test_wrong_confirmation_word(armed):
    r = armed.post("/api/trade/place", json=payload(confirm="yes"))
    assert r.status_code == 400
    assert "CONFIRM" in detail(r)
    assert "disabled" not in detail(r).lower()


def test_tampered_quantity_breaks_the_signature(armed):
    """The signature covers the quantity, so raising it must invalidate it."""
    r = armed.post("/api/trade/place", json=payload(quantity=ORDER["quantity"] * 100))
    assert r.status_code in (400, 403)
    assert "disabled" not in detail(r).lower()


@pytest.mark.parametrize("field,value", [
    ("tradingsymbol", "RELIANCE"),
    ("transaction_type", "SELL"),
    ("product", "MIS"),
    ("order_type", "LIMIT"),
])
def test_every_signed_field_is_actually_signed(armed, field, value):
    """Changing any signed field must invalidate the token.

    Parametrised because a signature that covers only some of the fields it
    claims to cover is the sort of thing that looks fine until the one field
    you forgot is the one that matters.
    """
    body = payload(**{field: value})
    if field == "order_type":
        body["price"] = 1500.0        # so a LIMIT order fails on the signature,
                                      # not on the missing-price check
    r = armed.post("/api/trade/place", json=body)
    assert r.status_code in (400, 403), f"{field} is not covered by the signature"
    assert "disabled" not in detail(r).lower()


def test_unknown_token(armed):
    r = armed.post("/api/trade/place", json=payload(confirm_token="nope"))
    assert r.status_code in (400, 403)
    assert "disabled" not in detail(r).lower()


def test_token_expires(armed, monkeypatch):
    body = payload()
    monkeypatch.setitem(trade._ISSUED, body["confirm_token"],
                        time.time() - (trade.TOKEN_TTL + 30))
    r = armed.post("/api/trade/place", json=body)
    assert r.status_code in (400, 403)
    assert "disabled" not in detail(r).lower()


# --------------------------------------------------------------------------
# the point of the whole file
# --------------------------------------------------------------------------

def test_a_fully_valid_order_stops_at_the_broker(armed):
    """Clears every guard, then dies for lack of a session — placing nothing.

    This is what proves the guards above were genuinely reached. If this
    returned 403-disabled like everything else, the suite would be measuring
    the outer gate over and over.
    """
    r = armed.post("/api/trade/place", json=payload())
    assert r.status_code == 401, f"expected to reach the broker, got {detail(r)}"
    assert "disabled" not in detail(r).lower()


def test_each_guard_fails_differently(armed, monkeypatch):
    """The regression guard for the original defect.

    Every rejection reason must be distinguishable. When they all collapsed to
    one message, three tests were passing on the strength of a fourth.
    """
    # Order matters here, and subtly. The token is a deterministic fingerprint
    # of the order fields, so _mint is idempotent: every payload() for the same
    # order returns the SAME token and refreshes its issued-at. Ageing a token
    # up front and then building the other cases silently un-ages it. Each case
    # therefore has to be posted immediately after its own setup.
    reasons = {}
    reasons["wrong word"] = detail(
        armed.post("/api/trade/place", json=payload(confirm="yes")))
    reasons["bad token"] = detail(
        armed.post("/api/trade/place", json=payload(confirm_token="nope")))

    stale = payload()
    monkeypatch.setitem(trade._ISSUED, stale["confirm_token"],
                        time.time() - (trade.TOKEN_TTL + 30))
    reasons["expired"] = detail(armed.post("/api/trade/place", json=stale))

    reasons["valid"] = detail(armed.post("/api/trade/place", json=payload()))
    assert len(set(reasons.values())) == len(reasons), (
        "guards are indistinguishable, so some are not really being tested: "
        f"{reasons}")
