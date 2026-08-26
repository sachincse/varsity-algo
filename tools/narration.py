"""Narration script and text-to-speech for the tutorial video.

Uses edge-tts: free, no API key, and genuinely good neural voices. The default
is an Indian English voice, because the audience for this is people who watched
a Zerodha Varsity video. Change VOICE to any name from `edge-tts --list-voices`.

The important structural point: NARRATION DRIVES TIMING. Each segment of the
video is stretched to fit the line spoken over it, rather than the line being
squeezed to fit a duration picked in advance. A tutorial where the voice is
still finishing a sentence as the picture cuts is worse than one that breathes.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

VOICE = "en-IN-PrabhatNeural"
RATE = "+6%"        # a touch quicker than default; still unhurried
PAD_BEFORE = 0.45   # silence before the line starts
PAD_AFTER = 0.85    # breathing room before the next segment

# --------------------------------------------------------------------------
# The script. One entry per video segment, keyed to the segment id.
# Written to be SPOKEN — short sentences, no bullet-point voice.
# --------------------------------------------------------------------------
SCRIPT: dict[str, str] = {
    "s01": (
        "This is varsity algo. It scans the Indian market for trading signals, "
        "and you describe what you want in plain English. "
        "Let me show you how to set it up."
    ),
    "s02": (
        "You need two free things installed: Python, and Node. "
        "When you install Python, make sure you tick the box that says "
        "add python dot exe to PATH. That one checkbox is the most common "
        "reason setups fail."
    ),
    "s03": (
        "Download the project from GitHub. "
        "Then just double-click start dot bat. "
        "It checks what you already have, installs whatever is missing, "
        "builds the dashboard, and opens it for you. "
        "The first run takes a few minutes. After that it is quick."
    ),
    "s04": (
        "This first tab connects the app to your Zerodha account. "
        "Paste in your API key and secret, and a login link appears. "
        "Sign in at Zerodha, and you get sent back with a request token in "
        "the address bar. Copy the whole address and paste it in. "
        "After that, prices come from Kite, so what you see here matches the "
        "chart in your own terminal."
    ),
    "s05": (
        "You do not have to connect straight away, though. "
        "Without a Zerodha session the scanner falls back to free "
        "end-of-day data, so you can try the whole thing before you pay for "
        "anything. "
        "The settings tab shows which data source is in use, and every "
        "language model option."
    ),
    "s06": (
        "The language model is optional too. It is only used to turn your "
        "English into a strategy. "
        "Groq, Google Gemini and OpenRouter all have free tiers, and none of "
        "them ask for a credit card. "
        "Pick one, paste the key into the env file, and restart."
    ),
    "s06b": (
        "Or skip the keys entirely. "
        "Ollama runs an open model on your own laptop. Nothing leaves your "
        "machine, and it costs nothing. "
        "This whole tutorial was recorded that way."
    ),
    "s07": (
        "Now type the rule the way you would say it out loud. "
        "Golden cross on the nifty five hundred, but only if RSI is under "
        "seventy. "
        "That is a seven billion parameter model, running locally, working "
        "it out. I have sped this bit up — it really took about half a minute. "
        "And notice what it produced. It did not write code. "
        "It filled in a fixed schema, which the server then checks. "
        "If the model gets creative, the strategy is rejected before anything "
        "runs."
    ),
    "s08": (
        "The signals tab has the same four controls as the video: "
        "short moving average, long moving average, lookback, and how many "
        "rows you want back. "
        "Hit generate. "
        "The first time, it downloads every stock in the universe, so give it "
        "a few minutes. You get a progress bar, so you know it is working. "
        "After that it is cached. "
        "Results are ranked by how recently each crossover fired, and each row "
        "shows the closing price next to both moving averages — so you can "
        "check the signal is real rather than taking it on trust. "
        "And a bearish row means sell something you already own. It is not a "
        "short. In India, a retail account cannot hold a short equity position "
        "overnight."
    ),
    "s09": (
        "The signals become a sized order sheet, split evenly across your "
        "open slots. "
        "Placing orders is switched off until you deliberately turn it on. "
        "Preview always works, so nothing is ever sent by surprise. "
        "And orders go one at a time. There is no place-all button."
    ),
    "s10": (
        "Now the part most tutorials leave out. "
        "This strategy does not beat the index. "
        "Tested properly, over fifteen years, with real charges and realistic "
        "fills, it returned under two percent a year. "
        "An index fund returned more than ten. "
        "Just holding the same stocks, with no timing rule at all, did better "
        "than both."
    ),
    "s11": (
        "So treat the scanner as a lens for seeing what is moving, "
        "not as a system to follow. "
        "The genuinely useful part is the machinery around it — "
        "the cost model, the tests that prove it cannot see the future, "
        "and the guardrails on every order."
    ),
    "s12": (
        "It is free, it is MIT licensed, and the link is on screen. "
        "The setup guide lists every error message you might hit, "
        "and how to fix it. "
        "Thanks for watching."
    ),
}


async def _synth(text: str, out: Path, voice: str, rate: str) -> None:
    comm = __import__("edge_tts").Communicate(text, voice, rate=rate)
    await comm.save(str(out))


def duration(p: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def synth_all(out_dir: Path, voice: str = VOICE, rate: str = RATE,
              force: bool = False) -> dict[str, dict]:
    """Render every line to its own wav, padded. Returns {seg: {path, dur}}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, dict] = {}

    for seg, text in SCRIPT.items():
        mp3 = out_dir / f"{seg}.mp3"
        wav = out_dir / f"{seg}.wav"
        if force or not wav.exists():
            asyncio.run(_synth(text, mp3, voice, rate))
            # Normalise to a consistent level and pad, so segments do not
            # jump in volume and the voice does not start on the cut.
            subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(mp3),
                 "-af", f"loudnorm=I=-17:TP=-1.5:LRA=11,"
                        f"adelay={int(PAD_BEFORE * 1000)}|{int(PAD_BEFORE * 1000)},"
                        f"apad=pad_dur={PAD_AFTER}",
                 "-ar", "48000", "-ac", "2", "-y", str(wav)],
                check=True, capture_output=True)
            mp3.unlink(missing_ok=True)
        result[seg] = {"path": wav, "dur": duration(wav)}

    return result


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/vo")
    info = synth_all(out, force="--force" in sys.argv)
    total = sum(v["dur"] for v in info.values())
    print(f"{VOICE} @ {RATE}\n")
    for seg, v in info.items():
        words = len(SCRIPT[seg].split())
        print(f"  {seg:6s} {v['dur']:6.2f}s  {words:3d} words  "
              f"{words / max(v['dur'] - PAD_BEFORE - PAD_AFTER, .1) * 60:5.0f} wpm")
    print(f"\n  total narration {total:.1f}s  ({total / 60:.1f} min)")
