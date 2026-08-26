"""Assemble the tutorial video from recorded clips + generated cards.

    python tools/record_app.py --out build/clips     # capture the real app
    python tools/build_video.py                      # produce build/varsity-algo-tutorial.mp4

Design notes that matter for a SOFTWARE tutorial specifically:

* Output is 1600x900, the native capture size. Upscaling to 1080p would only
  soften the UI text, which is the entire point of the video.
* Captions are rendered as PNG strips in PIL and composited with ffmpeg's
  overlay filter, rather than drawtext. drawtext on Windows means escaping a
  drive-letter colon inside a filter argument, and gives far less typographic
  control than PIL.
* The "thinking" stretch while a local model answers is sped up rather than
  cut, so viewers see that it takes real time without sitting through it.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import narration

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
CLIPS = BUILD / "clips"
WORK = BUILD / "work"
OUT = BUILD / "varsity-algo-tutorial.mp4"

W, H = 1600, 900
FPS = 25

# palette — matches the app so cards and screencast feel like one thing
BG = (14, 16, 19)
PANEL = (23, 26, 31)
INK = (230, 233, 238)
INK2 = (170, 178, 191)
INK3 = (120, 129, 143)
ACCENT = (90, 169, 221)
BUY = (76, 186, 139)
SELL = (224, 122, 104)
WARN = (212, 164, 78)
RULE = (38, 43, 51)

F = "C:/Windows/Fonts/"


def font(name: str, size: int):
    return ImageFont.truetype(F + name, size)


UI = lambda s: font("segoeui.ttf", s)
UIB = lambda s: font("segoeuib.ttf", s)
UIL = lambda s: font("segoeuil.ttf", s)
MONO = lambda s: font("CascadiaMono.ttf", s)


def run(args: list[str]) -> None:
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        print("FFMPEG FAILED:", " ".join(args[:9]), "...")
        print(r.stderr[-2500:])
        sys.exit(1)


def probe_duration(p: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(r.stdout.strip())


# ==========================================================================
# Cards
# ==========================================================================
def wrap(draw, text: str, fnt, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=fnt) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def card(path: Path, *, eyebrow="", title="", body="", bullets=None,
         mono=None, accent=ACCENT, big=None) -> None:
    """A full-frame card. Measured first, then drawn vertically centred —
    content pinned to the top of a 900px frame reads as a mistake."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    x = 150
    inner = W - 2 * x

    title_lines = wrap(d, title, UIB(58), inner) if title else []
    body_lines = wrap(d, body, UIL(30), inner - 60) if body else []
    bullet_lines = [wrap(d, b, UI(28), inner - 46) for b in (bullets or [])]
    mono_lines = (mono if isinstance(mono, list) else [mono]) if mono else []

    h = 0
    if eyebrow:
        h += 46
    if title_lines:
        h += 74 * len(title_lines) + 14
    if big:
        h += 130
    if body_lines:
        h += 45 * len(body_lines) + 14
    for bl in bullet_lines:
        h += 42 * len(bl) + 12
    if mono_lines:
        h += 34 * len(mono_lines) + 52

    y = max(120, (H - h) // 2 - 20)

    if eyebrow:
        d.text((x, y), eyebrow.upper(), font=UIB(19), fill=accent)
        y += 46
    for ln in title_lines:
        d.text((x, y), ln, font=UIB(58), fill=INK)
        y += 74
    if title_lines:
        y += 14
    if big:
        d.text((x, y), big, font=MONO(96), fill=accent)
        y += 130
    for ln in body_lines:
        d.text((x, y), ln, font=UIL(30), fill=INK2)
        y += 45
    if body_lines:
        y += 14
    for bl in bullet_lines:
        d.ellipse([x + 4, y + 14, x + 12, y + 22], fill=accent)
        for ln in bl:
            d.text((x + 32, y), ln, font=UI(28), fill=INK2)
            y += 42
        y += 12
    if mono_lines:
        by0 = y + 8
        bh = 34 * len(mono_lines) + 44
        d.rounded_rectangle([x, by0, W - x, by0 + bh], 10,
                            fill=PANEL, outline=RULE, width=1)
        ty = by0 + 22
        for ln in mono_lines:
            col = INK3 if ln.strip().startswith("#") else INK
            d.text((x + 26, ty), ln, font=MONO(24), fill=col)
            ty += 34

    d.rectangle([0, H - 5, W, H], fill=accent)
    img.save(path)


def caption_strip(path: Path, text: str, sub: str = "", accent=ACCENT) -> None:
    """A lower-third caption with an alpha channel, for overlay."""
    pad, radius = 30, 12
    tmp = Image.new("RGBA", (10, 10)); dtmp = ImageDraw.Draw(tmp)
    fnt, sfnt = UIB(31), UI(23)
    lines = wrap(dtmp, text, fnt, W - 300)
    slines = wrap(dtmp, sub, sfnt, W - 300) if sub else []

    h = pad * 2 + 42 * len(lines) + (32 * len(slines) + 8 if slines else 0)
    img = Image.new("RGBA", (W, h + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([70, 0, W - 70, h], radius, fill=(14, 16, 19, 234))
    d.rounded_rectangle([70, 0, 76, h], 3, fill=accent + (255,))

    y = pad - 4
    for ln in lines:
        d.text((104, y), ln, font=fnt, fill=INK + (255,))
        y += 42
    if slines:
        y += 6
        for ln in slines:
            d.text((104, y), ln, font=sfnt, fill=INK2 + (255,))
            y += 32
    img.save(path)


# ==========================================================================
# Terminal typing animation
# ==========================================================================
def terminal_clip(out: Path, title: str, lines: list[tuple[str, str]],
                  hold: float = 2.2) -> Path:
    """lines = [(kind, text)] where kind is 'cmd' | 'out' | 'ok' | 'note'."""
    frames = WORK / ("term_" + out.stem)
    if frames.exists():
        shutil.rmtree(frames)
    frames.mkdir(parents=True)

    base = Image.new("RGB", (W, H), BG)
    d0 = ImageDraw.Draw(base)
    d0.rounded_rectangle([110, 120, W - 110, H - 120], 14,
                         fill=(10, 12, 15), outline=RULE, width=1)
    d0.rounded_rectangle([110, 120, W - 110, 176], 14, fill=(28, 32, 38))
    d0.rectangle([110, 160, W - 110, 176], fill=(28, 32, 38))
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d0.ellipse([144 + i * 26, 141, 156 + i * 26, 153], fill=c)
    d0.text((W // 2 - d0.textlength(title, font=UI(21)) // 2, 138),
            title, font=UI(21), fill=INK3)
    d0.rectangle([0, H - 5, W, H], fill=ACCENT)

    fm = MONO(25)
    x0, y0, lh = 152, 214, 38
    n = 0
    done: list[tuple[str, str]] = []

    def paint(partial: str | None = None, kind: str = "cmd", cursor=True):
        nonlocal n
        img = base.copy()
        d = ImageDraw.Draw(img)
        y = y0
        for k, t in done:
            _line(d, x0, y, k, t, fm)
            y += lh
        if partial is not None:
            w = _line(d, x0, y, kind, partial, fm)
            if cursor:
                d.rectangle([x0 + w + 4, y + 3, x0 + w + 15, y + 30],
                            fill=(200, 210, 220))
        img.save(frames / f"{n:05d}.png")
        n += 1

    for kind, text in lines:
        if kind == "cmd":
            for i in range(len(text) + 1):
                paint(text[:i], kind)
                if text[i - 1:i] == " ":
                    paint(text[:i], kind)          # tiny pause at spaces
            for _ in range(int(0.45 * FPS)):
                paint(text, kind)
        else:
            for _ in range(max(2, int(0.30 * FPS))):
                paint(text, kind, cursor=False)
        done.append((kind, text))

    for _ in range(int(hold * FPS)):
        paint(None)

    run(["ffmpeg", "-v", "error", "-framerate", str(FPS),
         "-i", str(frames / "%05d.png"),
         "-c:v", "libx264", "-preset", "slow", "-crf", "17",
         "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-y", str(out)])
    shutil.rmtree(frames, ignore_errors=True)
    return out


def _line(d, x, y, kind, text, fm) -> float:
    if kind == "cmd":
        d.text((x, y), ">", font=fm, fill=ACCENT)
        d.text((x + 26, y), text, font=fm, fill=INK)
        return 26 + d.textlength(text, font=fm)
    col = {"ok": BUY, "note": INK3, "warn": WARN}.get(kind, INK2)
    d.text((x + 26, y), text, font=fm, fill=col)
    return 26 + d.textlength(text, font=fm)


def still_clip(out: Path, png: Path, seconds: float) -> Path:
    run(["ffmpeg", "-v", "error", "-loop", "1", "-framerate", str(FPS),
         "-t", f"{seconds}", "-i", str(png),
         "-c:v", "libx264", "-preset", "slow", "-crf", "17",
         "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-y", str(out)])
    return out


# ==========================================================================
# Screencast processing
# ==========================================================================
def screencast(out: Path, src: Path, captions: list[dict],
               trim_from: float = 0.0,
               speed: tuple[float, float, float] | None = None) -> Path:
    """Normalise a webm clip to mp4, trim its lead-in, optionally accelerate a
    stretch, and burn on captions.

    ``trim_from`` and ``speed`` are in ORIGINAL clip time (the cue points the
    recorder emitted). Caption ``t`` values are too — this function maps them
    through the trim and the speed change, so a caption stays glued to the
    moment it describes instead of drifting.
    """
    def to_out(t: float) -> float:
        t -= trim_from
        if speed is None:
            return max(0.0, t)
        s0, e0, f = speed[0] - trim_from, speed[1] - trim_from, speed[2]
        if t <= s0:
            return max(0.0, t)
        if t <= e0:
            return s0 + (t - s0) / f
        return s0 + (e0 - s0) / f + (t - e0)

    stage = WORK / (out.stem + "_a.mp4")
    args = ["ffmpeg", "-v", "error"]
    if trim_from > 0:
        args += ["-ss", f"{trim_from}"]
    args += ["-i", str(src)]

    if speed:
        s0, e0, f = speed[0] - trim_from, speed[1] - trim_from, speed[2]
        vf = (f"[0:v]trim=0:{s0},setpts=PTS-STARTPTS[a];"
              f"[0:v]trim={s0}:{e0},setpts=(PTS-STARTPTS)/{f}[b];"
              f"[0:v]trim={e0},setpts=PTS-STARTPTS[c];"
              f"[a][b][c]concat=n=3:v=1:a=0[v]")
        args += ["-filter_complex", vf, "-map", "[v]"]

    args += ["-c:v", "libx264", "-preset", "slow", "-crf", "18",
             "-tune", "animation", "-pix_fmt", "yuv420p",
             "-r", str(FPS), "-y", str(stage)]
    run(args)

    dur = probe_duration(stage)
    if not captions:
        shutil.move(str(stage), str(out))
        return out

    inputs, filt, prev, shown = ["-i", str(stage)], [], "0:v", 0
    for i, c in enumerate(captions):
        t0 = to_out(c["t"])
        t1 = min(t0 + c.get("dur", 5.0), dur - 0.15)
        if t1 - t0 < 1.0:
            # Never let a caption fall off the end of its own clip.
            print(f"    ! caption dropped (past end of {out.stem}): "
                  f"{c['text'][:48]}")
            continue
        png = WORK / f"{out.stem}_cap{i}.png"
        caption_strip(png, c["text"], c.get("sub", ""), c.get("accent", ACCENT))
        inputs += ["-i", str(png)]
        lbl = f"v{i}"
        filt.append(
            f"[{prev}][{len(inputs)//2 - 1}:v]overlay=x=0:y=H-h-46:"
            f"enable='between(t,{t0:.2f},{t1:.2f})'[{lbl}]")
        prev = lbl
        shown += 1

    if not filt:
        shutil.move(str(stage), str(out))
        return out

    run(["ffmpeg", "-v", "error"] + inputs +
        ["-filter_complex", ";".join(filt), "-map", f"[{prev}]",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18",
         "-tune", "animation", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-y", str(out)])
    stage.unlink(missing_ok=True)
    return out


def extend_to(clip: Path, target: float) -> Path:
    """Hold the final frame until ``target`` seconds.

    Used when the narration for a segment outlasts the footage. Freezing is
    the right move rather than slowing the clip down: the last frame is the
    compiled strategy, or the results table, or the order sheet — precisely
    the thing the voice is talking about while it holds.
    """
    have = probe_duration(clip)
    if target <= have + 0.05:
        return clip
    out = clip.with_name(clip.stem + "_ext.mp4")
    run(["ffmpeg", "-v", "error", "-i", str(clip),
         "-vf", f"tpad=stop_mode=clone:stop_duration={target - have:.2f}",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-y", str(out)])
    clip.unlink(missing_ok=True)
    return out


def mux_narration(video: Path, out: Path, starts: dict[str, float],
                  vo: dict[str, dict]) -> None:
    """Lay each narration line onto the finished picture at its segment start.

    The offsets must account for the crossfades — every join overlaps by
    ``fade`` seconds, so segment starts are NOT a running sum of durations.
    """
    ins, filt, labels = ["-i", str(video)], [], []
    for i, (seg, t) in enumerate(sorted(starts.items(), key=lambda kv: kv[1])):
        if seg not in vo:
            continue
        ins += ["-i", str(vo[seg]["path"])]
        lbl = f"a{i}"
        filt.append(f"[{len(ins)//2 - 1}:a]adelay={int(t * 1000)}|{int(t * 1000)}[{lbl}]")
        labels.append(f"[{lbl}]")

    filt.append(f"{''.join(labels)}amix=inputs={len(labels)}:"
                f"normalize=0:dropout_transition=0[mixed]")
    filt.append("[mixed]alimiter=limit=0.95,aresample=48000[aout]")

    run(["ffmpeg", "-v", "error"] + ins +
        ["-filter_complex", ";".join(filt),
         "-map", "0:v", "-map", "[aout]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", "-shortest", "-y", str(out)])


def concat_xfade(segments: list[Path], out: Path, fade: float = 0.4) -> None:
    """Crossfade segments together. The concat demuxer would be cheaper but
    cuts hard, and hard cuts between a card and a screencast look like a
    glitch rather than an edit."""
    durs = [probe_duration(p) for p in segments]
    inputs = []
    for p in segments:
        inputs += ["-i", str(p)]

    filt, prev, offset = [], "0:v", durs[0] - fade
    for i in range(1, len(segments)):
        lbl = f"x{i}"
        filt.append(f"[{prev}][{i}:v]xfade=transition=fade:"
                    f"duration={fade}:offset={offset:.3f}[{lbl}]")
        prev = lbl
        offset += durs[i] - fade

    run(["ffmpeg", "-v", "error"] + inputs +
        ["-filter_complex", ";".join(filt), "-map", f"[{prev}]",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart",
         "-y", str(out)])


# ==========================================================================
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", default=str(CLIPS))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--revoice", action="store_true",
                    help="re-synthesise the narration")
    a = ap.parse_args()

    clips = Path(a.clips)
    for f in ("01-connect", "02-settings", "03-strategy", "04-signals",
              "05-orders"):
        if not (clips / f"{f}.webm").exists():
            sys.exit(f"missing {f}.webm — run tools/record_app.py first")

    cues = json.loads((clips / "cues.json").read_text(encoding="utf-8")) \
        if (clips / "cues.json").exists() else {}

    def C(clip: str, name: str, default: float) -> float:
        return float(cues.get(clip, {}).get(name, default))

    WORK.mkdir(parents=True, exist_ok=True)

    # Narration first — it decides how long every segment has to be.
    print("synthesising narration")
    vo = narration.synth_all(BUILD / "vo", force=a.revoice)
    def want(name: str, floor: float) -> float:
        return max(floor, vo.get(name, {}).get("dur", 0.0))

    seg: list[Path] = []
    order: list[str] = []

    def add_named(name: str, p: Path) -> None:
        add(p, name)

    def add(p: Path, name: str) -> None:
        p = extend_to(p, want(name, 0.0))
        seg.append(p)
        order.append(name)
        n = vo.get(name, {}).get("dur", 0)
        print(f"  {len(seg):02d}. {name:5s} {probe_duration(p):6.2f}s"
              f"   voice {n:5.2f}s")

    print("building segments")

    # ---- 1. title ---------------------------------------------------------
    card(WORK / "c1.png",
         eyebrow="A trading scanner you can actually run",
         title="varsity-algo",
         body="Describe a strategy in plain English. Scan the Nifty universe. "
              "Review every order before it is placed.",
         mono=["github.com/sachincse/varsity-algo"])
    add_named("s01", still_clip(WORK / "s01.mp4", WORK / "c1.png", want("s01", 5.0)))

    # ---- 2. what you need -------------------------------------------------
    card(WORK / "c2.png", eyebrow="Step 1  \u00b7  What you need",
         title="Two free installs",
         bullets=["Python 3.11 or newer  \u2014  python.org/downloads",
                  "Node.js 20.19+ or 22.12+  \u2014  nodejs.org"],
         mono=["# on the Python installer, tick this box:",
               "  [x] Add python.exe to PATH"], accent=BUY)
    add_named("s02", still_clip(WORK / "s02.mp4", WORK / "c2.png", want("s02", 8.5)))

    # ---- 3. install terminal ---------------------------------------------
    add_named("s03", terminal_clip(WORK / "s03.mp4", "Command Prompt", [
        ("note", "# get the code"),
        ("cmd", "git clone https://github.com/sachincse/varsity-algo"),
        ("out", "Cloning into 'varsity-algo'..."),
        ("cmd", "cd varsity-algo"),
        ("note", ""),
        ("note", "# then just double-click start.bat"),
        ("cmd", "start.bat"),
        ("ok", "[ok] Python 3.11.9"),
        ("ok", "[ok] virtual environment"),
        ("ok", "[ok] Python packages"),
        ("ok", "[ok] dashboard"),
        ("out", ""),
        ("out", "Starting. Your browser will open in a moment."),
    ], hold=2.6))

    # ---- 4. Connect: the video's login page -------------------------------
    c_form = C("01-connect", "form", 3.0)
    c_link = C("01-connect", "loginlink", 10.5)
    c_tok = C("01-connect", "token", 13.1)
    add_named("s04", screencast(WORK / "s04.mp4", clips / "01-connect.webm", [
        {"t": c_form + 0.4, "dur": 5.0,
         "text": "API key, API secret, request token — the video's login page",
         "sub": "Typed here they stay in memory. Put them in .env to keep them."},
        {"t": c_link + 0.3, "dur": 4.6,
         "text": "The login link builds itself from your key",
         "sub": "Sign in at Zerodha; it sends you back with a token.",
         "accent": BUY},
        {"t": c_tok + 1.6, "dur": 5.6,
         "text": "Paste the whole redirected address — the token is pulled out",
         "sub": "It is single-use and expires in minutes. If login fails, that is why.",
         "accent": WARN},
    ], trim_from=max(0.0, C("01-connect", "ready", 1.4) - 0.7)))

    # ---- 5. Settings: providers + the data source -------------------------
    s_prov = C("02-settings", "providers", 3.0)
    s_price = C("02-settings", "pricedata", 8.0)
    add_named("s05", screencast(WORK / "s05.mp4", clips / "02-settings.webm", [
        {"t": s_prov + 0.6, "dur": 5.0,
         "text": "Not connected yet? It runs on free end-of-day data",
         "sub": "So you can try everything before paying for anything."},
        {"t": s_price + 0.4, "dur": 5.0,
         "text": "Kite once you connect, Yahoo until then",
         "sub": "Set PRICE_SOURCE in .env to force either one."},
    ], trim_from=max(0.0, s_prov - 1.4)))

    # ---- 6. free LLM ------------------------------------------------------
    card(WORK / "c6.png", eyebrow="Optional",
         title="Add a free language model",
         body="Only used to turn your English into a strategy. Pick one \u2014 "
              "all three are free and need no credit card.",
         bullets=["Groq  \u2014  console.groq.com/keys",
                  "Google Gemini  \u2014  aistudio.google.com/apikey",
                  "OpenRouter  \u2014  openrouter.ai/keys"],
         mono=["# paste into the .env file, then restart",
               "LLM_PROVIDER=groq",
               "GROQ_API_KEY=gsk_your_key_here"], accent=BUY)
    add_named("s06", still_clip(WORK / "s06.mp4", WORK / "c6.png", want("s06", 10.0)))

    card(WORK / "c6b.png", eyebrow="Or run it entirely offline",
         title="No key. No cost. No data leaves your laptop.",
         body="Ollama runs an open-weight model on your own machine. "
              "This tutorial was recorded using exactly this.",
         mono=["# install from ollama.com/download, then:",
               "ollama pull qwen3:8b",
               "",
               "# .env",
               "LLM_PROVIDER=ollama",
               "LLM_MODEL=qwen3:8b"], accent=WARN)
    add_named("s06b", still_clip(WORK / "s06b.mp4", WORK / "c6b.png",
                                 want("s06b", 9.5)))

    # ---- 7. describe in English ------------------------------------------
    t_type = C("03-strategy", "typing", 4.0)
    t_think = C("03-strategy", "thinking", 11.9)
    t_ans = C("03-strategy", "answered", 39.4)
    add_named("s07", screencast(WORK / "s07.mp4", clips / "03-strategy.webm", [
        {"t": t_type + 0.6, "dur": 5.2,
         "text": "Type the rule the way you would say it out loud",
         "sub": "No syntax to learn."},
        {"t": t_think + 0.4, "dur": 4.2,
         "text": "A 7-billion-parameter model, running locally on this laptop",
         "sub": "Sped up here \u2014 it really took about 28 seconds.",
         "accent": WARN},
        {"t": t_ans + 1.2, "dur": 6.0,
         "text": "It never writes code \u2014 it fills a fixed schema",
         "sub": "Anything that fails validation is rejected before it runs.",
         "accent": BUY},
    ], trim_from=max(0.0, t_type - 1.6),
       speed=(t_think + 1.2, t_ans - 0.6, 3.2)))

    # ---- 8. Signals: the four controls, then the scan ---------------------
    g_ctrl = C("04-signals", "controls", 5.0)
    g_run = C("04-signals", "run", 9.0)
    g_res = C("04-signals", "results", 27.0)
    g_cols = C("04-signals", "columns", 30.0)
    g_warn = C("04-signals", "shortwarning", 36.0)
    add_named("s08", screencast(WORK / "s08.mp4", clips / "04-signals.webm", [
        {"t": g_ctrl + 0.5, "dur": 4.6,
         "text": "Short SMA, Long SMA, Lookback, Max \u2014 as in the video",
         "sub": "They edit the strategy directly."},
        {"t": g_run + 1.6, "dur": 4.4,
         "text": "The first scan downloads every symbol in the universe",
         "sub": "A few minutes once, then cached and near-instant."},
        {"t": g_cols + 0.4, "dur": 5.2,
         "text": "Close, SMA(6) and SMA(30) on every row",
         "sub": "So you can check the crossover is real, not take it on trust.",
         "accent": BUY},
        {"t": g_warn - 0.4, "dur": 5.2,
         "text": "BEARISH means sell what you own \u2014 never a short",
         "sub": "Retail cannot hold a short equity position overnight in India.",
         "accent": SELL},
    ], trim_from=max(0.0, g_ctrl - 1.8),
       speed=(g_run + 6.0, max(g_run + 7.0, g_res - 1.5), 3.0)))

    # ---- 9. orders --------------------------------------------------------
    o_sheet = C("05-orders", "sheet", 14.7)
    o_ord = C("05-orders", "orders", 20.6)
    o_guard = C("05-orders", "guardrail", 22.4)
    add_named("s09", screencast(WORK / "s09.mp4", clips / "05-orders.webm", [
        {"t": o_sheet + 0.8, "dur": 4.4,
         "text": "Signals become a sized order sheet",
         "sub": "Equal weight across your open slots."},
        {"t": o_ord + 0.6, "dur": 4.6,
         "text": "Order placement is OFF until you turn it on in .env",
         "sub": "Preview always works. Nothing is ever sent by surprise.",
         "accent": BUY},
        {"t": o_guard + 1.4, "dur": 5.0,
         "text": "One order at a time. There is no 'place all'.",
         "sub": "Each needs a fresh preview token and a typed confirmation.",
         "accent": WARN},
    ], trim_from=max(0.0, o_sheet - 2.2)))

    # ---- 10. the honest part ----------------------------------------------
    card(WORK / "c10.png", eyebrow="Before you trade any of this",
         title="The strategy does not beat the index",
         body="SMA 6/30 on the Nifty 100, tested 2011\u20132026 with next-open "
              "fills, real Zerodha charges and a point-in-time universe:",
         mono=["  the rule, honestly tested      1.92%  a year",
               "  Nifty 100 index fund          10.70%  a year",
               "  same stocks, no timing rule   11.90%  a year"],
         accent=SELL)
    add_named("s10", still_clip(WORK / "s10.mp4", WORK / "c10.png", want("s10", 11.0)))

    card(WORK / "c11.png", eyebrow="So what is it for",
         title="A lens, not a system",
         body="The scanner is genuinely useful for seeing what is moving. "
              "The machinery around it \u2014 cost modelling, leak-free testing, "
              "order guardrails \u2014 is the part worth keeping.",
         bullets=["44 tests, including a future-scramble causality proof",
                  "Full backtest and evidence in the README"])
    add_named("s11", still_clip(WORK / "s11.mp4", WORK / "c11.png", want("s11", 9.5)))

    # ---- 11. end ----------------------------------------------------------
    card(WORK / "c12.png", eyebrow="MIT licensed  \u00b7  free forever",
         title="Get it",
         big="\u2193",
         mono=["github.com/sachincse/varsity-algo",
               "",
               "# setup guide, every error message, and the fix",
               "docs/SETUP.md"])
    add_named("s12", still_clip(WORK / "s12.mp4", WORK / "c12.png", want("s12", 7.0)))

    print("\nstitching with crossfades")
    silent = WORK / "_silent.mp4"
    fade = 0.4
    concat_xfade(seg, silent, fade=fade)

    # Where each segment lands on the FINAL timeline. Crossfades overlap the
    # joins, so this is a running sum minus one fade per join — not a plain
    # cumulative total.
    starts, t = {}, 0.0
    for i, (p, name) in enumerate(zip(seg, order)):
        starts[name] = t
        t += probe_duration(p) - (fade if i < len(seg) - 1 else 0)

    print("laying narration onto the timeline")
    out = Path(a.out)
    mux_narration(silent, out, starts, vo)
    silent.unlink(missing_ok=True)

    dur = probe_duration(out)
    has_audio = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name,channels", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True).stdout.strip()
    print(f"\n  {out}")
    print(f"  {dur // 60:.0f}m {dur % 60:04.1f}s   "
          f"{out.stat().st_size / 1e6:.1f} MB   {W}x{H} @ {FPS}fps")
    print(f"  audio: {has_audio or 'MISSING'}   voice: {narration.VOICE}")


if __name__ == "__main__":
    main()
