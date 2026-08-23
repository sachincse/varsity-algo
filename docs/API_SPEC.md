# varsity-algo — IMPLEMENTATION SPEC (binding)

**Status:** binding. Every literal string in this document is normative. Do not substitute synonyms, reorder positional args, or "clean up" casing.
**Date of research basis:** 2026-08-23. Anything not verifiable against a primary source is tagged `[UNVERIFIED]`.

---

## 0. Scope, layout, and version pins

```
varsity-algo/
├─ .venv/                        # created by python -m venv (see §6.3)
├─ .env                          # gitignored
├─ .env.example                  # committed, same KEYS, empty values
├─ app/
│  ├─ __init__.py
│  ├─ main.py                    # FastAPI app; route order is load-bearing (§6.2)
│  ├─ config.py                  # pydantic-settings Settings (§6.5)
│  ├─ kite/
│  │  ├─ auth.py                 # §1
│  │  ├─ data.py                 # §2
│  │  └─ orders.py               # §3
│  ├─ llm/
│  │  ├─ registry.py             # §4 PROVIDERS table
│  │  ├─ openai_provider.py      # all OpenAI-compatible providers
│  │  ├─ claude_provider.py      # official anthropic SDK ONLY
│  │  ├─ ollama_provider.py      # zero-key local
│  │  └─ structured.py           # §5 tiered JSON extraction + repair loop
│  └─ store/
│     ├─ session.json            # cached Kite access_token (gitignored)
│     └─ instruments.csv         # daily instrument dump cache (gitignored)
├─ frontend/
│  ├─ vite.config.js             # §6.1 — exact
│  ├─ package.json               # §6.4 — exact scripts block
│  └─ dist/                      # build output, served by FastAPI in prod
├─ dev.bat                       # §6.4 fallback launcher
└─ requirements.txt
```

**Pinned dependencies (`requirements.txt`):**

```
fastapi[standard]>=0.141.1
kiteconnect==5.2.1
anthropic
openai
ollama
pydantic-settings
pandas
```

- `kiteconnect` is the PyPI name; the import package is `kiteconnect`; `__version__ == "5.2.1"`; `__all__ = ["KiteConnect", "KiteTicker", "exceptions"]`.
- Node floor for the frontend: **20.19+ or 22.12+**. Node 21.x and 22.0–22.11 are rejected by Vite 8. Check with `node --version` before anything else.

---

## 1. KITE AUTH

### 1.1 Prerequisites (non-negotiable)

1. Active Zerodha trading account.
2. **2FA TOTP enabled on the account.** The login flow is interactive by design; there is no documented headless/password-grant path.
3. A Kite Connect app in the developer console with an `api_key` / `api_secret` pair and a **registered Redirect URL**. The console form requires HTTPS **except** for localhost — `http://127.0.0.1:<port>/kite-redirect` is accepted.
4. Paid Kite Connect subscription (₹500/month) — historical candle data is bundled since Feb 2025; there is no separate ₹2000 historical add-on any more.

`api_secret` lives only in `.env` on the server. Never ship it to the browser. Never expose `access_token` to the browser either.

### 1.2 The flow — numbered, exact

**Step 1 — Construct the login URL.**
Do **not** hardcode it. Call the SDK:

```python
from kiteconnect import KiteConnect
kite = KiteConnect(api_key=settings.kite_api_key)
url = kite.login_url()
```

The SDK emits (note param order — `api_key` first):

```
https://kite.zerodha.com/connect/login?api_key=xxx&v=3
```

The official docs write the same URL with the params reversed:

```
https://kite.zerodha.com/connect/login?v=3&api_key=xxx
```

**Both are valid.** Do not "fix" one to match the other.

Optional: append `redirect_params`, a URL-encoded query string echoed back to the redirect URL:
`https://kite.zerodha.com/connect/login?v=3&api_key=xxx&redirect_params=some%3DX%26more%3DY`
There is **no** `redirect_uri` / `redirect_url` parameter. The redirect target is fixed per `api_key` in the developer console.

**Step 2 — User logs in; browser lands on the registered redirect URL.**
Query params observed:

- `request_token` — the only one the normative docs name.
- `status` — named on the Mobile/Desktop apps page: `https://yoursite.com/kite-redirect?request_token=yyy&status=zzz`
- `action` — `[UNVERIFIED: appears only in a Zerodha staff forum example, not in any docs page]`. Full staff example:
  `https://kite.trade/?request_token=nCsQ1GUMkdtxoWp5Az37Ad3GO9EuHYY4&action=login&status=success&user_id=abcd`

Parse `request_token` only. Treat `status`/`action`/`user_id` as advisory.

**Step 3 — Compute the checksum.**

```
checksum = SHA-256 hash of (api_key + request_token + api_secret)
```

Exact implementation (this is what the SDK does — plain concatenation, **no separator, not an HMAC**, lowercase hex):

```python
h = hashlib.sha256(api_key.encode("utf-8") + request_token.encode("utf-8") + api_secret.encode("utf-8"))
checksum = h.hexdigest()
```

**Step 4 — Exchange for an access_token.**
Use the SDK; do not hand-roll:

```python
data = kite.generate_session(request_token, api_secret=settings.kite_api_secret)
```

Raw HTTP equivalent (form-encoded body, **not JSON**):

```
POST https://api.kite.trade/session/token
  -H "X-Kite-Version: 3"
  -d "api_key=xxx"
  -d "request_token=yyy"
  -d "checksum=zzz"
```

**Step 5 — Persist and set the token.**
`generate_session()` already calls `set_access_token()` internally. Persist `data["access_token"]` to `app/store/session.json` alongside the date it was minted. On every subsequent process start:

```python
kite = KiteConnect(api_key=settings.kite_api_key, access_token=cached_token)
```

**Step 6 — Register the expiry hook.**

```python
kite.set_session_expiry_hook(on_session_expired)   # must be callable, else TypeError
```

It fires inside `_request()` when `r.status_code == 403 and data["error_type"] == "TokenException"`. Wire it to: delete `session.json`, mark the app "needs re-login", surface a re-login banner in the dashboard.

**Step 7 — Every subsequent request carries these two headers** (the SDK adds them, but only attaches `Authorization` when **both** `api_key` and `access_token` are truthy):

```
X-Kite-Version: 3
Authorization: token api_key:access_token
```

**Step 8 — Logout (optional).**

```python
kite.invalidate_access_token()      # DELETE /session/token?api_key=xxx&access_token=yyy  -> {"status":"success","data":true}
```

### 1.3 The session response — exact fields

`generate_session()` returns the **unwrapped inner `data` dict** (no `status`/`data` envelope), and **mutates `login_time` from `str` to a `datetime`** via `dateutil` when `len(login_time) == 19`.

