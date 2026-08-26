"""Record a screencast of the real running app for the tutorial video.

Playwright does not draw the mouse pointer into the recorded video, and a
tutorial where the UI changes with no visible cause is close to useless. So a
fake cursor is injected: a div that listens for the real mouse events
Playwright dispatches, follows them, and flashes a ripple on click.

Everything here drives the ACTUAL app at localhost:8000. Nothing is mocked, so
what the viewer sees is what they will get.

    python tools/record_app.py --out build/clips
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
W, H = 1600, 900

# --------------------------------------------------------------------------
# Fake cursor. Injected before any page script runs, so it survives navigation.
# --------------------------------------------------------------------------
CURSOR_JS = r"""
(() => {
  const install = () => {
    if (document.getElementById('__cursor')) return;
    const style = document.createElement('style');
    style.textContent = `
      #__cursor {
        position: fixed; left: 0; top: 0; width: 22px; height: 22px;
        margin: -3px 0 0 -3px; z-index: 2147483647; pointer-events: none;
        transition: transform .04s linear; will-change: transform;
      }
      #__cursor svg { display:block; filter: drop-shadow(0 1px 3px rgba(0,0,0,.55)); }
      .__ripple {
        position: fixed; z-index: 2147483646; pointer-events: none;
        width: 14px; height: 14px; margin: -7px 0 0 -7px; border-radius: 50%;
        background: rgba(90,169,221,.55); border: 2px solid rgba(90,169,221,.95);
        animation: __rip .5s ease-out forwards;
      }
      @keyframes __rip {
        from { transform: scale(.4); opacity: 1 }
        to   { transform: scale(3.6); opacity: 0 }
      }`;
    document.head.appendChild(style);

    const c = document.createElement('div');
    c.id = '__cursor';
    c.innerHTML =
      '<svg width="22" height="22" viewBox="0 0 22 22">' +
      '<path d="M3 2 L3 17 L7.2 13.2 L10 19.5 L12.6 18.3 L9.9 12.2 L15.5 12z" ' +
      'fill="#fff" stroke="#111" stroke-width="1.2" stroke-linejoin="round"/></svg>';
    document.body.appendChild(c);

    let x = window.innerWidth / 2, y = window.innerHeight / 2;
    const draw = () => { c.style.transform = `translate(${x}px, ${y}px)`; };
    draw();

    // Playwright dispatches genuine mouse events, so listening is enough.
    addEventListener('mousemove', e => { x = e.clientX; y = e.clientY; draw(); }, true);
    addEventListener('mousedown', e => {
      const r = document.createElement('div');
      r.className = '__ripple';
      r.style.left = e.clientX + 'px';
      r.style.top = e.clientY + 'px';
      document.body.appendChild(r);
      setTimeout(() => r.remove(), 520);
    }, true);
  };
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', install);
  else install();
})();
"""

ZOOM_JS = "document.documentElement.style.fontSize = '17px';"


def open_app(page) -> None:
    """networkidle is unreliable here — wait for something real instead."""
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("h1", timeout=30_000)
    page.wait_for_selector("nav button", timeout=30_000)
    page.wait_for_timeout(900)          # let the config fetch paint


class Cam:
    """Thin wrapper that keeps the camera calm: smooth moves, human typing."""

    def __init__(self, page):
        self.p = page
        self.x, self.y = W / 2, H / 2
        self.t0 = time.time()
        self.cues: dict[str, float] = {}

    def mark(self, name: str) -> float:
        """Record how far into THIS clip we are, so the editor can trim and
        time captions against real events instead of guessing."""
        t = round(time.time() - self.t0, 2)
        self.cues[name] = t
        return t

    def beat(self, s: float = 0.7) -> None:
        self.p.wait_for_timeout(int(s * 1000))

    def move_to(self, locator, steps: int = 26) -> tuple[float, float]:
        # locator.click() scrolls into view for you; driving the mouse by hand
        # does not, so an element below the fold yields a bounding box outside
        # the viewport and the click lands on nothing.
        locator.wait_for(state="visible", timeout=60_000)
        locator.scroll_into_view_if_needed()
        self.p.wait_for_timeout(320)              # let smooth-scroll settle
        box = locator.bounding_box()
        if not box:
            raise RuntimeError("element has no box (hidden?)")
        tx = box["x"] + box["width"] / 2
        ty = box["y"] + box["height"] / 2
        if not (0 <= ty <= H):
            raise RuntimeError(f"element still off-screen at y={ty:.0f}")
        self.p.mouse.move(tx, ty, steps=steps)
        self.x, self.y = tx, ty
        return tx, ty

    def click(self, locator, settle: float = 0.8) -> None:
        self.move_to(locator)
        self.beat(0.28)
        self.p.mouse.down()
        self.p.wait_for_timeout(70)
        self.p.mouse.up()
        self.beat(settle)

    def type_in(self, locator, text: str, clear: bool = True) -> None:
        self.click(locator, settle=0.2)
        if clear:
            self.p.keyboard.press("ControlOrMeta+a")
            self.p.keyboard.press("Backspace")
        # press_sequentially is the current API; type() is deprecated.
        locator.press_sequentially(text, delay=42)
        self.beat(0.5)

    def scroll(self, dy: int, steps: int = 18) -> None:
        for _ in range(steps):
            self.p.mouse.wheel(0, dy / steps)
            self.p.wait_for_timeout(16)
        self.beat(0.3)


CUES: dict[str, dict] = {}


def record(out_dir: Path, scan_timeout_ms: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / "_raw"
    if raw.exists():
        shutil.rmtree(raw)
    raw.mkdir(parents=True)

    clips: list[Path] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--force-color-profile=srgb"])

        def new_ctx(name: str):
            ctx = browser.new_context(
                viewport={"width": W, "height": H},
                record_video_dir=str(raw / name),
                record_video_size={"width": W, "height": H},
                color_scheme="dark",
            )
            ctx.add_init_script(CURSOR_JS)
            return ctx

        def finish(ctx, page, name: str) -> Path:
            # The video file is only flushed on context.close(). Reading
            # page.video.path() before that gives you a path to nothing.
            vid = page.video
            ctx.close()
            src = Path(vid.path())
            dst = out_dir / f"{name}.webm"
            if dst.exists():
                dst.unlink()
            shutil.move(str(src), str(dst))
            print(f"  clip: {dst.name}  ({dst.stat().st_size // 1024} KB)")
            return dst

        def cue(cam, name: str) -> None:
            CUES.setdefault(name, {}).update(cam.cues)

        # Cam is created BEFORE open_app so its clock starts when the video
        # does. Cue times are therefore offsets into the recorded file, which
        # is what the editor needs to trim dead lead-in and time captions.

        # ---- clip 1: the Connect tab — the video's login page --------------
        print("recording 01-connect")
        ctx = new_ctx("01")
        page = ctx.new_page()
        page.add_init_script(ZOOM_JS)
        cam = Cam(page)
        open_app(page)
        cam.mark("ready")
        cam.beat(1.6)
        cam.mark("form")
        # A placeholder, not a real key. Enough to show the login link appear.
        cam.type_in(page.get_by_label("API key"), "your_api_key_here")
        cam.beat(0.5)
        cam.type_in(page.get_by_label("API secret"), "your_api_secret")
        cam.beat(0.8)
        cam.mark("loginlink")
        try:
            cam.move_to(page.get_by_role("link", name="Open the Kite login page"))
        except Exception:
            pass
        cam.beat(1.8)
        # Show the token being pasted — the narration describes exactly this,
        # and it gives the shot motion instead of a long freeze.
        cam.mark("token")
        cam.type_in(
            page.get_by_label("Request token"),
            "http://127.0.0.1:8000/kite-redirect?request_token=AbCdEf123456"
            "&action=login&status=success")
        cam.beat(1.6)
        cam.mark("ready_to_login")
        try:
            cam.move_to(page.get_by_role("button", name="Login", exact=True))
        except Exception:
            pass
        cam.beat(2.6)
        cam.mark("end")
        cue(cam, "01-connect")
        clips.append(finish(ctx, page, "01-connect"))

        # ---- clip 2: Settings — every model option, and the data source ----
        print("recording 02-settings")
        ctx = new_ctx("02")
        page = ctx.new_page()
        page.add_init_script(ZOOM_JS)
        cam = Cam(page)
        open_app(page)
        cam.click(page.get_by_role("button", name="Settings", exact=True))
        cam.mark("providers")
        cam.beat(1.6)
        cam.scroll(560)
        cam.beat(1.4)
        cam.mark("pricedata")
        cam.scroll(620)
        cam.beat(2.4)
        cam.mark("end")
        cue(cam, "02-settings")
        clips.append(finish(ctx, page, "02-settings"))

        # ---- clip 3: describe a strategy in English -----------------------
        print("recording 03-strategy")
        ctx = new_ctx("03")
        page = ctx.new_page()
        page.add_init_script(ZOOM_JS)
        cam = Cam(page)
        open_app(page)
        cam.click(page.get_by_role("button", name="Strategy", exact=True))
        cam.beat(0.5)
        cam.mark("typing")
        cam.type_in(page.get_by_label("Your rule"),
                    "golden cross on the nifty 500 but only if RSI is under 70")
        cam.beat(0.6)
        cam.click(page.get_by_role("button", name="Build strategy"), settle=0.4)
        cam.mark("thinking")
        try:
            page.get_by_text("Built by").wait_for(timeout=240_000)
            page.wait_for_timeout(400)
            print("   LLM answered:",
                  " ".join(page.locator(".spec").first.inner_text().split())[:70])
        except Exception:
            print("  ! LLM did not answer in time; using the built-in rule")
            cam.click(page.get_by_role("button", name="Use the video's SMA 6/30"))
        cam.mark("answered")
        cam.beat(0.9)
        cam.scroll(430)
        cam.beat(3.0)
        cam.mark("end")
        cue(cam, "03-strategy")
        clips.append(finish(ctx, page, "03-strategy"))

        # ---- clip 4: Signals — the video's four controls, then a scan ------
        print("recording 04-signals (waits for a real scan)")
        ctx = new_ctx("04")
        page = ctx.new_page()
        page.add_init_script(ZOOM_JS)
        cam = Cam(page)
        open_app(page)
        cam.click(page.get_by_role("button", name="Strategy", exact=True))
        cam.click(page.get_by_role("button", name="Use the video's SMA 6/30"), settle=0.7)
        cam.click(page.get_by_role("button", name="Signals", exact=True))
        cam.beat(0.7)
        cam.mark("controls")
        # Walk the cursor across the four controls so the viewer sees them.
        for lab in ("Short SMA", "Long SMA", "Lookback", "Max rows"):
            cam.move_to(page.get_by_label(lab))
            cam.beat(0.75)
        cam.beat(0.6)
        cam.mark("run")
        cam.click(page.get_by_role("button", name="Generate signals"), settle=0.4)
        page.wait_for_selector("table", timeout=scan_timeout_ms)
        cam.mark("results")
        cam.beat(2.0)
        cam.mark("columns")
        cam.scroll(520)
        cam.beat(2.2)
        cam.scroll(680)
        cam.beat(1.2)
        cam.mark("shortwarning")
        cam.beat(2.6)
        cam.mark("end")
        cue(cam, "04-signals")
        clips.append(finish(ctx, page, "04-signals"))

        # ---- clip 5: order sheet + the guardrails --------------------------
        print("recording 05-orders")
        ctx = new_ctx("05")
        page = ctx.new_page()
        page.add_init_script(ZOOM_JS)
        cam = Cam(page)
        open_app(page)
        cam.click(page.get_by_role("button", name="Strategy", exact=True))
        cam.click(page.get_by_role("button", name="Use the video's SMA 6/30"), settle=0.5)
        cam.click(page.get_by_role("button", name="Signals", exact=True))
        cam.click(page.get_by_role("button", name="Generate signals"), settle=0.4)
        page.wait_for_selector("table", timeout=scan_timeout_ms)
        cam.beat(0.5)
        cam.click(page.get_by_role("button", name="Build an order sheet"))
        cam.mark("sheet")
        cam.beat(0.6)
        cam.type_in(page.get_by_label("Max bars since signal"), "10")
        cam.click(page.get_by_role("button", name="Preview orders"), settle=1.2)
        page.wait_for_selector("tbody tr", timeout=60_000)
        cam.mark("orders")
        cam.beat(2.0)
        cam.mark("guardrail")
        cam.scroll(620)
        cam.beat(2.8)
        cam.mark("end")
        cue(cam, "05-orders")
        clips.append(finish(ctx, page, "05-orders"))

        browser.close()

    shutil.rmtree(raw, ignore_errors=True)
    (out_dir / "cues.json").write_text(json.dumps(CUES, indent=2), encoding="utf-8")
    print("  cues: " + str(out_dir / "cues.json"))
    return clips


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/clips")
    ap.add_argument("--scan-timeout", type=int, default=900_000)
    a = ap.parse_args()
    t0 = time.time()
    made = record(Path(a.out), a.scan_timeout)
    print(f"\n{len(made)} clips in {a.out}  ({time.time() - t0:.0f}s)")
