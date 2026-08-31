# varsity-algo

[![CI](https://github.com/sachincse/varsity-algo/actions/workflows/ci.yml/badge.svg)](https://github.com/sachincse/varsity-algo/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

A trading-signal scanner for the Indian market that you can actually run.
Describe a strategy in plain English, scan the Nifty universe, and review every
order before it is placed.

This is the system from Zerodha Varsity's
[*Build a Trading Algo with AI — No Coding Required*](https://www.youtube.com/watch?v=V9Ra8klDzrM),
built end to end and built safely.

It follows the video's flow — log in with your **API key, API secret and
request token**, see your account, then generate signals with **Short SMA,
Long SMA, Lookback and Max** — and adds the parts the video leaves out.

**Connect Zerodha and prices come from Kite, exactly as in the video.** Without
it the scanner still runs on free end-of-day data, so you can try everything
before paying for anything.

---

## Watch the setup tutorial

[![Tutorial](docs/img/video-poster.png)](https://github.com/sachincse/varsity-algo/releases/latest)

**▶ [Download the tutorial (5 min, narrated)](https://github.com/sachincse/varsity-algo/releases/latest)**
— or [docs/varsity-algo-tutorial.mp4](docs/varsity-algo-tutorial.mp4) in the repo.

Install, first scan, building a strategy from English, and the order
guardrails. Narrated end to end. Every frame is the real application — the
strategy you see being built from *"golden cross on the nifty 500 but only if
RSI is under 70"* was produced live by a 7B model running locally with no API
key.

---

## Install

**Windows** — download the repo, then double-click **`start.bat`**.

**macOS / Linux**

```bash
git clone https://github.com/sachincse/varsity-algo
cd varsity-algo
chmod +x start.sh && ./start.sh
```

That is the whole thing. The script checks for Python and Node, creates a
virtual environment, installs everything, builds the dashboard, and opens
<http://localhost:8000>. Re-running it is fast.

You need [Python 3.11+](https://www.python.org/downloads/) (tick **"Add
python.exe to PATH"** on the first installer screen) and
[Node 20.19+ or 22.12+](https://nodejs.org/). If Node is missing the app still
runs — you just get the API instead of the dashboard.

Full walkthrough, including every error message and its fix:
**[docs/SETUP.md](docs/SETUP.md)**.

---

## What it does

| | |
|---|---|
| ![Connect](docs/img/connect.png) | **Connect** — the video's login page: API key, API secret, request token. Credentials typed here stay in memory; put them in `.env` and only the token is needed each morning. |
| ![Account](docs/img/setup.png) | **Account** — the video's user tab: user ID, name, products and exchanges from the Kite profile API, plus holdings and funds. **Settings** lists every model option and which price source is live. |
| ![Strategy](docs/img/strategy.png) | **Strategy** — type the rule the way you would say it. The model fills a fixed schema; it never writes or runs code. |
| ![Signals](docs/img/signals.png) | **Signals** — Short SMA, Long SMA, Lookback and Max, then a table ranked by crossover recency showing the close beside both moving averages, so you can check a signal by eye. |
| ![Orders](docs/img/orders.png) | **Orders** — signals become a sized order sheet. Placement is off by default and every order needs its own confirmation. |

---

## The language model is optional, and free

Only used to turn English into a strategy. Pick one, put it in `.env`, restart.

**Free, no credit card**

| Provider | `.env` | Get a key |
|---|---|---|
| Groq | `LLM_PROVIDER=groq`<br>`GROQ_API_KEY=…` | [console.groq.com/keys](https://console.groq.com/keys) |
| Google Gemini | `LLM_PROVIDER=gemini`<br>`GEMINI_API_KEY=…` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| OpenRouter | `LLM_PROVIDER=openrouter`<br>`OPENROUTER_API_KEY=…` | [openrouter.ai/keys](https://openrouter.ai/keys) |

**Free and fully offline — no key, no account, nothing leaves your machine**

```bash
# install from https://ollama.com/download
ollama pull qwen3:8b
```

```ini
LLM_PROVIDER=ollama
LLM_MODEL=qwen3:8b
```

The tutorial video was recorded this way. A 7B model handled *"golden cross on
the nifty 500 but only if RSI is under 70"* correctly, on a laptop, for nothing.

Twelve providers are supported in total — Anthropic, Groq, OpenRouter, Gemini,
Together, DeepSeek, Fireworks, Cerebras, Mistral, xAI, Ollama, LM Studio, plus
any OpenAI-compatible endpoint. Claude uses its official SDK; the rest share one
adapter.

> Model IDs rot fast. Groq retired every Llama chat model in August 2026. If you
> see *"provider does not know this model"*, set `LLM_MODEL` to a current one —
> no code change needed.

---

## What is different from the video

**The AI writes code and then runs it.** A model that can emit arbitrary Python
into a process holding your broker access token is a remote-code-execution path
with a natural-language prompt as its input. Here the model fills a closed
schema ([`core/nl.py`](core/nl.py)) which compiles into a validated strategy
([`core/spec.py`](core/spec.py)). Asking it to add a `shell_command` field
returns `Extra inputs are not permitted`.

**₹500/month before you can look at anything.** Kite is used the moment you
connect — same data, same broker, same chart. But you are not blocked until
then: without a session the scanner falls back to free end-of-day data, so you
can decide whether it is worth paying for.

**Nothing checks the signals are honest.** 83 tests, and the important ones try
to prove the engine cannot see the future: truncate the input and signals must
be unchanged; replace every bar after date *T* with noise and everything up to
*T* must be bit-identical.

**Bullish and bearish are presented symmetrically.** A retail account cannot
hold a short equity position overnight in India, so a bearish crossover is an
exit for something you already own, never a trade.

---

## Does the strategy make money?

No, and you should know that before building on it. SMA(6)/SMA(30) on the Nifty
100, 2011–2026, next-open fills, full Zerodha charges, 25 bps slippage, and a
point-in-time universe:

| | CAGR |
|---|---|
| SMA 6/30, honestly tested | **1.92%** |
| Nifty 100 total-return index, net of fees | **10.70%** |
| Same universe, no timing rule at all | **13.65%** |

It also sits at the **28th percentile** of a random-entry null with the same
trade count and holding periods.

Where the money went, on closed trades across the full 15.6 years, starting
from ₹10,00,000:

| | ₹ |
|---|---|
| gross trading gains | 3,40,861 |
| less charges and slippage | −3,23,801 |
| **left over from actually trading** | **17,060** |
| plus dividends, which the rule did nothing to earn | +2,31,568 |
| net profit | 2,48,628 |

Charges took **95%** of the gross gains. What the timing rule itself earned in
fifteen and a half years — after costs, before dividends — was ₹17,060 on ₹10
lakh. Almost all of the reported profit is dividends you would have collected by
holding the same stocks and never trading at all.

Every figure there comes from
[`out/trades_S3_pit.csv`](https://github.com/sachincse/zerodha-algo/blob/main/out/trades_S3_pit.csv),
which is committed so you can add up the columns yourself.

Two caveats the study measures rather than hides. The **1.92% is sensitive to
an arbitrary tiebreak** — recency does not separate same-day crossovers, and
alphabetical-by-symbol was the accidental default. Across four defensible
tiebreaks the figure spans 0.66% to 2.66%. And the 13.65% no-timing null was
previously quoted at 11.90%, because it was measured on price return while the
strategy collected dividends; correcting that made the gap wider, not narrower.

Full method, artifacts and the leak tests: **[sachincse/zerodha-algo](https://github.com/sachincse/zerodha-algo)**.

The scanner is a useful lens on what is moving. It is not a reason to trade.

---

## Safety model for orders

Placing an order is the only irreversible thing this program does, so it sits
behind four locks:

1. `ENABLE_TRADING=true` in `.env` — a deliberate act in a text editor
2. a preview that mints a one-time token bound to the exact symbol, side,
   quantity and product
3. that token expiring after three minutes, because the prices behind it go stale
4. a browser confirmation naming the order

Orders go one at a time. There is no "place all".

---

## Layout

```
core/     spec.py (the DSL) · nl.py (English → spec) · engine.py (causal
          indicators) · data.py (yfinance or Kite)
server/   FastAPI; serves /api and the built SPA from one process
          kite_client.py · jobs.py · llm/ (12 providers) · routes/
web/      React + Vite dashboard
tests/    83 tests, mostly attempts to break the causality guarantee
tools/    record_app.py · narration.py · build_video.py — the tutorial
          video is generated from source, not hand-edited
docs/     SETUP.md · API_SPEC.md · the tutorial video
```

## Development

```bash
python -m pytest tests/ -q          # 44 passed
cd web && npm run dev               # hot-reload frontend on :5173
python -m uvicorn server.main:app --reload --port 8000
```

Rebuild the tutorial video (needs ffmpeg):

```bash
python tools/record_app.py --out build/clips   # drive the real app
python tools/build_video.py --revoice          # narrate, edit, encode
```

The narration script lives in [`tools/narration.py`](tools/narration.py) and is
spoken by a free neural voice via `edge-tts` — no API key. Narration *drives*
the edit: each segment is stretched to fit its line rather than the line being
squeezed into a duration chosen in advance. Change `VOICE` for a different
accent.

## Licence

MIT — see [LICENSE](LICENSE). Not financial advice. You are responsible for
every order you approve.

---

## Checking a strategy you wrote yourself

The engine's causality is covered by tests, but those tests use fixed
strategies. They say nothing about a rule you invented this morning — and a
strategy is where look-ahead most easily creeps in.

```bash
python tools/lookahead_check.py                       # the shipped default
python tools/lookahead_check.py --spec my.json
python tools/lookahead_check.py --text "golden cross on the nifty 500"
```

Four checks: signals computed on truncated data must match signals computed at
the same as-of date on full data; scrambling every bar after date T must leave
everything before T untouched; the **indicator series itself** must be
identical at the as-of bar with and without the future present; and recomputing
from three different start dates must give the same recent signals.

The third check exists because of the fourth flag:

```bash
python tools/lookahead_check.py --selftest
```

That deliberately shifts every moving average one bar into the future and
requires the checks to go red. The first time it ran, they did not — a uniform
shift moves the *numbers* without moving the crossover *days*, so comparing
signal identity sailed straight past a broken engine. A checker nobody has
tried to fool is not evidence.

## The five locks on placing an order

| Lock | What it does |
|---|---|
| `ENABLE_TRADING=false` | The default. Placement is refused outright until you change it in `.env`. |
| Signed preview | An HMAC bound to symbol, side, quantity, product and order type. Alter any of them and it is rejected. |
| 3-minute expiry | A preview goes stale. Walk away and come back, you preview again. |
| Typed `CONFIRM` | The request must carry the literal word. |
| **Size** | An order worth more than `LARGE_ORDER_VALUE` (default ₹50,000) needs a separate acknowledgement. |

The fifth is there because the other four are all binary — armed or not, signed
or not, expired or not, confirmed or not. **None of them notices size.** A
fat-fingered quantity produces an order that is correctly signed, correctly
confirmed, comfortably unexpired, and sails through every other check. It is
deliberately checked *after* the signature, so trimming the quantity to slip
under the threshold invalidates the token first.

## Plain English, both ways

The Strategy tab compiles what you type into a validated schema, then compiles
it **back into English**:

> Every day, look at the 100 largest stocks on the NSE, using daily prices. Buy
> a stock when its 6-day average price rises above its 30-day average price.
> Sell it again when its 6-day average price falls below its 30-day average
> price. Selling here means closing a position you already hold — it is never a
> short.

Restating your own notation confirms nothing. A model that reads *"under 70"* as
*"over 70"* produces a spec that validates perfectly and describes itself in
notation you will nod along to. The round trip through different words is what
catches it.

A separate linter asks whether a valid strategy is *sensible*: identical buy and
sell rules, an RSI threshold outside 0–100 that can never fire, a 500-stock scan
truncated to 5 rows, a missing liquidity filter.

## Charts

Click any row in the Signals table to see the candles with both moving averages
drawn over them, and an arrow on the bar the crossover actually fired. The
series come from the same panel the scan used, so the chart cannot disagree with
the row that opened it.
