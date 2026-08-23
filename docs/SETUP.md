# Setup guide

Written for Windows, because that is what most people following the video are
on. Mac and Linux notes are at the bottom. Nothing here assumes you can code.

Total time: about 15 minutes for the free path, 25 if you connect Zerodha.

**You can stop after Step 3 and have a working scanner.** Steps 4 and 5 are
optional: Step 4 connects your Zerodha account, Step 5 adds the plain-English
strategy builder.

---

## Step 0 — Check what you already have

Open **PowerShell** (press `Win`, type `powershell`, hit Enter) and run:

```powershell
python --version
node --version
```

You need **Python 3.11 or newer** and **Node 20.19+ or 22.12+**.

Node 21.x and Node 22.0–22.11 are rejected by the build tool — if you have one
of those, upgrade. If either command says "not recognized", install from
[python.org/downloads](https://www.python.org/downloads/) (tick **"Add python.exe
to PATH"** on the first screen — this is the single most common setup mistake)
and [nodejs.org](https://nodejs.org/) (take the LTS version).

Close and reopen PowerShell after installing, or the new commands will not be
found.

---

## Step 1 — Get the code and create a virtual environment

```powershell
cd $HOME\codes\varsity-algo
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Your prompt should now start with `(.venv)`.

### If Activate.ps1 fails

You will see something like *"cannot be loaded because running scripts is
disabled on this system"*. This is Windows' default and it blocks about half of
all first-time setups. Fix it once, for your user only:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Answer `Y`, then run the activate command again. This does not weaken anything
meaningful — it allows locally-created scripts to run for your account.

If you would rather not change it at all, use `cmd.exe` instead:

```cmd
.venv\Scripts\activate.bat
```

---

## Step 2 — Install the Python side

With `(.venv)` showing:

```powershell
pip install -r requirements.txt
```

Takes two or three minutes. Then check it worked:

```powershell
python -m pytest tests\ -q
```

You should see **40 passed**. Those tests prove the strategy engine cannot see
future prices — worth running once so you know the thing you are about to trust
was actually checked.

---

## Step 3 — Start it up

Two servers need to run: the Python backend and the web frontend.

**The easy way** — double-click `dev.bat` in the project folder. Two windows
open, one per server. Leave both open.

**Or, from PowerShell**, in two separate windows:

```powershell
# window 1 — backend
cd $HOME\codes\varsity-algo
.\.venv\Scripts\Activate.ps1
python -m uvicorn server.main:app --reload --port 8000
```

```powershell
# window 2 — frontend
cd $HOME\codes\varsity-algo\web
npm install
npm run dev
```

> PowerShell 5.1 — the Windows 11 default — does not support `&&` between
> commands. Use separate lines, or a semicolon. If you want `&&`, install
> PowerShell 7 and use `pwsh`.

Now open **http://localhost:5173**.

Go to the **Strategy** tab, click **"Use the video's SMA 6/30"**, then
**Signals** → **Run scan**.

The first scan downloads prices for a few hundred stocks and takes two or three
minutes. After that it is cached and near-instant. You now have the video's
scanner, with no Zerodha subscription and no API keys.

---

## Step 4 — Connect Zerodha (optional)

Only needed for your holdings, live prices, and placing orders. The scanner
works without it.

**4a. You need a Kite Connect app.** Go to
[developers.kite.trade](https://developers.kite.trade), sign in with your
Zerodha account, and create an app:

| Field | What to put |
|---|---|
| Type | **Connect** |
| App name | anything, e.g. `varsity-algo` |
| Zerodha client ID | your client ID |
| Redirect URL | `http://127.0.0.1:8000/kite-redirect` |
| Postback URL | leave blank |

This costs **₹500/month**. Historical candle data is included — there is no
longer a separate add-on for it.

You also need **2FA/TOTP enabled** on your Zerodha account. The login flow is
interactive by design; there is no password-only path.

**4b. Put the credentials in `.env`.** Copy `.env.example` to `.env` and fill in:

```
KITE_API_KEY=your_api_key_here
KITE_API_SECRET=your_api_secret_here
```

Restart the backend so it picks them up.

**4c. Log in.** On the **Setup** tab, click the Kite login link, sign in, and
you will land on a URL like:

```
http://127.0.0.1:8000/kite-redirect?request_token=AbCdEf123&action=login&status=success
```

The page will show an error — that is expected and harmless, nothing is
listening there. Copy the whole URL from the address bar and paste it into the
box. The token gets extracted for you.

> **The `request_token` is single-use and dies after a couple of minutes.** If
> you get "Kite rejected the login", the overwhelmingly likely cause is a stale
> token, not a wrong secret. Just click the login link again for a fresh one.

Your session lasts until **6 AM IST**, then you log in again. That is a
regulatory rule, not a limitation of this app.

---

## Step 5 — Add a language model (optional)

This is what lets you type *"golden cross on the Nifty 500 but only if RSI is
under 70"* instead of editing numbers by hand.

Pick **one**. Add its key to `.env` and set `LLM_PROVIDER`.

### Free, no credit card

| Provider | `.env` | Notes |
|---|---|---|
| **Groq** | `LLM_PROVIDER=groq`<br>`GROQ_API_KEY=...` | Fastest. Free tier. Key: [console.groq.com/keys](https://console.groq.com/keys) |
| **Google Gemini** | `LLM_PROVIDER=gemini`<br>`GEMINI_API_KEY=...` | Generous free tier. Key: [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| **OpenRouter** | `LLM_PROVIDER=openrouter`<br>`OPENROUTER_API_KEY=...`<br>`LLM_MODEL=z-ai/glm-5.2:free` | 400+ models, one key. Free variants at 20/min, 50/day. |

### Completely local — no key, no cost, nothing leaves your laptop

```powershell
# install from https://ollama.com/download, then:
ollama pull qwen3:8b
```

```
LLM_PROVIDER=ollama
LLM_MODEL=qwen3:8b
```

That is it — no key, no account. A 7–8B model handles this task well; it was
tested on `qwen2.5:7b` and got the crossover, the compound RSI filter, and the
custom exit level all correct. Expect ~10 GB of RAM in use and a few seconds
per request.

### Paid, most reliable

| Provider | `.env` |
|---|---|
| **Anthropic** | `LLM_PROVIDER=anthropic`<br>`ANTHROPIC_API_KEY=...` |
| **DeepSeek** | `LLM_PROVIDER=deepseek`<br>`DEEPSEEK_API_KEY=...` |

The **Setup** tab shows every provider and whether it is ready, so you can see
at a glance what is wired up.

> **Model IDs change constantly.** Groq retired every Llama chat model in August
> 2026. If you get "provider does not know this model", check the provider's
> current model list and set `LLM_MODEL` accordingly — no code change needed.

---

## Step 6 — Enabling real orders (think about this one)

Order placement is **off by default**. To turn it on:

```
ENABLE_TRADING=true
```

and restart the backend. Then every order still requires:

1. a preview, which mints a token bound to that exact order
2. the token to still be valid (3 minutes)
3. a browser confirmation dialog naming the symbol and quantity

Orders go one at a time. There is deliberately no "place all" button.

**Before you switch this on**, read [`../README.md`](../README.md) on what this
strategy actually returned when tested properly. Short version: 1.9% a year
against the index's 10.7%, and it lost to random entries. The scanner is
interesting. The strategy is not a reason to trade.

---

## Running it as one app (optional)

Once you are done experimenting, you can drop the second server:

```powershell
cd web
npm run build
```

Now the backend serves everything. Just run the backend and open
**http://localhost:8000**.

---

## Mac and Linux

Everything is the same except:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn server.main:app --reload --port 8000
```

There is no ExecutionPolicy problem, and `&&` works.

---

## When something breaks

| What you see | What it is |
|---|---|
| `Activate.ps1 cannot be loaded` | Step 1 — run the `Set-ExecutionPolicy` line |
| `'python' is not recognized` | Python not on PATH — reinstall, tick "Add to PATH", reopen PowerShell |
| `The token '&&' is not a valid statement separator` | PowerShell 5.1 — use separate lines |
| Browser says "Could not reach the backend" | The backend window is closed or crashed — check window 1 |
| `Kite rejected the login` | Stale `request_token`. Get a fresh one. Then check `KITE_API_SECRET` for a stray space |
| `Not logged in to Kite` after it worked yesterday | Tokens expire at 6 AM IST. Log in again |
| Scan takes forever the first time | Normal — a few hundred symbols. Cached afterwards |
| `provider does not know the model` | The model ID was retired. Set `LLM_MODEL` to a current one |
| `The 'x' provider is not configured` | Key missing from `.env`, or the backend was not restarted after you added it |
| Ollama shows "not running" | Run `ollama serve`, and `ollama list` to confirm a model is pulled |
| Port 8000 already in use | An old backend is still running — see below |
| You changed `.env` but nothing changed | Almost always the same stale-process problem — see below |

### The stale-backend trap on Windows

This one cost me an hour while building it, so it is worth its own section.

On Windows, closing a terminal or pressing Ctrl+C does not always kill the
`uvicorn` process. Start the server again and it silently fails to bind, and
**the old process keeps answering on port 8000** — running the old code, with
the old `.env`. You edit a setting, restart, and see no change, because you are
still talking to the process from twenty minutes ago.

Git Bash's `pkill -f uvicorn` does **not** work for this. Use the real thing:

```powershell
# see what is holding the port
netstat -ano | findstr :8000

# the last column is the PID — kill it
taskkill /F /PID <pid>
```

Or kill every Python process, which is blunt but effective:

```powershell
taskkill /F /IM python.exe
```

The backend prints its configuration on startup — provider, Kite key present or
not, price source. If those lines do not match your `.env`, you are looking at a
stale process, not a bug.

Anything else: the backend window prints the real error. That is the one worth
reading.
