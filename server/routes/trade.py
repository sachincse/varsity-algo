"""Order preview and placement.

THE SAFETY MODEL, STATED PLAINLY
Placing an order is the only irreversible thing this program does, so it is the
only thing behind three separate locks:

  1. ENABLE_TRADING must be true in .env. Default is false. Turning it on is a
     deliberate act performed in a text editor, not a click.
  2. Every order must be previewed first. The preview mints a one-time token
     bound to the EXACT order — symbol, side, quantity, product. Change any of
     those and the token no longer matches.
  3. The request must carry that token plus the literal word CONFIRM.

The token also expires. If you preview a basket, go to lunch, and come back,
the prices that justified those orders are stale and the tokens are dead. That
is the intended behaviour, not an inconvenience.

Orders are placed ONE AT A TIME. There is no "place all". A basket button is
how people fire twelve orders they meant to read.
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets
import time
from hashlib import sha256

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.kite_client import SESSION, KiteNotAuthenticated

router = APIRouter()
log = logging.getLogger("varsity.trade")

TOKEN_TTL = 180                      # seconds a preview stays actionable
_NONCE = secrets.token_bytes(32)     # per-process; a restart voids all tokens
_ISSUED: dict[str, float] = {}       # token -> issued_at


def trading_enabled() -> bool:
    return os.getenv("ENABLE_TRADING", "false").strip().lower() == "true"


def _fingerprint(o: dict) -> str:
    raw = "|".join(str(o.get(k, "")) for k in
                   ("tradingsymbol", "exchange", "transaction_type",
                    "quantity", "product", "order_type"))
    return hmac.new(_NONCE, raw.encode(), sha256).hexdigest()[:32]


def _mint(o: dict) -> str:
    tok = _fingerprint(o)
    _ISSUED[tok] = time.time()
    return tok


def _check(o: dict, token: str) -> None:
    expected = _fingerprint(o)
    if not hmac.compare_digest(expected, token or ""):
        raise HTTPException(
            status_code=400,
            detail="This order does not match the one you previewed. Preview "
                   "again and confirm the exact order shown.")
    issued = _ISSUED.get(token)
    if issued is None:
        raise HTTPException(status_code=400,
                            detail="Unknown confirmation token. Preview again.")
    if time.time() - issued > TOKEN_TTL:
        _ISSUED.pop(token, None)
        raise HTTPException(
            status_code=400,
            detail=f"That preview is more than {TOKEN_TTL // 60} minutes old, "
                   f"so the prices behind it are stale. Preview again.")


# --------------------------------------------------------------------------
class PreviewBody(BaseModel):
    signals: list[dict] = Field(default_factory=list)
    capital: float = Field(default=1_000_000, gt=0)
    max_positions: int = Field(default=10, ge=1, le=50)
    max_bars_since: int = Field(default=3, ge=0, le=250)
    use_live_cash: bool = True


@router.get("/status")
def status() -> dict:
    return {
        "trading_enabled": trading_enabled(),
        "authenticated": SESSION.is_live(),
        "token_ttl_seconds": TOKEN_TTL,
        "note": "Set ENABLE_TRADING=true in .env to allow order placement. "
                "Preview always works.",
    }


@router.post("/preview")
def preview(body: PreviewBody) -> dict:
    """Build a reviewable order sheet. Places nothing."""
    holdings_map: dict[str, int] = {}
    cash = body.capital
    notes: list[str] = []

    if SESSION.is_live():
        k = SESSION.client()
        try:
            for h in k.holdings():
                q = int(h.get("quantity") or 0) + int(h.get("t1_quantity") or 0)
                if q > 0:
                    holdings_map[h["tradingsymbol"]] = q
        except Exception as e:
            notes.append(f"could not read holdings: {e}")
        if body.use_live_cash:
            try:
                eq = (k.margins() or {}).get("equity", {}) or {}
                live = float((eq.get("available") or {}).get("live_balance") or 0)
                if live > 0:
                    cash = live
                    notes.append(f"using live available cash Rs {live:,.0f}")
            except Exception as e:
                notes.append(f"could not read margins: {e}")
    else:
        notes.append("not logged in to Kite — using the capital figure you "
                     "supplied, and assuming no existing holdings")

    entries = [s for s in body.signals if s.get("side") == "ENTRY"]
    exits = [s for s in body.signals if s.get("side") == "EXIT"]

    orders: list[dict] = []

    # Exits first: they free both cash and slots.
    for s in exits:
        sym = s.get("symbol")
        qty = holdings_map.get(sym, 0)
        if qty > 0:
            orders.append({
                "tradingsymbol": sym, "exchange": "NSE",
                "transaction_type": "SELL", "quantity": int(qty),
                "product": "CNC", "order_type": "MARKET",
                "est_price": float(s.get("price") or 0),
                "est_value": round(float(s.get("price") or 0) * qty, 2),
                "reason": f"exit signal {s.get('signal_date')} "
                          f"({s.get('bars_since')} bars ago)",
            })

    not_held = len(exits) - sum(1 for o in orders if o["transaction_type"] == "SELL")
    if not_held:
        notes.append(f"{not_held} exit signals ignored — you do not hold them, "
                     f"and retail equity delivery cannot be shorted overnight "
                     f"in India")

    held_after = {s: q for s, q in holdings_map.items()
                  if s not in {e.get("symbol") for e in exits}}
    free_slots = body.max_positions - len(held_after)

    if free_slots <= 0:
        notes.append(f"no free slots — holding {len(held_after)} of "
                     f"{body.max_positions}")
    else:
        fresh = [s for s in entries
                 if int(s.get("bars_since", 999)) <= body.max_bars_since
                 and s.get("symbol") not in held_after]
        stale = len(entries) - len(fresh)
        if stale:
            notes.append(f"{stale} entry signals skipped — older than "
                         f"{body.max_bars_since} bars")

        budget = cash / max(body.max_positions, 1)
        for s in fresh[:free_slots]:
            px = float(s.get("price") or 0)
            if px <= 0:
                continue
            qty = int(budget // px)
            if qty <= 0:
                notes.append(f"{s.get('symbol')} skipped — one share is "
                             f"Rs {px:,.0f}, above the Rs {budget:,.0f} slot")
                continue
            orders.append({
                "tradingsymbol": s.get("symbol"), "exchange": "NSE",
                "transaction_type": "BUY", "quantity": qty,
                "product": "CNC", "order_type": "MARKET",
                "est_price": px, "est_value": round(px * qty, 2),
                "reason": f"entry signal {s.get('signal_date')} "
                          f"({s.get('bars_since')} bars ago)",
            })

    for o in orders:
        o["confirm_token"] = _mint(o)

    buy = sum(o["est_value"] for o in orders if o["transaction_type"] == "BUY")
    sell = sum(o["est_value"] for o in orders if o["transaction_type"] == "SELL")
    if buy > cash:
        notes.append(f"buy side Rs {buy:,.0f} exceeds available "
                     f"Rs {cash:,.0f} — place fewer, or reduce quantities")

    return {
        "orders": orders,
        "totals": {"buy": round(buy, 2), "sell": round(sell, 2),
                   "net": round(buy - sell, 2), "cash": round(cash, 2)},
        "notes": notes,
        "trading_enabled": trading_enabled(),
        "token_ttl_seconds": TOKEN_TTL,
        "disclaimer": "Estimated at the last close. Market orders fill at the "
                      "open and can gap. Nothing has been sent.",
    }


class PlaceBody(BaseModel):
    tradingsymbol: str = Field(min_length=1, max_length=30)
    exchange: str = "NSE"
    transaction_type: str = Field(pattern="^(BUY|SELL)$")
    quantity: int = Field(gt=0, le=100_000)
    product: str = Field(default="CNC", pattern="^(CNC|MIS)$")
    order_type: str = Field(default="MARKET", pattern="^(MARKET|LIMIT)$")
    price: float | None = None
    confirm_token: str
    confirm: str = Field(description="Must be the literal string CONFIRM")


@router.post("/place")
def place(body: PlaceBody) -> dict:
    """Place exactly one order. Every guard must pass."""
    if not trading_enabled():
        raise HTTPException(
            status_code=403,
            detail="Order placement is disabled. Set ENABLE_TRADING=true in "
                   ".env and restart the server if you really want this.")

    if body.confirm != "CONFIRM":
        raise HTTPException(status_code=400,
                            detail="confirm must be the literal string CONFIRM")

    order = body.model_dump()
    _check(order, body.confirm_token)

    if body.order_type == "LIMIT" and not body.price:
        raise HTTPException(status_code=400,
                            detail="a LIMIT order needs a price")

    try:
        k = SESSION.client()
    except KiteNotAuthenticated as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    from kiteconnect import KiteConnect

    kwargs = dict(
        variety=KiteConnect.VARIETY_REGULAR,
        exchange=body.exchange,
        tradingsymbol=body.tradingsymbol,
        transaction_type=body.transaction_type,
        quantity=body.quantity,
        product=body.product,
        order_type=body.order_type,
        validity=KiteConnect.VALIDITY_DAY,
        tag="varsity-algo",
    )
    if body.order_type == "LIMIT":
        kwargs["price"] = body.price

    log.warning("PLACING ORDER: %s %s x%d %s",
                body.transaction_type, body.tradingsymbol, body.quantity,
                body.product)
    try:
        order_id = k.place_order(**kwargs)
    except Exception as e:
        raise HTTPException(status_code=502,
                            detail=f"Kite rejected the order: {e}") from e

    _ISSUED.pop(body.confirm_token, None)   # single use

    status_txt, filled, avg = "UNKNOWN", 0, 0.0
    try:
        for h in reversed(k.order_history(order_id) or []):
            status_txt = h.get("status", status_txt)
            filled = int(h.get("filled_quantity") or 0)
            avg = float(h.get("average_price") or 0)
            break
    except Exception:
        pass

    log.warning("order %s -> %s filled=%d avg=%.2f",
                order_id, status_txt, filled, avg)
    return {"ok": True, "order_id": order_id, "status": status_txt,
            "filled_quantity": filled, "average_price": avg,
            "note": "Read back with /api/trade/order/{order_id} — a placed "
                    "order is not a filled order."}


@router.get("/order/{order_id}")
def order_status(order_id: str) -> dict:
    try:
        k = SESSION.client()
    except KiteNotAuthenticated as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    try:
        history = k.order_history(order_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kite: {e}") from e
    latest = history[-1] if history else {}
    return {"order_id": order_id, "status": latest.get("status"),
            "filled_quantity": latest.get("filled_quantity"),
            "average_price": latest.get("average_price"),
            "status_message": latest.get("status_message"),
            "history": history}


@router.get("/orders")
def orders() -> dict:
    try:
        k = SESSION.client()
    except KiteNotAuthenticated as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    try:
        return {"orders": k.orders()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kite: {e}") from e
