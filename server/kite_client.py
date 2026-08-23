"""Kite Connect session handling.

THE FLOW, WHICH IS THE PART EVERY TUTORIAL GETS SLIGHTLY WRONG

  1. You register an app at https://developers.kite.trade and get an
     api_key and an api_secret.
  2. The user opens  https://kite.zerodha.com/connect/login?v=3&api_key=...
     and logs in with their Zerodha credentials. We never see the password.
  3. Zerodha redirects to your registered redirect URL with
     ?request_token=...&action=login&status=success
  4. You exchange that for an access_token by POSTing to /session/token with
     checksum = SHA256(api_key + request_token + api_secret), plain
     concatenation, no separator, lowercase hex.
  5. The access_token dies at 6 AM IST the next morning. There is no renewal
     for ordinary apps — you log in again.

The request_token is single-use and lives for a couple of minutes. If you
fetch it, wander off, and come back, it is dead: get a fresh one. That single
fact accounts for most "invalid checksum" reports, because an expired token
produces the same error as a wrong secret.
"""
from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
LOGIN_URL = "https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"


class KiteNotConfigured(RuntimeError):
    """No api_key/api_secret in the environment."""


class KiteNotAuthenticated(RuntimeError):
    """Configured, but no live access_token."""


def next_expiry(now: datetime | None = None) -> datetime:
    """Kite tokens expire at 6 AM IST the following morning."""
    now = (now or datetime.now(IST)).astimezone(IST)
    six = datetime.combine(now.date(), dtime(6, 0), tzinfo=IST)
    return six if now < six else six + timedelta(days=1)


def checksum(api_key: str, request_token: str, api_secret: str) -> str:
    """SHA-256 of the three strings concatenated, in that order, no separator.

    Not an HMAC. Any delimiter or reordering still produces valid-looking hex,
    which is why a mistake here shows up as a confusing 403 rather than a
    format error.
    """
    return hashlib.sha256(
        (api_key + request_token + api_secret).encode("utf-8")).hexdigest()


@dataclass
class Session:
    user_id: str = ""
    user_name: str = ""
    email: str = ""
    broker: str = ""
    exchanges: list = field(default_factory=list)
    products: list = field(default_factory=list)
    order_types: list = field(default_factory=list)
    login_time: str = ""
    expires_at: str = ""

    def to_public(self) -> dict:
        """Never includes the access_token, api_secret, or enctoken."""
        return {
            "user_id": self.user_id, "user_name": self.user_name,
            "email": self.email, "broker": self.broker,
            "exchanges": self.exchanges, "products": self.products,
            "order_types": self.order_types,
            "login_time": self.login_time, "expires_at": self.expires_at,
        }