Wire payload (docs sample, with the docs' invalid single-quoted empties corrected to `""`):

```json
{
  "user_type": "individual",
  "email": "XXXXXX",
  "user_name": "Kite Connect",
  "user_shortname": "Connect",
  "broker": "ZERODHA",
  "exchanges": ["NSE","NFO","BFO","CDS","BSE","MCX","BCD","MF"],
  "products": ["CNC","NRML","MIS","BO","CO"],
  "order_types": ["MARKET","LIMIT","SL","SL-M"],
  "avatar_url": "abc",
  "user_id": "XX0000",
  "api_key": "XXXXXX",
  "access_token": "XXXXXX",
  "public_token": "XXXXXXXX",
  "enctoken": "XXXXXX",
  "refresh_token": "",
  "silo": "",
  "login_time": "2021-01-01 16:15:14",
  "meta": {"demat_consent": "physical"}
}
```

Documented attributes: `user_id`, `user_name`, `user_shortname`, `email`, `user_type`, `broker`, `exchanges[]`, `products[]`, `order_types[]`, `api_key`, `access_token`, `public_token`, `refresh_token`, `login_time`, `meta` (`demat_consent` ∈ empty / `consent` / `physical`), `avatar_url`.

`enctoken` and `silo` appear in the payload but have **no entry** in the docs' Response-attributes table. Treat as internal. Do not build on them.

Persist only: `access_token`, `user_id`, `login_time` (as ISO string — see Gotcha 6).

### 1.4 Token expiry rule — binding

- Authoritative sentence: the `access_token` *"will expire at 6 AM on the next day (regulatory requirement)"* unless invalidated earlier.
- The docs never write "IST" on that line. The timezone comes from the global rule: *"Timestamp (datetime) strings in the responses are represented in the form yyyy-mm-dd hh:mm:ss, set under the Indian timezone (IST) — UTC+5.5 hours."*
- `[UNVERIFIED — long-time forum user, not Zerodha staff]`: the actual flush lands somewhere between **05:00 and 07:30 IST**.
- **Implementation rule:** schedule the daily interactive re-login at **07:30 IST or later**, never at 06:01.
- **There is no renewal for ordinary apps.** The v3 User endpoint table contains exactly four rows — `POST /session/token`, `GET /user/profile`, `GET /user/margins/:segment`, `DELETE /session/token`. No renew endpoint. `KiteConnect.renew_access_token(refresh_token, api_secret)` (→ `POST /session/refresh_token`) exists in the SDK but is undocumented in the REST docs and requires a non-empty `refresh_token`, which is *"only available to certain approved platforms"* and comes back `""` for individual apps. **Plan for a fresh interactive login every trading day.**
- Three independent things kill the token, all surfacing as HTTP **403** with `error_type: "TokenException"`: (a) `DELETE /session/token`, (b) master-logout from the Kite web terminal, (c) the user logging into another Kite instance.
- **Missing/invalid credentials are HTTP 400 `InputException`, not 403** — body: `{"status":"error","message":"Invalid \`api_key\` or \`access_token\`.","data":null,"error_type":"InputException"}`. Retry logic watching only 403 will miss auth failure entirely.

### 1.5 Postback URL — separate mechanism, different checksum

Not part of auth. Registered separately in the console. Kite server-to-server POSTs a **raw JSON body** on order status change (`COMPLETE`, `CANCEL`, `REJECTED`, `UPDATE`). Works even when the user is not logged in.

**Postback checksum is a different formula — do not reuse the session one:**

```
sha256(order_id + order_timestamp + api_secret)
```

Only orders placed with your own `api_key` are notified. For an individual developer wanting updates for orders placed anywhere, the docs direct you to **Postbacks over WebSocket** (`KiteTicker.on_order_update`) instead.

---

## 2. KITE DATA

### 2.1 Instruments dump

| | |
|---|---|
| All exchanges | `GET https://api.kite.trade/instruments` |
| One exchange | `GET https://api.kite.trade/instruments/NSE` |
| Content type | `text/csv` |
| SDK | `kite.instruments()` / `kite.instruments(exchange="NSE")` → **list of dicts**, already parsed and type-cast (not raw CSV) |

**CSV header, exact order:**

```
instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange
```

Types: `instrument_token` string, `exchange_token` string, `tradingsymbol` string, `name` string, `last_price` float64, `expiry` string, `strike` float64, `tick_size` float64, `lot_size` int64, `instrument_type` string (`EQ, FUT, CE, PE`), `segment` string, `exchange` string. The SDK's `_parse_instruments` converts `expiry` to a `date` and the numerics to int/float.

Sample rows:
```
408065,1594,INFY,INFOSYS,0,,,0.05,1,EQ,NSE,NSE
211616005,826625,BANKEX26AUGFUT,"BANKEX",0,2026-08-27,0,0.05,30,FUT,BFO-FUT,BFO
```

**Size (measured 2026-08-23, not a constant):** full dump 9,547,749 bytes uncompressed / 1,604,679 gzipped, 117,015 data rows + header. NSE-only: 678,954 bytes / 10,222 rows.

**Caching rule (docs, verbatim):** *"The instrument list API returns large amounts of data. It's best to request it once a day (ideally at around 08:30 AM) and store in a database at your end."* And: *"The dump is generated once everyday and hence `last_price` is not real time."* → varsity-algo fetches it once at ≥08:30 IST into `app/store/instruments.csv`. **Never** use the dump's `last_price` as a price source.

**Storage key rule (docs, verbatim):** *"For storage, it is recommended to use a combination of `exchange` and `tradingsymbol` as the unique key, not the numeric instrument token. Exchanges may reuse instrument tokens for different derivative instruments after each expiry."*

`[UNVERIFIED — empirical invariant, not documented]`: `instrument_token == (exchange_token << 8) | segment_code`; verified on all 117,015 live rows with 0 mismatches. Observed low-byte codes: NSE 1, NFO-FUT/OPT 2, CDS 3, BSE 4, BFO 5, MCX 7, INDICES 9, NCO 12. **Do not put a correctness-critical path on this** — always fall back to a CSV lookup.

`[UNVERIFIED — undocumented behaviour]`: both instrument-dump endpoints currently return HTTP 200 with **no auth headers at all** (probed 2026-08-23), while `/quote/ltp` and `/instruments/historical/...` return 400 without credentials. Keep the auth headers in the client anyway; Zerodha can close this at any time.

### 2.2 Historical candles

**URL:**
```
GET https://api.kite.trade/instruments/historical/{instrument_token}/{interval}?from={from}&to={to}&continuous={0|1}&oi={0|1}
```

**Documented `:interval` values (8):** `minute`, `day`, `3minute`, `5minute`, `10minute`, `15minute`, `30minute`, `60minute`.
`[UNVERIFIED — accepted by the API but absent from the docs]`: `2minute`, `4minute`, `hour`, `2hour`, `3hour`, `4hour`, `week`. Treat as unsupported for anything critical.

**Datetime format — the exact string:**

- Request (`from` / `to`): `yyyy-mm-dd hh:mm:ss`, e.g. `2017-12-15 09:15:00`.
- Python strftime, verbatim from the SDK: `date_string_format = "%Y-%m-%d %H:%M:%S"`
- URL-encoding of the space: both `+` and `%20` work; the docs' own examples are inconsistent.
- **Response timestamps use a DIFFERENT format:** ISO 8601 with offset, `2017-12-15T09:15:00+0530`. **Never round-trip a response timestamp back into `from`/`to`.**

**SDK signature — note the argument order is NOT the URL order:**

```python
def historical_data(self, instrument_token, from_date, to_date, interval, continuous=False, oi=False):
```

`from_date`/`to_date` come **before** `interval`. Accepts `datetime` objects or `"%Y-%m-%d %H:%M:%S"` strings.

**SDK return shape** — a list of dicts, **not** the raw arrays; the timestamp key is `"date"` (tz-aware datetime), not `"timestamp"`:

```python
{"date": <datetime>, "open": float, "high": float, "low": float, "close": float, "volume": int}
# plus "oi": int  — ONLY when the raw candle has 7 elements
```

Raw REST shape is `[timestamp, open, high, low, close, volume]`, becoming a **7-element** array when `oi=1`. Parse by length (`if len(d) == 7`), never by fixed unpacking.

`continuous=1`: day candles only, NFO and MCX **futures** only. Given a live contract's token it returns day candles for that instrument's expired contracts. Not a back-adjusted series; does not work for options or equities.

### 2.3 Per-interval MAX DATE RANGE PER REQUEST

`[UNVERIFIED — this table is NOT in the official docs.]` It is the enumeration of the API's own error string `interval exceeds max limit: N days`, collected on the Kite Connect forum. **Implementation requirement:** hardcode the table *and* parse that error string at runtime, widening/narrowing the chunk size from the parsed `N`.

| interval | max days / request |
|---|---|
| `minute` | 60 |
| `2minute` | 60 |
| `3minute` | 100 |
| `4minute` | 100 |
| `5minute` | 100 |
| `10minute` | 100 |
| `15minute` | 200 |
| `30minute` | 200 |
| `60minute` | 400 |
| `hour` | 400 |
| `2hour` | 400 |
| `3hour` | 400 |
| `4hour` | 400 |
| `day` | 2000 |
| `week` | 2000 |

This is a **per-request window, not the archive depth**. Zerodha staff: *"We have back filled the data with how much ever we had got back them. For some NSE stocks, day candles are back filled till late 1990s as well."* To go deeper, page backwards with repeated calls.

Historical candles are **not** corporate-action adjusted; splits/bonuses appear as raw price gaps and the API offers no adjustment factors.

### 2.4 Rate limits

| end-point | rate-limit |
|---|---|
| Quote | 1 req/second |
| Historical candle | 3 req/second |
| Order placement | 10 req/second |
| All other endpoints | 10 req/second |

Additional hard caps (docs, verbatim): *"There are limitations at 400 orders per minute and 10 orders per second."* / *"a single user/API key will not be able to place more than 5000 orders per day. This restriction is across all segments and varieties."* / *"a maximum of 25 modifications are allowed per order. Post that user has to cancel the order and place it again."*

Breach → **HTTP 429** *"Too many requests to the API (rate limiting)"*. There is no documented daily cap on quote or historical calls, only the per-second rate.

**Implementation:** one token-bucket per class in `app/kite/data.py` — `quote` bucket at 1/s, `historical` bucket at 3/s, `default` bucket at 10/s, `orders` bucket at 10/s with a 400/min and 5000/day counter.

### 2.5 Quote / OHLC / LTP

| endpoint | URL | max instruments per call | SDK |
|---|---|---|---|
| Full quote | `GET https://api.kite.trade/quote?i=...` | **500** | `kite.quote(*instruments)` |
| OHLC + LTP | `GET https://api.kite.trade/quote/ohlc?i=...` | **1000** | `kite.ohlc(*instruments)` |
| LTP only | `GET https://api.kite.trade/quote/ltp?i=...` | **1000** | `kite.ltp(*instruments)` |

Instrument identifier is `EXCHANGE:TRADINGSYMBOL`. The `i` query param **repeats** once per instrument:
`?i=NSE:INFY&i=BSE:SENSEX&i=NSE:NIFTY+50`. Symbols with spaces must be encoded (`+` or `%20`); the response map is still keyed by the decoded `"NSE:NIFTY 50"`.

Docs, repeated on all three endpoints: *"If there is no data available for a given key, the key will be absent from the response. The existence of all the instrument keys in the response map should be checked before to accessing them."* → **always `.get()`, never `[]`.**

Response shapes:

```json
/quote/ltp   → {"NSE:INFY":{"instrument_token":408065,"last_price":1074.35}}
/quote/ohlc  → {"NSE:INFY":{"instrument_token":408065,"last_price":1075,
                 "ohlc":{"open":1085.8,"high":1085.9,"low":1070.9,"close":1075.8}}}
/quote       → instrument_token, timestamp, last_trade_time, last_price, last_quantity,
               buy_quantity, sell_quantity, volume, average_price, oi, oi_day_high, oi_day_low,
               net_change, lower_circuit_limit, upper_circuit_limit,
               ohlc{open,high,low,close}, depth{buy[5]{price,quantity,orders}, sell[5]{...}}
```

`ohlc.close` = *"Closing price of the instrument from the last trading day"*. `net_change` = *"The absolute change from yesterday's close to last traded price"*.

SDK notes: all three accept varargs **or** a single list (`kite.ltp(["NSE:INFY","BSE:SENSEX"])`). Only `quote()` post-processes — it converts `timestamp` and `last_trade_time` to datetimes; `ohlc()` and `ltp()` return the raw dict. `ohlc()`'s docstring claims "and market depth" — that is **wrong**; `/quote/ohlc` returns no depth.

**Throughput ceiling:** Quote is 1 req/s, so `/quote/ltp` at 1000 instruments/call = 1000 instruments/second maximum. Anything faster must use the WebSocket (`KiteTicker`), not polling.

---

## 3. KITE ORDERS

### 3.1 `place_order` — full signature (kiteconnect 5.2.1)

```python
def place_order(self,
                variety,              # REQUIRED
                exchange,             # REQUIRED
                tradingsymbol,        # REQUIRED
                transaction_type,     # REQUIRED
                quantity,             # REQUIRED
                product,              # REQUIRED
                order_type,           # REQUIRED
                price=None,
                validity=None,
                validity_ttl=None,
                disclosed_quantity=None,
                trigger_price=None,
                iceberg_legs=None,
                iceberg_quantity=None,
                auction_number=None,
                algo_id=None,
                tag=None,
                market_protection=None):
```

Internals that matter: `params = locals()`, `del params["self"]`, then **every `None` is stripped**. Anything you pass as `0` or `""` **is sent**. Returns `self._post("order.place", url_args={"variety": variety}, params=params)["order_id"]` — i.e. the **bare `order_id` string**, already unwrapped.

### 3.2 Every constant string

```python
# Varieties (go into the URL path: POST /orders/:variety)
VARIETY_REGULAR   = "regular"
VARIETY_CO        = "co"
VARIETY_AMO       = "amo"
VARIETY_ICEBERG   = "iceberg"
VARIETY_AUCTION   = "auction"

# Products
PRODUCT_MIS  = "MIS"
PRODUCT_CNC  = "CNC"
PRODUCT_NRML = "NRML"
PRODUCT_CO   = "CO"
# "MTF" is a documented valid value with NO constant in the SDK — pass the literal "MTF".

# Order types
ORDER_TYPE_MARKET = "MARKET"
ORDER_TYPE_LIMIT  = "LIMIT"
ORDER_TYPE_SLM    = "SL-M"
ORDER_TYPE_SL     = "SL"

# Transaction type
TRANSACTION_TYPE_BUY  = "BUY"
TRANSACTION_TYPE_SELL = "SELL"

# Validity
VALIDITY_DAY = "DAY"
VALIDITY_IOC = "IOC"
VALIDITY_TTL = "TTL"

# Exchanges
EXCHANGE_NSE = "NSE"; EXCHANGE_BSE = "BSE"; EXCHANGE_NFO = "NFO"
EXCHANGE_CDS = "CDS"; EXCHANGE_BFO = "BFO"; EXCHANGE_MCX = "MCX"; EXCHANGE_BCD = "BCD"

# Market protection
MARKET_PROTECTION_AUTO = -1           # or a value > 0 and up to 100 = percent

# Position type (convert_position)
POSITION_TYPE_DAY = "day"; POSITION_TYPE_OVERNIGHT = "overnight"

# Margin segments
MARGIN_EQUITY = "equity"; MARGIN_COMMODITY = "commodity"

# Terminal order statuses (the ONLY three exposed as constants)
STATUS_COMPLETE  = "COMPLETE"
STATUS_REJECTED  = "REJECTED"
STATUS_CANCELLED = "CANCELLED"
# There is NO STATUS_OPEN constant, no VARIETY_BO, no PRODUCT_BO, no PRODUCT_MTF.

# GTT
GTT_TYPE_OCO = "two-leg"; GTT_TYPE_SINGLE = "single"
GTT_STATUS_ACTIVE = "active"; GTT_STATUS_TRIGGERED = "triggered"
GTT_STATUS_DISABLED = "disabled"; GTT_STATUS_EXPIRED = "expired"
GTT_STATUS_CANCELLED = "cancelled"; GTT_STATUS_REJECTED = "rejected"
GTT_STATUS_DELETED = "deleted"
```

Canonical varsity-algo call (NSE equity, delivery, market):

```python
order_id = kite.place_order(
    variety=kite.VARIETY_REGULAR,
    exchange=kite.EXCHANGE_NSE,
    tradingsymbol="ACC",
    transaction_type=kite.TRANSACTION_TYPE_BUY,
    quantity=1,
    product=kite.PRODUCT_CNC,
    order_type=kite.ORDER_TYPE_MARKET,
    validity=kite.VALIDITY_DAY,
    market_protection=kite.MARKET_PROTECTION_AUTO,
    tag="varsityalgo",          # alphanumeric, MAX 20 CHARS
)
```

Other order methods:

```python
kite.modify_order(variety, order_id, parent_order_id=None, quantity=None, price=None,
                  order_type=None, trigger_price=None, validity=None,
                  disclosed_quantity=None, market_protection=None)   -> order_id str
kite.cancel_order(variety, order_id, parent_order_id=None)           -> order_id str
kite.exit_order(variety, order_id, parent_order_id=None)             -> alias for cancel_order
```
Modifiable regular-order fields are exactly: `order_type`, `quantity`, `price`, `trigger_price`, `disclosed_quantity`, `validity`.

### 3.3 How to verify a fill — binding procedure

Docs, verbatim: *"Successful placement of an order via the API does not imply its successful execution. To know the true status of a placed order, you should scan the order history or retrieve the particular order's current details using its `order_id`."*

**Rejections arrive on TWO paths. Handling one alone silently loses orders.**

- **Path A (synchronous, pre-OMS):** Zerodha's RMS rejects before the exchange. `place_order()` **raises**; there is no `order_id`; *"Zerodha rejects them before they are sent to the exchanges"* so the order may never appear in `orders()` at all. Capture the exception message at place time — the orderbook is not a complete audit log.
- **Path B (asynchronous, post-OMS):** you get an `order_id`, then the order lands with `status == "REJECTED"`, `exchange_order_id == null`, `exchange_timestamp == null`, and `status_message` / `status_message_raw` populated.

**Required implementation:**

```python
try:
    order_id = kite.place_order(...)
except KiteException as e:
    # Path A. e.code = HTTP status, e.message = text. Persist and stop.
    raise

TERMINAL = {"COMPLETE", "REJECTED", "CANCELLED"}

def poll_until_terminal(kite, order_id, timeout_s=60, interval_s=1.0):
    while ...:
        snaps = kite.order_history(order_id)   # LIST of state snapshots, chronological
        cur = snaps[-1]                        # CURRENT state is the LAST element
        if cur["status"] in TERMINAL:
            return cur
        time.sleep(interval_s)                 # respect the 10 req/s bucket
```

**Fill test (both conditions):**
```python
filled = cur["status"] == "COMPLETE" and cur["filled_quantity"] == cur["quantity"] and cur["average_price"] > 0
```
Partial fill: `0 < filled_quantity < quantity` with `pending_quantity > 0`.

Everything not in `TERMINAL` is "still live" — the docs hedge *"There may be other values as well."* Documented interim statuses: `PUT ORDER REQ RECEIVED`, `VALIDATION PENDING`, `OPEN PENDING`, `MODIFY VALIDATION PENDING`, `MODIFY PENDING`, `TRIGGER PENDING`, `CANCEL PENDING`, `AMO REQ RECEIVED`; plus `OPEN`. **Switch on the three terminal constants and default everything else to live.**

For non-MARKET orders open all day, polling is impractical — the docs direct you to postbacks (or `KiteTicker.on_order_update`, fired when `data.get("type") == "order"`, callback receives `data["data"]`).

### 3.4 Order object — field names

`orders()` → `list`; `order_history(order_id)` → `list` of snapshots; both go through `_format_response`.

```
order_id, parent_order_id, exchange_order_id, modified, placed_by, variety, status,
tradingsymbol, exchange, instrument_token, transaction_type, order_type, product, validity,
price, quantity, trigger_price, average_price, pending_quantity, filled_quantity,
disclosed_quantity, order_timestamp, exchange_timestamp, exchange_update_timestamp,
status_message, status_message_raw, cancelled_quantity, auction_number, meta, tag, guid
```
Live responses may also carry `market_protection`, `validity_ttl`, and a `tags` array — none of which are in the attribute table.

`_format_response` converts to `datetime` **only when the string is exactly 19 chars**, and only for: `order_timestamp`, `exchange_timestamp`, `created`, `last_instalment`, `fill_timestamp`, `timestamp`, `last_trade_time`. **`exchange_update_timestamp` is NOT in that list and stays a string.**

### 3.5 Trades

`kite.trades()` (all today) / `kite.order_trades(order_id)`.

Docs attribute table names: `trade_id`, `order_id`, `exchange_order_id`, `tradingsymbol`, `exchange`, `instrument_token`, `transaction_type`, `product`, `average_price`, **`filled`**, `fill_timestamp`, `order_timestamp`, `exchange_timestamp`.

**The wire field is `quantity`, not `filled`** — confirmed by the docs' own JSON sample. Read `quantity`, fall back to `.get("filled")`.

In the trades response `order_timestamp` comes back time-only (`"16:00:36"`, 8 chars) so it stays a **string**, while `fill_timestamp` (19 chars) becomes a **datetime**.

### 3.6 Holdings — `kite.holdings()` → raw list (bypasses `_format_response`)

```
tradingsymbol, exchange, instrument_token, isin, t1_quantity, realised_quantity, quantity,
used_quantity, authorised_quantity, opening_quantity, authorised_date, price, average_price,
last_price, close_price, pnl, day_change, day_change_percentage, product,
collateral_quantity, collateral_type, discrepancy
```
Present in live JSON, absent from the docs table: `short_quantity`, `authorisation`, `mtf{quantity,used_quantity,average_price,value,initial_margin}`. `price` has **no description** in the docs and is 0 in every sample — do not use it; use `last_price`.

Semantics that bite:
- `quantity` = realised T+2 quantity. Freshly bought stock sits in `t1_quantity` and is **not** CNC-sellable yet.
- `used_quantity` = quantity already sold today.
- **Sellable today** = `quantity + t1_quantity - used_quantity`, capped by `authorised_quantity`.
- CNC SELL can still fail with **HTTP 428** *"N quantity needs authorisation at depository."* Authorisations are valid for one trading session (until 5:30 PM). `POST /portfolio/holdings/authorise` has **no SDK helper** — call it yourself, then redirect to `https://kite.zerodha.com/connect/portfolio/authorise/holdings/:api_key/:request_id`.

### 3.7 Positions — `kite.positions()` → `{"net": [...], "day": [...]}`

Identical field set in both lists:

```
tradingsymbol, exchange, instrument_token, product, quantity, overnight_quantity, multiplier,
average_price, close_price, last_price, value, pnl, m2m, unrealised, realised,
buy_quantity, buy_price, buy_value, buy_m2m,
sell_quantity, sell_price, sell_value, sell_m2m,
day_buy_quantity, day_buy_price, day_buy_value,
day_sell_quantity, day_sell_price, day_sell_value
```
There is no `day_buy_m2m` / `day_sell_m2m` — only `buy_m2m` and `sell_m2m`.

`net` is the actual current net portfolio; `day` is a snapshot of that day's buy/sell activity. Equity positions carried overnight move to holdings the next day.

**Exiting:** *"There are no special API calls for exiting instruments from holdings and positions portfolios."* Place an opposite BUY/SELL with **the same `product`** — a different product creates a new position.

`kite.convert_position(exchange, tradingsymbol, transaction_type, position_type, quantity, old_product, new_product)` → boolean.

### 3.8 Margins — `kite.margins(segment=None)`

- `margins()` → `{"equity": {...}, "commodity": {...}}`
- `margins("equity")` → the **inner** object directly (different nesting depth for the same data)

```
enabled (bool)
net (float)                       # deployable funds — USE THIS
available: {adhoc_margin, cash, opening_balance, live_balance, collateral, intraday_payin}
utilised:  {debits, exposure, m2m_realised, m2m_unrealised, option_premium, payout, span,
            holding_sales, turnover, liquid_collateral, stock_collateral, delivery}
```

`net` = *"Net cash balance available for trading (intraday_payin + adhoc_margin + collateral)"*, net of debits. `available.cash` is the **raw** cash balance and does **not** subtract `utilised.debits`. For "how much can I deploy right now" use `net` (or `available.live_balance`).

### 3.9 Exceptions

`error_type` → class via `getattr(kiteconnect.exceptions, error_type, GeneralException)`. Every exception carries `.code` (HTTP status) and `.message`.

Defined in `kiteconnect/exceptions.py`: `KiteException`, `GeneralException`, `TokenException`, `PermissionException`, `OrderException`, `InputException`, `DataException`, `NetworkException`.

**`MarginException`, `HoldingException` and `UserException` are documented by the API but NOT defined in the SDK** — they degrade to `GeneralException`. To distinguish "insufficient funds" from a generic 500, either inspect `exc.code` + message, or define the missing classes on `kiteconnect.exceptions` before your first call.

HTTP codes: 400 bad params · 403 session expired (relogin) · 404 · 405 · 410 · 429 rate limit · 500 · 502 OMS down · 503 · 504.

Classify rejections on `status_message_raw` prefixes, never on the human `status_message` (Zerodha rewrote all of them in 2019):
`RMS:Margin Exceeds` → insufficient funds · `RMS:Rule: Check holdings` → insufficient holdings / short-sell in CNC · `RMS:Rule: Check circuit limit` → price outside daily range · `16387 : Security is not allowed to trade in this market` / `16278 : The markets have not been opened for trading` / `TRANSACTION NOT ALLOWED IN CURRENT INSTRUMENT STATE` → outside trading hours, try AMO.

---

## 4. LLM LAYER

**Architecture rule:** one internal interface, two implementations. Anthropic goes through the **official `anthropic` SDK**. Everything else is the `openai` SDK pointed at a different `base_url`. **Do not use litellm.** Do not route Claude through an OpenAI-compatible shim.

### 4.1 Provider table

| provider | base_url | env var | 2 current model ids | JSON mode param | notes |
|---|---|---|---|---|---|
| **anthropic** | *(none — official SDK, no base_url override)* | `ANTHROPIC_API_KEY` | `claude-opus-5`, `claude-sonnet-5` | `output_config={"format":{"type":"json_schema","schema":{...}}}` on `messages.create`, **or** `output_format=<PydanticModel>` on `messages.parse` | **Official `anthropic` SDK only.** `thinking={"type":"adaptive"}`. `max_tokens` required. `budget_tokens` → **400**. `temperature`/`top_p`/`top_k` → **400**. No assistant prefill (400). `output_config={"effort": "low"\|"medium"\|"high"\|"xhigh"\|"max"}`. Stream when `max_tokens` is large. |
| groq | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` | `openai/gpt-oss-120b`, `openai/gpt-oss-20b` | `response_format={"type":"json_schema","json_schema":{"name":...,"strict":true,"schema":{...}}}` or `{"type":"json_object"}` | **All Llama chat models retired 2026-08-16.** `strict:true` honoured only on the two gpt-oss models. Structured outputs incompatible with streaming and tool use. Free tier ~30 RPM / 250 RPD on compound. |
| openrouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | `z-ai/glm-5.2`, `openai/gpt-oss-120b` | `response_format={"type":"json_schema","json_schema":{"name":...,"strict":true,"schema":{...,"additionalProperties":false}}}` | Set provider preference `require_parameters: true` or you get schema-less responses intermittently. Attribution header is now `X-OpenRouter-Title` (not `X-Title`). Free `:free` variants: 20 RPM / 50 RPD (1000 RPD after $10 credits), enforced globally. `GET /api/v1/models` is public, no auth. |
| together | `https://api.together.ai/v1` | `TOGETHER_API_KEY` | `deepseek-ai/DeepSeek-V4-Pro`, `openai/gpt-oss-120b` | `response_format={"type":"json_schema","json_schema":{"name":...,"schema":{...}}}`; also `{"type":"regex","pattern":...}` | Legacy host `api.together.xyz` still live. No static free tier — "dynamic per-model rate limits that scale with your sustained traffic". |
| fireworks | `https://api.fireworks.ai/inference/v1` | `FIREWORKS_API_KEY` | `accounts/fireworks/models/deepseek-v4-pro`, `accounts/fireworks/models/gpt-oss-120b` | `response_format={"type":"json_schema","json_schema":{"schema":Model.model_json_schema()}}` or `{"type":"json_object"}` | Full `accounts/fireworks/models/` prefix mandatory. Dots become `p` in slugs (`glm-5p2`, `kimi-k2p6`, `qwen3p7-plus`). **`json_schema` silently disables reasoning output.** No free tier. |
| cerebras | `https://api.cerebras.ai/v1` | `CEREBRAS_API_KEY` | `gpt-oss-120b`, `gemma-4-31b` | `response_format={"type":"json_schema", ...}` with `schema`/`name`/`strict` | Only two public models. Bare IDs, **no** vendor prefix (contrast Groq's `openai/gpt-oss-120b`). Free trial = $5 credits expiring in 30 days at **5 RPM**. |
| deepseek | `https://api.deepseek.com` *(no `/v1`)* | `DEEPSEEK_API_KEY` | `deepseek-v4-flash`, `deepseek-v4-pro` | `response_format={"type":"json_object"}` **only — no `json_schema`** | `deepseek-chat` / `deepseek-reasoner` no longer documented. Requires the literal word "json" in the prompt + a format example + a set `max_tokens`. Docs admit *"the API may occasionally return empty content."* No free tier. |
| gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` **(trailing slash required)** | `GEMINI_API_KEY` | `gemini-3.7-flash`, `gemini-3.5-flash` | `client.beta.chat.completions.parse(..., response_format=PydanticModel)` → `.choices[0].message.parsed` | OpenAI shim is officially **beta**. Reasoning cannot be disabled on 2.5 Pro / 3.x. Free tier covers Flash + Flash-Lite only. |
| mistral | `https://api.mistral.ai/v1` | `MISTRAL_API_KEY` | `mistral-medium-3.5`, `mistral-small-4` | `client.chat.parse(..., response_format=PydanticClass)` via the **`mistralai`** SDK; `{"type":"json_object"}` works over the OpenAI shim | `magistral` and `devstral` are deprecated. Plain chat works with the `openai` SDK; `.parse()` requires `mistralai`. Phone verification required to activate the free tier. |
| xai | `https://api.x.ai/v1` | `XAI_API_KEY` | `grok-4.6`, `grok-4.3` | `response_format.type ∈ {"json_schema","json_object","text"}`, schema under `response_format.json_schema` | No open-weight models, no standing free tier — sign-up credit only. |
| **ollama** *(zero-key local)* | `http://localhost:11434/v1/` | *(none)* — pass `api_key="ollama"`, required but ignored | `qwen3:8b`, `qwen3:4b-instruct-2507-q4_K_M` | **native**: top-level `format` = `"json"` or a raw JSON-Schema object. Over the `/v1` shim: `response_format` `json_object`/`json_schema` (only `json_schema.schema` is read; `name`/`strict` are silently discarded) | Native API root is `http://localhost:11434`. `ollama pull <tag>`, `ollama serve`. Install: `winget install -e --id Ollama.Ollama`. Models dir override: `OLLAMA_MODELS`. |

### 4.2 The registry (exact)

```python
# app/llm/registry.py
PROVIDERS = {
  "groq":       ("https://api.groq.com/openai/v1",                           "GROQ_API_KEY",       "openai/gpt-oss-120b"),
  "together":   ("https://api.together.ai/v1",                               "TOGETHER_API_KEY",   "deepseek-ai/DeepSeek-V4-Pro"),
  "openrouter": ("https://openrouter.ai/api/v1",                             "OPENROUTER_API_KEY", "z-ai/glm-5.2"),
  "deepseek":   ("https://api.deepseek.com",                                 "DEEPSEEK_API_KEY",   "deepseek-v4-flash"),
  "fireworks":  ("https://api.fireworks.ai/inference/v1",                    "FIREWORKS_API_KEY",  "accounts/fireworks/models/deepseek-v4-pro"),
  "cerebras":   ("https://api.cerebras.ai/v1",                               "CEREBRAS_API_KEY",   "gpt-oss-120b"),
  "mistral":    ("https://api.mistral.ai/v1",                                "MISTRAL_API_KEY",    "mistral-medium-3.5"),
  "gemini":     ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY",     "gemini-3.7-flash"),
  "xai":        ("https://api.x.ai/v1",                                      "XAI_API_KEY",        "grok-4.6"),
  "ollama":     ("http://localhost:11434/v1/",                               None,                 "qwen3:8b"),
}
# "anthropic" is deliberately absent — it is a separate branch (ClaudeProvider).
```

**Startup validation (required):** for the configured provider, call `GET {base_url}/models` and fail fast with a named error if the configured model id is absent. Model IDs are the #1 runtime failure — Groq retired all Llama chat models on 2026-08-16 and DeepSeek renamed its entire line.

### 4.3 The Claude branch — exact

```python
# app/llm/claude_provider.py
import anthropic
client = anthropic.Anthropic()          # resolves ANTHROPIC_API_KEY / auth profile

resp = client.messages.create(
    model="claude-opus-5",
    max_tokens=16000,                   # REQUIRED
    thinking={"type": "adaptive"},      # adaptive thinking; do NOT send budget_tokens
    output_config={"effort": "high"},   # low|medium|high|xhigh|max
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": user_text}],
)
for block in resp.content:
    if block.type == "text":
        ...
```

Rules:
- On Opus 5 thinking is **on by default**; `{"type":"adaptive"}` is equivalent to omitting it. `{"type":"disabled"}` is accepted only at effort ≤ `high` and is discouraged (it can leak tool calls into visible text and leak `<thinking>` tags).
- `thinking={"type":"adaptive","display":"summarized"}` if the dashboard should show reasoning; default `display` on Opus 5 is `"omitted"` (empty thinking text).
- Use `client.messages.stream(...)` + `.get_final_message()` whenever `max_tokens` is large; 128K output requires streaming.
- Never mix in `requests`/`httpx` for Claude.

---

## 5. STRUCTURED OUTPUT

The whole app extracts one canonical object from natural language — the strategy spec. Define it **once** as a Pydantic model and derive every provider's schema from `Model.model_json_schema()`.

**Schema design rules (these materially change accuracy, not just shape):**

1. Put a short free-text `evidence` field **first**, capped with `maxLength`, then the enums. Constrained decoding commits at the first distinguishing token; putting the classification first collapses reasoning into a direct answer (EMNLP 2024 found 100% of GPT-3.5 JSON-mode outputs emitted the answer key before the reason key).
2. Every enum must carry an `"unspecified"` member. Without it the model is mathematically forced to guess on dimensions the sentence never mentions.
3. Choose enum values with **distinct leading tokens**. `"crosses_above"` vs `"crosses_below"` are identical up to `crosses_` and get decided on a token with almost no signal — use `"above"` / `"below"`.
4. `additionalProperties: false`, all fields `required`, flat schema — no `$ref`, no `$defs`, no `oneOf`, no `patternProperties`. llama.cpp's JSON-Schema→GBNF converter (which Ollama inherits) supports only a subset and defaults `additionalProperties` to false.
5. A grammar guarantees **shape, never truth**. Monitor the rate at which `"unspecified"` is chosen — a suspiciously low rate means confabulation.

### 5.1 Tier A — Claude (official SDK)

Two supported paths. Prefer `parse()`.

```python
# Path 1 — parse() with a Pydantic model  (kwarg is output_format=, on messages.parse)
resp = client.messages.parse(
    model="claude-opus-5",
    max_tokens=16000,
    thinking={"type": "adaptive"},
    messages=[{"role": "user", "content": sentence}],
    output_format=StrategySpec,
)
spec = resp.parsed_output          # validated StrategySpec instance
```

```python
# Path 2 — raw schema on messages.create  (kwarg is output_config={"format": ...})
resp = client.messages.create(
    model="claude-opus-5",
    max_tokens=16000,
    thinking={"type": "adaptive"},
    output_config={
        "effort": "high",
        "format": {
            "type": "json_schema",
            "schema": StrategySpec.model_json_schema(),   # must contain
                                                          # "required" and
                                                          # "additionalProperties": false
        },
    },
    messages=[{"role": "user", "content": sentence}],
)
text = next(b.text for b in resp.content if b.type == "text")
spec = StrategySpec.model_validate_json(text)
```

Path 3 (only when you need a *side-effecting* call rather than a return value): **strict tool use** — `strict: True` as a **top-level field on the tool definition** (not on `tool_choice`), with `additionalProperties: false` and `required` in `input_schema`. Guarantees `tool_use.input` validates exactly. Parse tool inputs with `json.loads()`, never string-match the serialized input.

Constraint: `output_config.format` is **incompatible with document citations** (`citations: {enabled: true}` returns 400). varsity-algo does not use citations, so this is a non-issue — do not add them later without removing the format constraint.

### 5.2 Tier B — OpenAI-compatible providers

Three sub-dialects. Key the adapter on provider name, not on a capability guess.

**B1 — strict `json_schema` dict.** groq (gpt-oss only), together, openrouter, fireworks, cerebras, xai:

```python
resp = client.chat.completions.create(
    model=model_id,
    messages=[{"role": "system", "content": SYS}, {"role": "user", "content": sentence}],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "strategy_spec",
            "strict": True,
            "schema": StrategySpec.model_json_schema(),
        },
    },
    temperature=0,
)
spec = StrategySpec.model_validate_json(resp.choices[0].message.content)
```
- openrouter additionally needs `extra_body={"provider": {"require_parameters": True}}`.
- fireworks: setting `json_schema` **disables reasoning output**. If you need reasoning, put the schema in the prompt and omit `response_format`.
- groq: cannot combine with streaming or tool use.

**B2 — SDK `parse()` helper with a Pydantic class.** gemini and mistral:

```python
# gemini (OpenAI shim)
completion = client.beta.chat.completions.parse(
    model="gemini-3.7-flash",
    messages=[...],
    response_format=StrategySpec,
)
spec = completion.choices[0].message.parsed

# mistral (requires the mistralai SDK, not openai)
chat_response = mistral_client.chat.parse(
    model="mistral-medium-3.5", messages=[...],
    response_format=StrategySpec, max_tokens=1024, temperature=0,
)
```
Gemini's **native** (non-shim) API uses yet another shape — `response_format={"type":"text","mime_type":"application/json","schema": ...}` where `type` is `"text"`. varsity-algo uses the shim only; do not mix the two.

**B3 — `json_object` only.** deepseek:

```python
response_format={"type": "json_object"}
```
Mandatory companions: the literal word **"json"** in the system or user prompt, a pasted JSON format example, and an explicit `max_tokens` to avoid truncation. Always wrap in the repair loop — the docs admit empty-content responses.

### 5.3 Tier C — Ollama (local, zero key)

**Use the native endpoint**, not the `/v1` shim — the shim discards `strict` and `name`.

```python
import ollama
resp = ollama.chat(
    model="qwen3:4b-instruct-2507-q4_K_M",
    messages=[{"role": "system", "content": SYS_WITH_SCHEMA_TEXT},
              {"role": "user", "content": sentence}],
    format=StrategySpec.model_json_schema(),   # top-level `format`, schema UNWRAPPED
    think=False,                               # kill <think> blocks
    options={"temperature": 0, "top_k": 1, "seed": 42,
             "num_predict": 256, "num_ctx": 4096},
)
spec = StrategySpec.model_validate_json(resp.message.content)
```

Raw HTTP equivalent: `POST http://localhost:11434/api/chat` with `"stream": false`, `"think": false`, and top-level `"format": {...}`.

Ollama's own docs also require putting the schema **in the prompt**: *"Include the JSON schema as a string in your prompt to ground the model's response."* Grammar constrains the decoder; the prompt tells the model what the fields mean. For sub-8B models, adding 5–10 few-shot exemplars (covering negation and `unspecified`) is the single largest accuracy lift available — larger than moving up one model size.

**Model floor:** practical floor is a 3B–4B instruct model **with** grammar constraints — `qwen3:4b-instruct-2507-q4_K_M` (2.5 GB). Safe production choice: `qwen3:8b` (5.2 GB). `[UNVERIFIED planning numbers, not measurements]` all-fields-correct rate on a single-sentence → 6-enum extraction: 1–2B ≈55–70%, 3–4B ≈85–93%, 7–8B ≈94–98%. Build a 100-sentence gold set and measure per-field before trusting any of this.

Memory budget: `qwen3:4b-…-q4_K_M` ≈3.5–4 GB · `llama3.1:8b-instruct-q4_K_M` ≈6–6.5 GB · `qwen3:8b` ≈6.5–7 GB · `mistral-nemo:12b` ≈8.5–9 GB. **Never quantize below Q4_K_M** for this task — drop a model size instead (8B Q4_K_M beats 12B Q2_K here).

### 5.4 The fallback ladder — required for every tier

```python
def extract(sentence: str, provider: Provider) -> StrategySpec:
    for attempt, mode in enumerate(provider.modes):    # ["json_schema","json_object","prompt_only"]
        raw = provider.call(sentence, mode=mode, prior_error=last_err)
        raw = _strip_fences(raw)                       # ```json fences, <think> blocks
        try:
            spec = StrategySpec.model_validate_json(raw)
        except ValidationError as e:
            last_err = f"Your previous output failed validation: {e}. Return ONLY valid JSON matching the schema."
            continue
        problems = semantic_check(spec)                # e.g. comparator set but indicator == "unspecified"
        if problems:
            last_err = f"Your previous output was self-inconsistent: {problems}."
            continue
        return spec
    raise ExtractionFailed(sentence, last_err)         # log the row; never silently pass a bad spec
```

Ordering per tier:
- **Claude:** `messages.parse` → `output_config.format` → strict tool use. A validation failure here is a bug in the schema, not the model — log loudly.
- **OpenAI-compatible B1:** `json_schema` → `json_object` + schema-in-prompt → prompt-only + repair.
- **DeepSeek (B3):** starts at `json_object`; add the empty-content guard (`if not raw.strip(): retry`).
- **Ollama (C):** grammar-constrained → grammar + failure appended → grammar + few-shot exemplars. Max 2 retries; with `num_predict: 256` a local retry is nearly free. Never loop unbounded.

**Repair-loop invariant:** every failed attempt writes a row to the extraction log with `sentence`, `provider`, `model`, `mode`, `raw_output`, `error`. A silently-dropped bad extraction is the worst outcome in a trading app.

---

## 6. PACKAGING

### 6.1 `frontend/vite.config.js` — exact

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
```

**Deliberately no `rewrite`.** Keep the `/api` prefix on the FastAPI side. Frontend code calls **same-origin relative URLs only**:

```js
const r = await fetch('/api/health')     // NEVER 'http://localhost:8000/api/health'
```

Consequences: the URL is identical in dev (proxied) and prod (same origin), zero code changes between the two, no `VITE_API_URL` env var, and **no CORS middleware is needed at all**. `strictPort: true` makes Vite fail loudly instead of drifting to 5174.

Scaffold command (the bare `--` is required on npm 7+):

```
npm create vite@latest frontend -- --template react
```
Valid templates today: `vanilla`, `vanilla-ts`, `vue`, `vue-ts`, `react`, `react-compiler`, `react-ts`, `react-compiler-ts`, `preact`, `preact-ts`, `lit`, `lit-ts`, `svelte`, `svelte-ts`, `solid`, `solid-ts`, `qwik`, `qwik-ts`. **`react-swc` no longer exists.**

### 6.2 `app/main.py` — static mount + catch-all, exact, route order load-bearing

```python
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

# ============ ORDER IS LOAD-BEARING, TOP TO BOTTOM ============

# 1. ALL /api ROUTES FIRST
@app.get("/api/health")
def health():
    return {"status": "ok"}

# ... every other /api route registered here, before anything below ...

# 2. Vite's hashed build output  (dist/assets/index-a1b2c3.js, etc.)
app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

# 3. CATCH-ALL LAST — anything unmatched returns the SPA shell
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    return FileResponse(DIST / "index.html")
```

Why the order: Starlette/FastAPI match routes in **registration order**. A mount at `"/"` or the `/{full_path:path}` route registered before the API routes wins, and every API call returns `index.html` as 200 HTML. The tell-tale symptom is the frontend throwing `Unexpected token <, "<!doctype"... is not valid JSON` — that is HTML arriving where JSON was expected, not a JSON bug.

Why `StaticFiles(html=True)` alone is **not** a substitute: in html mode, on a miss Starlette looks for `404.html` and if absent does `raise HTTPException(status_code=404)`. It **never** falls back to `index.html` with a 200 for an unknown deep path, so React Router deep links and hard refresh on `/dashboard/settings` 404.

**Preferred alternative (FastAPI ≥ 0.138.0, which the pin already satisfies):**

```python
app.frontend("/", directory="frontend/dist", fallback="index.html")
# signature: app.frontend(path, directory, fallback="auto", check_dir="auto")
```
Docs, verbatim: *"FastAPI checks path operations first. The frontend files are checked only if no normal route matched, so your API won't be affected."* Order therefore does not matter with `app.frontend()` — but still declare it last by convention. The fallback fires only for GET/HEAD with `Accept: text/html`, so POST to a missing path still correctly 404s.

**Only if credentials were needed cross-origin** (they are not, with the proxy) would CORS apply. If it is ever added: `allow_methods` defaults to `["GET"]` only and `allow_headers` defaults to `[]`, and `["*"]` for origins/methods/headers is **forbidden** with `allow_credentials=True`.

### 6.3 Windows PowerShell venv — exact, with the ExecutionPolicy fix

Run the ExecutionPolicy line **first**, before the activate step — not as troubleshooting. It needs no admin rights.

```powershell
# 0. One-time, per-user. Answer Y at the prompt.
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# verify
Get-ExecutionPolicy -List

# 1. Create
python -m venv .venv

# 2. Activate (prompt becomes prefixed with (.venv))
.\.venv\Scripts\Activate.ps1

# 3. Install
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Deactivate
deactivate
```

The error this prevents:

```
.\.venv\Scripts\Activate.ps1 : File C:\...\.venv\Scripts\Activate.ps1 cannot be
loaded because running scripts is disabled on this system.
    + FullyQualifiedErrorId : UnauthorizedAccess
```

Session-only variant: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process`.
Sidestep entirely (no policy change): use `cmd.exe` and `.venv\Scripts\activate.bat`.

**PowerShell trap:** Windows 11's default shell is Windows PowerShell **5.1**, which has no `&&`. `cd app && python -m uvicorn ...` fails with *"The token '&&' is not a valid statement separator in this version."* Use `;`, separate lines, or `pwsh` (PowerShell 7). Check with `$PSVersionTable.PSVersion`.

### 6.4 One-command dev runner (works on Windows)

```
cd frontend
npm i -D concurrently
```

`frontend/package.json` — **inner quotes must be escaped double quotes**; concurrently's docs state *"Windows only supports double quotes"*, so single quotes silently fail:

```json
{
  "scripts": {
    "dev:web": "vite",
    "dev:api": "../.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000 --app-dir ..",
    "dev": "concurrently -k -n api,web -c blue,green \"npm:dev:api\" \"npm:dev:web\""
  }
}
```

The user types exactly one command:

```
npm run dev
```

`-k` (`--kill-others`) means Ctrl+C stops both — without it an orphaned uvicorn holds port 8000 and the next `npm run dev` dies with an uninterpretable bind error. `-n` labels the interleaved output. `npm:script-name` is concurrently's shorthand for `npm run script-name`.

Always `python -m uvicorn`, never bare `uvicorn` — `python -m` pins the interpreter even when the venv is not activated in that particular spawned subprocess.

**Fallback launcher for a non-expert — `dev.bat` in the repo root, double-clickable:**

```bat
@echo off
REM Two titled console windows, each with its own live log and its own Ctrl+C.
start "API"  cmd /k "cd /d %~dp0 && .venv\Scripts\activate.bat && python -m uvicorn app.main:app --reload --port 8000"
start "WEB"  cmd /k "cd /d %~dp0frontend && npm run dev"
```
`%~dp0` expands to the .bat's own directory with a trailing backslash, so it works from any cwd. Trade-off vs concurrently: closing one window does not stop the other.

Production run: `npm run build` in `frontend/`, then `fastapi run app/main.py` (reload off, binds 0.0.0.0:8000).

### 6.5 Config — `app/config.py`

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        extra="ignore", case_sensitive=False,
    )
    # required — app refuses to start with a named error if missing
    kite_api_key: str
    kite_api_secret: str
    # optional
    llm_provider: str = "ollama"
    llm_model: str = "qwen3:8b"
    anthropic_api_key: str | None = None
    dry_run: bool = True

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Use pydantic-settings, not bare python-dotenv: pydantic-settings *uses* python-dotenv internally, so it is not an extra dependency, and it fails at **boot** with `Field required: kite_api_secret` rather than mysteriously as a `None` deep inside a request handler.

`.gitignore` must contain: `.env`, `.venv/`, `__pycache__/`, `node_modules/`, `dist/`, `app/store/session.json`, `app/store/instruments.csv`.

---

## 7. GOTCHAS

1. **The checksum is plain SHA-256 of a bare concatenation, not an HMAC, no separator.** `hashlib.sha256(api_key + request_token + api_secret).hexdigest()`, that exact order, lowercase hex. Any reorder or added delimiter produces a valid-looking hex string the server rejects. *Fix:* call `kite.generate_session()` and never compute it by hand.

2. **`request_token` is single-use and lives only a few minutes.** A second exchange of the same token fails. *Fix:* exchange immediately; never cache or retry the request_token; cache the `access_token` instead.

3. **The login URL param order differs between the docs (`?v=3&api_key=`) and the SDK (`?api_key=&v=3`).** Both work. *Fix:* call `kite.login_url()`; do not hardcode either form and do not "correct" one to the other.

4. **The token expires "at 6 AM the next day" but the docs never write IST on that line, and the real flush is reported anywhere in 05:00–07:30 IST.** *Fix:* schedule the daily interactive re-login at **07:30 IST or later**. Never assume 06:01 is safe.

5. **There is no token renewal for ordinary apps.** `refresh_token` comes back as `""` and `renew_access_token()` is undocumented in the REST docs. *Fix:* design for a fresh interactive login every trading day; make re-login a first-class dashboard flow, not an error path.

6. **`generate_session()` mutates `login_time` from a string into a `datetime`.** `json.dumps()` on the returned dict raises `TypeError: Object of type datetime is not JSON serializable`. *Fix:* `data["login_time"] = data["login_time"].isoformat()` before persisting, or persist only the fields you need.

7. **`generate_session()` returns the unwrapped inner dict, not the `{"status","data"}` envelope.** Code written against the raw REST shape (`resp["data"]["access_token"]`) KeyErrors. *Fix:* index `data["access_token"]` directly.

8. **The `Authorization` header is attached only when BOTH `api_key` and `access_token` are truthy.** Construct `KiteConnect(api_key=...)` without a token and calls go out unauthenticated, failing with `InputException` "Invalid api_key or access_token" rather than a clear "missing token". *Fix:* assert the cached token is non-empty before constructing the client.

9. **Missing credentials return HTTP 400 `InputException`, not 403 `TokenException`.** Retry logic watching only 403 misses auth failure completely, and auth is validated *before* parameter validation, so you cannot discover a bad interval or range until you authenticate. *Fix:* handle 400+`InputException` and 403+`TokenException` as two distinct branches; register `set_session_expiry_hook()` rather than try/except around every call.

10. **Redirect URL and Postback URL are unrelated and use different checksum formulas.** Session = `sha256(api_key + request_token + api_secret)`; postback = `sha256(order_id + order_timestamp + api_secret)`. *Fix:* two separate functions with names that cannot be confused; unit-test both against the docs' examples.

11. **`historical_data()`'s argument order is `(instrument_token, from_date, to_date, interval)` — from/to come BEFORE interval, the opposite of the URL path.** Passing positionally in URL order silently transposes them. *Fix:* always call with keyword arguments.

12. **`historical_data()` returns dicts keyed `"date"`, not the raw `[timestamp, o, h, l, c, v]` arrays, and `"date"` is a tz-aware datetime.** Code written against the REST shape breaks. Also, `oi=1` appends a **7th** element. *Fix:* consume the SDK's dict shape; if you touch raw candles, branch on `len(d) == 7`.

13. **The per-interval max-range table is not in the docs and can change without notice.** *Fix:* hardcode the table, chunk requests to it, **and** parse the API's `interval exceeds max limit: N days` error at runtime to re-derive `N`.

14. **The response timestamp format (`2017-12-15T09:15:00+0530`) is not the request format (`2017-12-15 09:15:00`).** Feeding a response timestamp back into `from`/`to` fails. *Fix:* one formatter (`"%Y-%m-%d %H:%M:%S"`) for requests, one parser for responses; never share.

15. **Quote is 1 req/second — ten times stricter than everything else in the API.** Naive per-symbol polling throttles instantly. *Fix:* batch up to 1000 symbols into a single `/quote/ltp` call; above ~1000 symbols/second, switch to `KiteTicker` WebSocket.

16. **Quote responses silently omit keys for instruments with no data or expired contracts — no error is raised.** *Fix:* `data.get("NSE:INFY")` and handle `None`; never `data["NSE:INFY"]`.

17. **`place_order()` returns a bare `order_id` string, but `place_gtt()` returns `{"trigger_id": 123}` and `place_autoslice_order()` returns a dict with a children array.** Three unwrapping conventions in one client. *Fix:* wrap each in its own typed helper; never assume symmetry.

18. **An `order_id` says nothing about execution, and rejections arrive on two independent paths.** Pre-OMS RMS rejections raise from `place_order()` and may leave **no trace in `orders()` at all**; post-OMS rejections appear as `status == "REJECTED"`. *Fix:* try/except around `place_order` **and** poll `order_history(order_id)` — neither alone is sufficient. Persist the exception message at place time; the orderbook is not a complete audit log.

19. **`order_history(order_id)` returns a chronological LIST, not an object.** Reading `[0]` gives you `"PUT ORDER REQ RECEIVED"` forever. *Fix:* the current state is `snaps[-1]`.

20. **`MarginException`, `HoldingException` and `UserException` are documented by the API but not defined in `kiteconnect/exceptions.py`** — `getattr` degrades them to `GeneralException`, so "insufficient funds" is indistinguishable from a generic 500. *Fix:* define the three missing classes on `kiteconnect.exceptions` at import time, before the first call.

21. **`place_order` strips only `None`, so `price=0` on a MARKET order IS sent.** *Fix:* omit inapplicable fields entirely or pass `None` — never `0` or `""`.

22. **`tag` is capped at 20 alphanumeric characters.** Longer tags are rejected. *Fix:* validate client-side.

23. **In `trades()` the wire field is `quantity`, but the docs' attribute table calls it `filled`.** *Fix:* read `t["quantity"]`, fall back to `t.get("filled")`.

24. **`_format_response` converts timestamps to datetimes only when the string is exactly 19 chars**, so `exchange_update_timestamp` stays a string, and the trades' time-only `order_timestamp` ("16:00:36") stays a string while `fill_timestamp` becomes a datetime. `holdings()` and `positions()` bypass `_format_response` entirely. *Fix:* normalize everything through one coercion function before it reaches the API layer.

25. **`holdings()["quantity"]` is T+2 realised stock and is not everything you can sell.** Freshly bought stock is in `t1_quantity`; already-sold-today is in `used_quantity`. *Fix:* `sellable = quantity + t1_quantity - used_quantity`, capped by `authorised_quantity`.

26. **A CNC SELL of shares you actually own can still fail with HTTP 428** *"N quantity needs authorisation at depository."* The SDK has **no helper** for `POST /portfolio/holdings/authorise`. *Fix:* check `authorised_quantity` before selling; implement the 428 → authorise → redirect flow yourself; authorisations expire at 5:30 PM.

27. **`margins()["equity"]["available"]["cash"]` is the raw balance and does NOT subtract `utilised.debits`.** Sizing off it over-allocates. *Fix:* use `net` (or `available.live_balance`). Also note `margins()` and `margins("equity")` return different nesting depths.

28. **`product="MTF"` is documented but has no SDK constant; there is no `STATUS_OPEN`, no `VARIETY_BO`, no `PRODUCT_BO`.** *Fix:* pass literals where no constant exists; test terminality against the three terminal constants and treat everything else as live.

29. **Market orders are blocked for all stock options, far-dated index options, deep-ITM contracts, MCX options, and ETFs in the first two minutes.** SL-M is discontinued for index option contracts and blocked on BSE. *Fix:* for anything other than NSE equity CNC during market hours, default to LIMIT and surface the rejection string.

30. **A GTT is not an exchange-resting order and blocks no margin, so `status == "triggered"` does not mean the spawned order succeeded.** The real outcome lives at `trigger["orders"][i]["result"]["order_result"]["status"] / ["order_id"] / ["rejection_reason"]`, and `result` is `null` until it fires. `get_gtts()` only returns active GTTs plus the last 7 days of other states. *Fix:* read the nested `order_result`; fetch older triggers individually with `get_gtt(trigger_id)`, which works irrespective of age.

31. **Groq retired every Llama chat model on 2026-08-16, and DeepSeek renamed its entire line (`deepseek-chat`/`deepseek-reasoner` are gone).** Any tutorial or copied config using those IDs is already broken. *Fix:* call `GET {base_url}/models` at startup and fail fast with a named error if the configured ID is absent — never discover it as a 404 mid-request.

32. **The same logical model has different IDs on different providers** (`deepseek-v4-pro` on DeepSeek, `deepseek/deepseek-v4-pro` on OpenRouter, `accounts/fireworks/models/deepseek-v4-pro` on Fireworks). *Fix:* never share one model-ID constant across providers; the ID belongs in the per-provider registry row.

33. **Fireworks encodes dots as `p` in model slugs** (`glm-5p2`, `kimi-k2p6`, `qwen3p7-plus`) and requires the full `accounts/fireworks/models/` prefix; its own quickstart page contradicts its recommended-models page. *Fix:* trust `GET /v1/models`, not the docs.

34. **Gemini's base_url needs both `/v1beta/openai/` and the trailing slash.** Dropping either breaks it. *Fix:* copy the string from the registry table verbatim.

35. **There are three incompatible `response_format` dialects plus Ollama's own `format`.** A one-size-fits-all structured-output wrapper silently fails on at least three providers — you get unconstrained output that happens to look right in dev. *Fix:* one adapter function per dialect, keyed on provider name, with a smoke test per provider in CI.

36. **Fireworks' `json_schema` silently disables reasoning output; Groq's structured outputs are incompatible with streaming and tool use.** Both are silent quality regressions, not errors. *Fix:* if you need reasoning on Fireworks, put the schema in the prompt and omit `response_format`; never combine Groq structured outputs with streaming.

37. **Routing Claude through an OpenAI shim silently costs you** the native `system` parameter, prompt caching via `cache_control`, extended-thinking blocks, the `tool_use`/`tool_result` protocol, fine-grained streaming events, and accurate cache token accounting. *Fix:* `ClaudeProvider` implements the same internal interface but is backed by `anthropic.Anthropic().messages.create()`. Never `openai.OpenAI(base_url="…anthropic…")`.

38. **On Claude Opus 5, `budget_tokens`, `temperature`, `top_p`, `top_k`, and assistant prefill all return 400.** Recalled patterns from older models will hard-fail. *Fix:* `thinking={"type":"adaptive"}` for depth, `output_config={"effort": ...}` for spend, structured outputs for format control.

39. **Thinking/reasoning models wreck local JSON mode** — `<think>` blocks land inside or ahead of the constrained region and eat the token budget. *Fix:* pass Ollama's `"think": false`, or use the explicitly non-thinking tags (`qwen3:4b-instruct-2507-*`). Strip `<think>…</think>` and ``` fences before validating, always.

40. **Ollama's `/v1` shim reads only `json_schema.schema` and silently discards `name` and `strict`.** `strict: true` means nothing there. *Fix:* use the native `/api/chat` endpoint with top-level `format`.

41. **A grammar guarantees shape, never truth — and without an `"unspecified"` enum member the model is forced to guess.** A wrong value becomes indistinguishable from a right one by validation. *Fix:* add the escape hatch to every enum, put a `maxLength`-capped free-text `evidence` field first, choose enum values with distinct leading tokens, and monitor the `"unspecified"` rate.

42. **Trading-sentence failure modes to write explicit tests for**, in priority order: (a) negation/direction inversion — "short unless RSI is NOT above 70"; (b) period-vs-threshold confusion — "14-period RSI above 70" yielding `threshold=14`; (c) unit ambiguity — "2%" as `2` vs `0.02`; (d) implied timeframe filled with the training prior (`1d`) instead of `"unspecified"`; (e) compound sentences collapsing two conditions into one object; (f) ticker names bleeding into the indicator field. *Fix:* a 100-sentence gold set with per-field accuracy, run in CI against the configured local model.

43. **The Vite proxy target must be `127.0.0.1`, not `localhost`.** Node 17+ resolves `localhost` to IPv6 `::1` first; uvicorn binds IPv4. Symptom: intermittent `ECONNREFUSED ::1:8000` while `curl` to the same URL works. *Fix:* literally `http://127.0.0.1:8000`.

44. **`StaticFiles(html=True)` does not fix SPA deep links.** On a miss it serves `404.html` if present, otherwise raises 404 — it never returns `index.html` with a 200. Hard-refresh on `/positions` 404s. *Fix:* `app.frontend(..., fallback="index.html")` or the explicit catch-all in §6.2.

45. **Registering the catch-all (or any mount at `/`) before the `/api` routes makes every API call return `index.html` as 200 HTML.** Symptom: `Unexpected token <, "<!doctype"... is not valid JSON` in the browser console. *Fix:* API routes first, `/assets` mount second, catch-all last — or use `app.frontend()`, where FastAPI checks path operations first regardless of order.

46. **Windows PowerShell 5.1 (the Windows 11 default) has no `&&`.** Any `cd x && y` line errors with *"The token '&&' is not a valid statement separator in this version."* *Fix:* `;`, separate lines, or PowerShell 7 (`pwsh`).

47. **`.\.venv\Scripts\Activate.ps1` fails on a fresh Windows machine** because the default execution policy is `Restricted`. *Fix:* run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` **before** the activate step (no admin needed), or use `cmd.exe` + `activate.bat`.

48. **In `package.json`, concurrently's inner quotes must be escaped double quotes on Windows** — the single-quoted form from macOS/Linux examples silently fails. And without `-k`, Ctrl+C leaves an orphaned uvicorn holding port 8000. *Fix:* use the exact script block in §6.4.

49. **Vite 8 requires Node 20.19+ or 22.12+ — Node 21.x and 22.0–22.11 are rejected**, and the `react-swc` template no longer exists. *Fix:* `node --version` as step zero of the setup guide; scaffold with `--template react`.

50. **In production, `app.frontend()` / `StaticFiles` serve whatever is on disk in `dist/`.** Editing React and refreshing the FastAPI-served page shows nothing. *Fix:* the guide must state that `npm run build` is required after every frontend change in production mode; hot reload exists only on the Vite dev server at :5173.

51. **`DRY_RUN=true` must be the default in `.env.example` and in `Settings`.** The first thing a non-expert does is run the app. *Fix:* `place_order` is only reachable when `settings.dry_run is False`, and the dashboard renders a persistent red "LIVE" banner in that state.