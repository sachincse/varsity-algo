# varsity-algo

The system from Zerodha Varsity's [*Build a Trading Algo with AI — No Coding
Required*](https://www.youtube.com/watch?v=V9Ra8klDzrM), built end to end and
built properly.

Describe a strategy in English, get a ranked signal table across the Nifty
universe, review a sized order sheet, and place orders one at a time through
Kite Connect.

**→ [docs/SETUP.md](docs/SETUP.md) is the step-by-step guide. Start there.**

---

## What is different from the video

The video is a good tutorial about tooling. Four things in it do not survive
contact with a real account, and this repo fixes each one.

**The AI writes code and then runs it.** A model that can emit arbitrary Python
into a process holding your broker access token is a remote-code-execution path
with a natural-language prompt as its input — prompt injection through a pasted
strategy description is enough. Here the model never writes code. It fills in a
closed schema ([`core/nl.py`](core/nl.py)) with fixed enums and range-checked
numbers, and the server compiles that into a validated strategy
([`core/spec.py`](core/spec.py)). Anything unexpected is refused. Tested: asking
the model to add a `shell_command` field returns
`shell_command: Extra inputs are not permitted`.

**It costs ₹500/month before you can look at anything.** The scanner here runs
on free end-of-day data by default. Kite Connect is optional and only needed for
holdings, live prices, and orders.

**Nothing checks that the signals are honest.** The engine has 40 tests, and the
important ones try to prove it cannot see the future: truncate the input and the
signals must be unchanged; replace every bar after date *T* with noise and
everything up to *T* must be bit-identical. A leak in a backtest gives you a
wrong number; a leak in a live scanner gives you a signal that could not have
existed, and you trade on it.

**It presents bullish and bearish signals symmetrically.** A retail account
cannot hold a short equity position overnight in India, so a bearish crossover is
an exit for something you already own, never a trade. The app says so where it
matters.

It also drops the Node/React/FastAPI/Codex stack requirement down to: Python,
and optionally Node. And it works with **any** LLM — including one running on
your own laptop with no API key at all.

---

## Does the strategy make money?

No, and you should know that before you build on it.

The same rule — SMA(6)/SMA(30) on the Nifty 100 — backtested over 2011–2026 with
next-open fills, full Zerodha charges, 25 bps of slippage and a point-in-time
universe:

| | CAGR |
|---|---|
| SMA 6/30, honestly tested | **1.92%** |
| Nifty 100 total-return index, net of fees | **10.70%** |
| Same universe, no timing rule at all | 11.90% |

It also sits at the **28th percentile** of a random-entry null with the same
trade count and holding periods — throwing darts did better. 95% of its gross
trading gains went to charges, and 67% of the remaining profit was dividends the
strategy did nothing to earn.

The scanner is a genuinely useful lens on what is moving. It is not a reason to
trade. The full study, including the leak-free backtester, is in
[`../zerodha-algo`](../zerodha-algo).

---

## Layout

```
core/
  spec.py      the strategy DSL — closed, validated, what the engine executes
  nl.py        the flat schema the LLM fills in, and the compiler to spec.py
  engine.py    causal indicator + condition evaluation, per-symbol calendars
  data.py      price panels from yfinance (free) or Kite (subscription)
server/
  main.py      FastAPI app; serves /api and the built SPA from one process
  kite_client.py   session handling, checksum, 6 AM IST expiry, expiry hook
  llm/
    registry.py    provider catalogue — base URLs, env vars, model defaults
    providers.py   Anthropic via its own SDK; everything else OpenAI-compatible
    base.py        JSON extraction, validation, and a one-shot repair retry
  routes/      health, kite, llm, scan, trade
web/           React + Vite dashboard (Setup / Strategy / Signals / Orders)
tests/         40 tests, mostly trying to break the causality guarantee
docs/
  SETUP.md     the step-by-step guide
  API_SPEC.md  the researched Kite + LLM API contract this was built against
```

## Supported LLM providers

One key, one line in `.env`. Anthropic uses the official `anthropic` SDK;
everything else speaks the OpenAI chat-completions shape through one adapter.

**Free, no card:** Groq · Google Gemini · OpenRouter (`:free` variants)
**Local, no key:** Ollama · LM Studio · vLLM / llama.cpp (via `custom`)
**Paid:** Anthropic · DeepSeek · Together · Fireworks · Cerebras · Mistral · xAI

Verified working end to end on a local `qwen2.5:7b` through Ollama with no API
key: it correctly produced the plain crossover, a compound golden-cross-plus-RSI
filter, and an RSI strategy with a custom exit level.

## Safety model for orders

Placing an order is the only irreversible thing this program does, so it sits
behind four locks:

1. `ENABLE_TRADING=true` in `.env`, which is a deliberate act in a text editor
2. a preview that mints a one-time token bound to the exact symbol, side,
   quantity and product
3. that token expiring after three minutes, because the prices behind it go stale
4. a browser confirmation naming the order

Orders go one at a time. There is no "place all" — that is how people fire
twelve orders they meant to read.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest tests\ -q          # 40 passed
cd web ; npm install ; npm run build ; cd ..
python -m uvicorn server.main:app --reload --port 8000
```

Open http://localhost:8000. No keys needed to scan.

Full guide, including the Windows ExecutionPolicy trap and every error message
you are likely to hit: **[docs/SETUP.md](docs/SETUP.md)**.