class KiteSession:
    """Holds one broker session for this process.

    This is a single-user tool that runs on your own laptop, so the session
    lives in memory and dies with the process. That is a deliberate choice: an
    access_token written to disk is an access_token that outlives your
    attention. If you restart the server you log in again, which takes about
    fifteen seconds.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._kite = None
        self._session: Session | None = None

    # -- configuration ----------------------------------------------------
    @property
    def api_key(self) -> str:
        return os.getenv("KITE_API_KEY", "").strip()

    @property
    def api_secret(self) -> str:
        return os.getenv("KITE_API_SECRET", "").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def login_url(self) -> str:
        if not self.api_key:
            raise KiteNotConfigured(
                "KITE_API_KEY is not set. Add it to your .env file — see "
                "docs/SETUP.md step 4.")
        return LOGIN_URL.format(api_key=self.api_key)

    # -- session ----------------------------------------------------------
    def is_live(self) -> bool:
        with self._lock:
            if self._kite is None or self._session is None:
                return False
            try:
                exp = datetime.fromisoformat(self._session.expires_at)
            except (ValueError, TypeError):
                return True
            return datetime.now(IST) < exp

    def status(self) -> dict:
        configured = self.is_configured()
        live = self.is_live()
        out = {
            "configured": configured,
            "authenticated": live,
            "api_key_present": bool(self.api_key),
            "api_secret_present": bool(self.api_secret),
            "login_url": self.login_url() if configured else None,
            "profile": self._session.to_public() if (live and self._session) else None,
        }
        if configured and not live:
            out["next_step"] = ("Open the login URL, sign in, then paste the "
                                "request_token from the redirected address bar.")
        return out

    def authenticate(self, request_token: str) -> Session:
        """Exchange a request_token for an access_token."""
        if not self.is_configured():
            raise KiteNotConfigured(
                "KITE_API_KEY and KITE_API_SECRET must both be set in .env.")

        request_token = (request_token or "").strip()
        if not request_token:
            raise ValueError("request_token is empty.")
        if len(request_token) < 8 or " " in request_token:
            raise ValueError(
                "That does not look like a request_token. Copy only the value "
                "between 'request_token=' and the next '&' in the redirected URL.")

        try:
            from kiteconnect import KiteConnect
        except ImportError as e:
            raise RuntimeError(
                "kiteconnect is not installed. Run: pip install kiteconnect") from e

        kite = KiteConnect(api_key=self.api_key)

        # Kite calls this from inside its own request path when it sees a 403
        # with error_type TokenException. Three things trigger it besides the
        # clock: an explicit logout, a master-logout from the Kite web
        # terminal, and the user signing in to another Kite instance. Without
        # the hook, the next scan just fails with a confusing 403.
        kite.set_session_expiry_hook(self._on_expired)

        try:
            # generate_session computes the checksum itself and calls
            # set_access_token internally on success.
            data = kite.generate_session(request_token, api_secret=self.api_secret)
        except Exception as e:
            raise _friendly_kite_error(e) from e

        login_time = data.get("login_time")
        sess = Session(
            user_id=data.get("user_id", ""),
            user_name=data.get("user_name", ""),
            email=data.get("email", ""),
            broker=data.get("broker", ""),
            exchanges=list(data.get("exchanges") or []),
            products=list(data.get("products") or []),
            order_types=list(data.get("order_types") or []),
            login_time=str(login_time) if login_time else "",
            expires_at=next_expiry().isoformat(),
        )
        with self._lock:
            self._kite = kite
            self._session = sess
        return sess

    def _on_expired(self) -> None:
        """Kite told us the token is dead. Drop it so the UI shows re-login."""
        import logging
        logging.getLogger("varsity.kite").warning(
            "Kite session expired or was invalidated elsewhere — clearing it.")
        with self._lock:
            self._kite = None
            self._session = None

    def client(self):
        """The authenticated KiteConnect, or a clear error."""
        with self._lock:
            kite, sess = self._kite, self._session
        if kite is None or sess is None:
            raise KiteNotAuthenticated(
                "Not logged in to Kite. Open the login URL and paste the "
                "request_token.")
        if not self.is_live():
            raise KiteNotAuthenticated(
                "The Kite session expired — tokens die at 6 AM IST. Log in again.")
        return kite

    def logout(self) -> None:
        with self._lock:
            kite = self._kite
            self._kite = None
            self._session = None
        if kite is not None:
            try:
                kite.invalidate_access_token()
            except Exception:
                pass


def _friendly_kite_error(e: Exception) -> Exception:
    """Kite's errors are terse and their causes are usually mundane."""
    msg = str(e)
    low = msg.lower()
    if "checksum" in low or "invalid" in low and "token" in low:
        return ValueError(
            "Kite rejected the login. The usual causes, in order of "
            "likelihood: (1) the request_token was already used or is more "
            "than a few minutes old — get a fresh one from the login URL; "
            "(2) KITE_API_SECRET is wrong or has a stray space; "
            "(3) you pasted the whole URL instead of just the token. "
            f"[Kite said: {msg}]")
    if "api_key" in low:
        return ValueError(f"Kite did not recognise the API key. Check "
                          f"KITE_API_KEY matches your app. [{msg}]")
    return RuntimeError(f"Kite login failed: {msg}")


SESSION = KiteSession()
