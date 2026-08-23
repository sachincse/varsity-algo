"""Kite session, portfolio and margin endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.kite_client import (SESSION, KiteNotAuthenticated,
                                KiteNotConfigured)

router = APIRouter()


class LoginBody(BaseModel):
    request_token: str = Field(min_length=1, max_length=200)


@router.get("/status")
def status() -> dict:
    return SESSION.status()


@router.get("/login-url")
def login_url() -> dict:
    try:
        return {"url": SESSION.login_url()}
    except KiteNotConfigured as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/login")
def login(body: LoginBody) -> dict:
    """Exchange a request_token for a live session.

    The token is single-use and lives a couple of minutes, so a stale one and a
    wrong secret produce the same error from Kite. The client explains both.
    """
    token = body.request_token.strip()

    # People paste the whole redirected URL. Rather than reject that, dig the
    # token out of it — it is unambiguous and saves a support round-trip.
    if "request_token=" in token:
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(token).query)
        got = q.get("request_token", [""])[0]
        if got:
            token = got

    try:
        sess = SESSION.authenticate(token)
    except KiteNotConfigured as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"ok": True, "profile": sess.to_public()}


@router.post("/logout")
def logout() -> dict:
    SESSION.logout()
    return {"ok": True}


def _client():
    try:
        return SESSION.client()
    except KiteNotAuthenticated as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


@router.get("/holdings")
def holdings() -> dict:
    k = _client()
    try:
        rows = k.holdings()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kite: {e}") from e
    total_pnl = sum(float(r.get("pnl") or 0) for r in rows)
    invested = sum(float(r.get("average_price") or 0) * float(r.get("quantity") or 0)
                   for r in rows)
    return {"holdings": rows, "count": len(rows),
            "invested": round(invested, 2), "pnl": round(total_pnl, 2)}


@router.get("/positions")
def positions() -> dict:
    k = _client()
    try:
        return {"positions": k.positions()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kite: {e}") from e


@router.get("/margins")
def margins() -> dict:
    k = _client()
    try:
        m = k.margins()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kite: {e}") from e
    equity = (m or {}).get("equity", {}) or {}
    return {"margins": m,
            "available_cash": float(
                (equity.get("available") or {}).get("live_balance") or 0)}


@router.get("/quote")
def quote(instruments: str) -> dict:
    """Live prices. ``instruments`` is a comma-separated list like NSE:INFY."""
    k = _client()
    want = [s.strip() for s in instruments.split(",") if s.strip()][:200]
    if not want:
        raise HTTPException(status_code=400, detail="no instruments given")
    try:
        return {"ltp": k.ltp(want)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kite: {e}") from e
