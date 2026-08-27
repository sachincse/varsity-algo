"""FastAPI backend for varsity-algo.

Everything the browser calls lives under /api, which means the same URLs work
in development (Vite proxies /api to this server) and in production (this
server hosts the built SPA too). No VITE_API_URL, no CORS, no per-environment
frontend config.

WHAT THIS SERVER WILL AND WILL NOT DO
It will read prices, evaluate a strategy, read your holdings and margins, and
prepare an order. It will not place an order unless the request carries an
explicit confirmation token that the UI only produces after you have seen the
exact order and typed a confirmation. That is a deliberate speed bump on the
one action that spends real money.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S")
log = logging.getLogger("varsity")

from server.routes import bars, health, kite, llm, scan, trade  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    from server.llm.registry import active_key
    from server.kite_client import SESSION
    log.info("varsity-algo starting")
    log.info("  LLM provider   %s", active_key())
    log.info("  Kite API key   %s",
             "set" if SESSION.api_key else "NOT SET (see docs/SETUP.md)")
    log.info("  price source   %s%s", *(lambda s, p: (s, "" if p else "  (auto)"))(*__import__("server.price_source", fromlist=["resolve"]).resolve()))

    # The provider SDKs are imported lazily so a missing one is not fatal, but
    # that pushes a multi-second import onto whichever request touches it
    # first — which is the page-load config call. Warm them here instead.
    #
    # On a BACKGROUND THREAD: uvicorn does not accept connections until the
    # lifespan startup returns, so doing this inline added ~8s before the app
    # would answer at all. Boot time is what the user actually waits on after
    # double-clicking start.bat; the import finishes long before they click.
    def _warm() -> None:
        for mod in ("openai", "anthropic"):
            try:
                __import__(mod)
            except ImportError:
                log.debug("%s not installed", mod)

    threading.Thread(target=_warm, daemon=True, name="warm-sdks").start()

    yield
    log.info("varsity-algo stopped")


app = FastAPI(
    title="varsity-algo",
    description="The Zerodha Varsity SMA-crossover algo, built properly.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def unhandled(request, exc: Exception):
    """Return the message, not a stack trace — the UI shows it to the user."""
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500,
                        content={"detail": f"{type(exc).__name__}: {exc}"})


app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(kite.router, prefix="/api/kite", tags=["kite"])
app.include_router(llm.router, prefix="/api/llm", tags=["llm"])
app.include_router(scan.router, prefix="/api/scan", tags=["scan"])
app.include_router(bars.router, prefix="/api/bars", tags=["bars"])
app.include_router(trade.router, prefix="/api/trade", tags=["trade"])

# Serve the built SPA when it exists. FastAPI checks path operations first, so
# this cannot shadow /api — but it is declared last by convention anyway.
DIST = ROOT / "web" / "dist"
if DIST.is_dir():
    app.frontend("/", directory=str(DIST), fallback="index.html")
    log.info("serving built frontend from %s", DIST)
else:
    @app.get("/")
    def _no_build():
        return {
            "detail": "Frontend is not built.",
            "in_development": "run the Vite dev server and open "
                              "http://localhost:5173",
            "for_production": "cd web && npm install && npm run build",
            "api_docs": "/docs",
        }
