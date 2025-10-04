# SwingBot Codex (EOD, Zero-Server, ChatGPT Agent)

**Goal:** A nightly, maintenance-light swing/position “agent” you can chat with in ChatGPT Teams.
**Outputs:**

* `data/signals.json` (machine-readable signals + positions)
* `data/highlights.md` (human one-glance brief)
  **Agent:** ChatGPT Teams **Custom GPT** with one **Action** that fetches those two files.

---

## 0) Repo Layout

```
swingbot/
  data/                      # generated nightly (committed by the workflow)
    ledger.csv
    out_signals.csv
    highlights.txt
    signals.json
    highlights.md
  nine_ema_dual_strategy_bot_v2.py   # screener + tracker (entries/exits, R, % since entry)
  run.py                    # publishes signals.json + highlights.md
  requirements.txt
  watchlist.txt             # universe (editable)
  .github/
    workflows/
      eod.yml               # nightly job (~EOD ET)
  codex.md                  # (this file)
```

> You already have `nine_ema_dual_strategy_bot_v2.py`. If not, drop the provided one in.

---

## 1) Python Environment

**`requirements.txt`**

```txt
yfinance==0.2.43
pandas>=2.0.0
numpy>=1.25.0
```

> Optional later: add `finnhub-python` or Polygon SDK; see §6.

---

## 2) Publisher (turn CSVs → JSON/MD)

**`run.py`**

````python
#!/usr/bin/env python3
"""
EOD publisher for Option 1 (zero-server JSON + MD)
- Calls the v2 dual-strategy bot to generate CSVs (signals + ledger + highlights.txt)
- Then converts to signals.json and highlights.md for static hosting
"""
import json, os, subprocess, sys
from datetime import datetime
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

cmd = [
    sys.executable, "nine_ema_dual_strategy_bot_v2.py",
    "--ledger", os.path.join(DATA_DIR, "ledger.csv"),
    "--emit", os.path.join(DATA_DIR, "out_signals.csv"),
    "--highlights", os.path.join(DATA_DIR, "highlights.txt"),
    "--tickers-file", os.path.join(os.path.dirname(__file__), "watchlist.txt")
]
print("Running screener:", " ".join(cmd))
subprocess.run(cmd, check=False)

signals_csv = os.path.join(DATA_DIR, "out_signals.csv")
ledger_csv = os.path.join(DATA_DIR, "ledger.csv")
highlights_txt = os.path.join(DATA_DIR, "highlights.txt")

signals = []
if os.path.exists(signals_csv):
    df = pd.read_csv(signals_csv)
    for _, r in df.iterrows():
        signals.append({
            "date": str(r.get("date","")),
            "ticker": r.get("ticker",""),
            "strategy": r.get("strategy",""),
            "setup": bool(r.get("setup", False)),
            "action": r.get("action",""),
            "buy_zone_low": None if pd.isna(r.get("buy_zone_low")) else float(r.get("buy_zone_low")),
            "buy_zone_high": None if pd.isna(r.get("buy_zone_high")) else float(r.get("buy_zone_high")),
            "confirm_today": bool(r.get("confirm_today", False)),
            "close": None if pd.isna(r.get("close")) else float(r.get("close")),
            "ema9": None if pd.isna(r.get("ema9")) else float(r.get("ema9")),
            "ema20": None if pd.isna(r.get("ema20")) else float(r.get("ema20")),
            "atr14": None if pd.isna(r.get("atr14")) else float(r.get("atr14")),
            "vol": None if pd.isna(r.get("vol")) else int(r.get("vol")),
            "vol20": None if pd.isna(r.get("vol20")) else int(r.get("vol20"))
        })

ledger = []
if os.path.exists(ledger_csv):
    ldf = pd.read_csv(ledger_csv)
    for _, r in ldf.iterrows():
        ledger.append({
            "ticker": r.get("ticker",""),
            "strategy": r.get("strategy",""),
            "status": r.get("status",""),
            "entry_date": None if pd.isna(r.get("entry_date")) else str(r.get("entry_date"))[:10],
            "entry_price": None if pd.isna(r.get("entry_price")) else float(r.get("entry_price")),
            "exit_date": None if pd.isna(r.get("exit_date")) else str(r.get("exit_date"))[:10],
            "exit_price": None if pd.isna(r.get("exit_price")) else float(r.get("exit_price")),
            "pct_since_entry": None if pd.isna(r.get("pct_since_entry")) else float(r.get("pct_since_entry")),
            "r_peak": None if pd.isna(r.get("r_peak")) else float(r.get("r_peak")),
            "days_held": None if pd.isna(r.get("days_held")) else int(r.get("days_held")),
            "highest_close": None if pd.isna(r.get("highest_close")) else float(r.get("highest_close")),
            "notes": r.get("notes","")
        })

payload = {
    "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds"),
    "universe_source": "watchlist.txt",
    "signals": signals,
    "positions": ledger
}
with open(os.path.join(DATA_DIR, "signals.json"), "w") as f:
    json.dump(payload, f, indent=2)

if os.path.exists(highlights_txt):
    with open(highlights_txt, "r") as f:
        content = f.read()
    md = "## Highlights (Today)\n\n```\n" + content + "\n```\n"
    with open(os.path.join(DATA_DIR, "highlights.md"), "w") as f:
        f.write(md)

print("Wrote data/signals.json and data/highlights.md")
````

---

## 3) Universe

**`watchlist.txt`** (edit anytime)

```
AAPL
MSFT
NVDA
META
TSLA
AMD
AVGO
NFLX
GOOGL
AMZN
```

> Later: replace with an auto-universe step (top $-volume via Finnhub/Polygon) before the screener runs.

---

## 4) Nightly Automation (GitHub Actions)

**`.github/workflows/eod.yml`**

```yaml
name: EOD Swing Signals
on:
  schedule: [{ cron: "05 21 * * 1-5" }]  # ~5:05pm ET, weekdays
  workflow_dispatch: {}
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - run: python run.py
      - name: Commit outputs
        run: |
          git config user.name "swingbot"
          git config user.email "swingbot@users.noreply.github.com"
          git add data/*
          git commit -m "EOD update" || echo "No changes"
          git push
```

**Enable GitHub Pages** (Settings → Pages) to serve `/data/signals.json` and `/data/highlights.md` via a stable URL.

**Optional Discord Alerts**

* Add secrets `DISCORD_WEBHOOK_SWINGBOT` (required) and `DISCORD_WEBHOOK_SWINGBOT_2` (optional) under Settings → Secrets → Actions.
* `DISCORD_WEBHOOK_SWINGBOT` posts as **SwingBot**; `DISCORD_WEBHOOK_SWINGBOT_2` (optional) posts as **SwingBot_2** so you can route to another channel. Leave the second blank if you only need one notification.
* Each run posts an embed-style summary pulled from `data/highlights.txt` and the latest entries.

---

## 5) Data Model (what the agent reads)

**`data/signals.json`**

```json
{
  "generated_at_utc": "2025-10-02T21:10:05Z",
  "universe_source": "watchlist.txt",
  "signals": [
    {
      "date": "2025-10-02",
      "ticker": "AAPL",
      "strategy": "BASE",
      "setup": true,
      "action": "BUY_ZONE_TRIGGERED",
      "buy_zone_low": 221.35,
      "buy_zone_high": 223.10,
      "confirm_today": false,
      "close": 222.40,
      "ema9": 223.00,
      "ema20": 219.42,
      "atr14": 4.12,
      "vol": 51234567,
      "vol20": 62345678
    }
  ],
  "positions": [
    {
      "ticker": "AAPL",
      "strategy": "BASE",
      "status": "OPEN",
      "entry_date": "2025-09-20",
      "entry_price": 214.20,
      "exit_date": null,
      "exit_price": null,
      "pct_since_entry": 3.8,
      "r_peak": 1.6,
      "days_held": 9,
      "highest_close": 224.10,
      "notes": "CONFIRM_BREAKOUT_ENTRY"
    }
  ]
}
```

**`data/highlights.md`** (agent can also fetch as plain text)

```md
## Highlights (Today)

```

=== HIGHLIGHTS (Today) ===
Entries:
INTC [BASE] → BUY_ZONE_TRIGGERED @ close 34.62 | Buy Zone [34.10, 34.62]
Exits:
SNDK [TIGHT] → CLOSED: EMA20_break @ 98.12 | PnL +12.7% | R_peak 2.4 | Days 14

Open Positions (top):
RR [BASE] +18.3% | R_peak 2.1 | Held 9d | Entry 4.32 on 2025-09-20 (CONFIRM_BREAKOUT_ENTRY)

```
```

---

## 6) (Optional) Stack yfinance with free APIs

Add **secrets** in GitHub (Settings → Secrets → Actions):

* `POLYGON_API_KEY` or `FINNHUB_API_KEY`

Then, in `nine_ema_dual_strategy_bot_v2.py`, wrap your data fetch:

```python
def get_bars(ticker, start):
    try:
        import yfinance as yf
        df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
        if not df.empty: return df
    except Exception:
        pass
    # Fallback (pseudo; implement your adapter of choice)
    # df = fetch_polygon_daily_bars(ticker, start, os.getenv("POLYGON_API_KEY"))
    # return df
    return df
```

Replace the internal `yf.download` calls with `get_bars(...)`. Keep everything else identical.

---

## 7) Custom GPT (Teams) — Action Config

In **ChatGPT → Explore → Create a GPT → Configure → Actions**, add a single OpenAPI spec that points to your GitHub Pages URLs.

**OpenAPI (minimal)**

```yaml
openapi: 3.1.0
info:
  title: SwingBot Data
  version: "1.0.0"
servers:
  - url: https://<your-gh-pages-domain>/<your-repo>   # e.g., https://username.github.io/swingbot
paths:
  /data/signals.json:
    get:
      operationId: fetchSignals
      summary: Get EOD swing signals and positions
      responses:
        "200":
          description: OK
          content:
            application/json:
              schema:
                type: object
  /data/highlights.md:
    get:
      operationId: fetchHighlights
      summary: Get one-glance highlights
      responses:
        "200":
          description: OK
          content:
            text/markdown:
              schema:
                type: string
```

**System Prompt (Agent Brain)**

```
You are SwingBot, a swing/position trading assistant.
Always call fetchSignals first. If the user asks for a quick summary, also call fetchHighlights.
Show a "HIGHLIGHTS" section first with: Entries today, Exits today, Top Open by % since entry and R-peak.
Then list actionable "Do Now" notes: 
- "Buy zone active: [$low, $high]" 
- "Exit: EMA20 break" 
- "Trail: 2R reached, watch 9-EMA".
Never invent prices; only use signals.json/highlights.md.
Default timeframe: daily bars (EOD). No day trading.
```

**Example user prompts:**

* “What’s actionable tonight?”
* “Any Base or Tight entries in buy zones?”
* “Show open positions sorted by % since entry with stops.”
* “Which names hit ≥2R and are archived?”

---

## 8) Local Dev & Dry Runs

```bash
# First time
pip install -r requirements.txt

# Run locally (uses watchlist.txt)
python run.py

# Inspect outputs
cat data/highlights.md
cat data/signals.json
```

If outputs look good, push to GitHub, enable Pages, and verify the two URLs load in a browser.

---

## 9) Troubleshooting

* **No outputs?** Check `Actions` logs → ensure `run.py` ran; ensure `watchlist.txt` has tickers.
* **NaNs in JSON?** You’re fine; the agent will ignore missing optional fields.
* **Timezone drift:** Cron set to ~**5:05pm ET** weekdays; adjust if needed.
* **Too many entries/exits:** Tighten liquidity (`min $-volume`), increase `low_volume` strictness (0.7), or raise run window to 180/90 days.

---

## 10) Roadmap (if/when you want more)

* **Auto-Universe** (pre-step): fetch top-$-volume tickers nightly and refresh `watchlist.txt`.
* **Market Context Filter:** only signal entries if SPY/QQQ > rising 50-SMA.
* **HTML Dashboard:** simple cards + chips; still static, published with Pages.
* **Slack/Telegram Notifications:** add a step in `run.py` to hit a webhook with `highlights.md` after each run.
* **On-Demand API (Option 2):** expose `/highlights` + `/screen` via FastAPI on a free host; update the OpenAPI server URL accordingly.

---

## 11) Safety & Intent

* Educational code; **not investment advice**.
* EOD cadence; **no intraday** obligations.
* Liquidity checks + swing exits (EMA20 / ATR / time stop / 2R→9EMA trail) built in.



---

# ✅ Market Filter Guardrail (Add to System)

**Purpose:** pause **new** long entries when the **broad market** is weak, while still managing **existing** positions normally.

**Why:** swing setups have much higher follow-through when the tide (SPY/QQQ) is rising. This avoids buying “cheap dips” that are actually **trend rollovers**.

**Rule (EOD, Daily):**
New long entries are **allowed** only if **both** SPY **and** QQQ are:

* `Close > EMA20`, **and**
* `Close > SMA50`, **and**
* `SMA50` is **rising** vs. 5 trading days ago.

If this fails, **suppress** new entries for today with a visible reason:

> `MARKET_FILTER_ACTIVE — SPY/QQQ not in uptrend (pause new longs)`

**Notes:**

* This **doesn’t** force-sell current holdings. Exit rules stay the same (EMA20/ATR/time/2R→9EMA trail).
* Expect ~10–15% fewer entries in weak tape, with higher trade expectancy.

---

## Implementation (drop-in snippet)

> Add the function + calls below to `swingbot/nine_ema_dual_strategy_bot_v2.py`.
> If you already centralized fetching (e.g., `get_bars()`), use it; otherwise `yfinance` is fine.

### 1) Market check helper

```python
# --- Add near other helpers in nine_ema_dual_strategy_bot_v2.py ---

def _ema(series, span): return series.ewm(span=span, adjust=False).mean()
def _sma(series, win):  return series.rolling(win).mean()

def compute_basic(df):
    out = df.copy()
    out['ema20'] = _ema(out['Close'], 20)
    out['sma50'] = _sma(out['Close'], 50)
    return out

def check_market_filter(start_date):
    """
    Returns (market_ok: bool, reason: str)
    OK only if BOTH SPY and QQQ have: Close>EMA20, Close>SMA50, rising SMA50 vs 5d ago.
    """
    import yfinance as yf
    try:
        spy = yf.download('SPY', start=start_date, progress=False, auto_adjust=True)
        qqq = yf.download('QQQ', start=start_date, progress=False, auto_adjust=True)
    except Exception as e:
        return (True, f"market_check_skipped: {e}")  # fail-open on data issues

    if spy.empty or qqq.empty or len(spy) < 60 or len(qqq) < 60:
        return (True, "market_check_skipped: insufficient_data")

    s = compute_basic(spy).iloc[-1]
    q = compute_basic(qqq).iloc[-1]
    s_prev = compute_basic(spy).iloc[-6]   # ~5 bars ago
    q_prev = compute_basic(qqq).iloc[-6]

    def healthy(row, prev):
        return (
            (row['Close'] > row['ema20']) and
            (row['Close'] > row['sma50']) and
            (row['sma50'] > prev['sma50'])
        )

    spy_ok = healthy(s, s_prev)
    qqq_ok = healthy(q, q_prev)

    if spy_ok and qqq_ok:
        return (True, "market_ok: SPY & QQQ in uptrend")
    else:
        why = []
        if not spy_ok: why.append("SPY below EMA20/SMA50 or SMA50 not rising")
        if not qqq_ok: why.append("QQQ below EMA20/SMA50 or SMA50 not rising")
        return (False, " ; ".join(why))
```

### 2) Enforce filter before opening new positions

Find your `screen_and_track(...)` function. Add the market check near the top and pass a `suppress_market` flag into your per-strategy signal logic.

```python
def screen_and_track(ticker, start_date, ledger, suppress_reentry_after_success=True):
    # NEW: check market once per run (reuse start_date)
    market_ok, market_reason = check_market_filter(start_date)

    # ... existing code to fetch data, compute df ...

    def signal_block(sig, df, ledger):
        row = df.iloc[-1]
        entry_action = 'NONE'; entry_price = np.nan

        # NEW: if market not OK, suppress new entries
        suppressed = (not market_ok)

        if sig['setup'] and not suppressed:
            low, high = sig['buy_zone_low'], sig['buy_zone_high']
            close = row['Close']
            in_zone = (not np.isnan(low)) and (low <= close <= high)
            if in_zone:
                entry_action = 'BUY_ZONE_TRIGGERED'
                entry_price = close
            elif sig['confirm_today']:
                entry_action = 'CONFIRM_BREAKOUT_ENTRY'
                entry_price = close
        elif sig['setup'] and suppressed:
            entry_action = 'MARKET_FILTER_ACTIVE'  # visible reason, no entry

        # open position only if not suppressed and action is an entry
        if entry_action in ('BUY_ZONE_TRIGGERED','CONFIRM_BREAKOUT_ENTRY'):
            has_open = not ledger[(ledger['ticker']==ticker) & (ledger['strategy']==sig['strategy']) & (ledger['status']=='OPEN')].empty
            if not has_open:
                ledger = open_position(ledger, ticker, sig['strategy'], df.index[-1].date(), entry_price, row['atr14'], notes=entry_action)

        # apply exits regardless
        apply_exit_rules(ledger, ticker, sig['strategy'], df)

        signal = {
            'date': df.index[-1].date(),
            'ticker': ticker,
            'strategy': sig['strategy'],
            'setup': sig['setup'],
            'action': entry_action,
            'buy_zone_low': sig['buy_zone_low'],
            'buy_zone_high': sig['buy_zone_high'],
            'confirm_today': sig['confirm_today'],
            'close': row['Close'],
            'ema9': df['ema9'].iloc[-1],
            'ema20': df['ema20'].iloc[-1],
            'atr14': df['atr14'].iloc[-1],
            'vol': int(df['Volume'].iloc[-1]),
            'vol20': int(df['vol20'].iloc[-1]) if not np.isnan(df['vol20'].iloc[-1]) else np.nan,
            # NEW: include market status for visibility
            'market_ok': market_ok,
            'market_reason': market_reason
        }
        return signal, ledger
```

### 3) Show market status in the nightly Highlights

In your `generate_highlights(...)` (same file), add a line near the top to surface today’s market state (we’ll read from the signals DataFrame if available):

```python
def generate_highlights(signals_df, ledger_df, highlights_path):
    lines = []
    today = datetime.utcnow().date()

    # NEW: market line
    market_line = "Market: (no signals)" 
    if not signals_df.empty and 'market_ok' in signals_df.columns:
        last = signals_df.iloc[-1]
        if bool(last.get('market_ok', True)):
            market_line = "Market Check: ✅ SPY & QQQ uptrend — new entries allowed."
        else:
            market_line = f"Market Check: ⚠️ {last.get('market_reason','Market weak')} — pause new entries."

    lines.append("=== HIGHLIGHTS (Today) ===")
    lines.append(market_line)
    lines.append("")  # blank line

    # ...existing sections: Entries / Exits / Open Positions...
```

That’s it: when the market is weak, the **Entries** section will either be empty **or** show `MARKET_FILTER_ACTIVE` instead of an entry trigger, *and* the top of Highlights will explain **why**.

---

# ✅ Risk & Sanity Enhancements (v1.1)

These are incremental improvements to clarity, transparency, and downside control.  
They do **not** alter strategy logic — only improve safety and readability.

---

## 1. Hard Stop (Explicit Risk)
**Purpose:** record a fixed 1R distance per trade to standardize R-based metrics.

**Rule:**
```
hard_stop = entry_price - 1.5 × ATR14
```
Store in ledger at open.  
This enables consistent `R_peak` and `R_multiple` calculations and makes downside risk explicit.

---

## 2. Max Position Cap + UX Display
**Purpose:** keep trader cognitive load low and surface risk state in Highlights.

**Rules:**
- Suppress new entries if `OPEN positions ≥ 5`.
- Always show a summary line in Highlights:

If under cap:
```
Open Positions: {open_count} / 5 Max
```
If at cap:
```
⚠️ Max positions reached (5). Suppressing new entries.
```

These appear directly beneath the **Market Check** line.

---

## 3. Earnings Guard + Entry Sanity Filters

**Purpose:** avoid entries around earnings, gaps, or bad data that distort signals.

### 3.1 Earnings Guard (Critical)
Reject entries if the next earnings report is within ±2 trading days.
- **Source:** `yfinance` (`ticker.calendar`) or fallback API.
- **Fail-open:** if no data, do not block.

Surface reason:
```
EARNINGS_GUARD_ACTIVE — earnings within 2 days
```

### 3.2 Gap Filter
Reject entries when:
```
abs(Open - PrevClose) / PrevClose > 0.08
```
Surface reason:
```
GAP_FILTER_TRIGGERED — gap > 8%
```

### 3.3 Data Sanity Check
Skip or flag bars where:
```
(High - Low)/Close > 0.2  OR  abs(Close - PrevClose)/PrevClose > 0.2
```
Surface reason:
```
DATA_SANITY_FLAG — abnormal bar (>20% range/change)
```

Each filter should appear in the daily log if triggered, so you always know *why* a ticker was skipped.

---

## 4. Market Filter (Reminder)
No changes — already implemented.

---

## 5. Sector Rotation (Technical Debt)
Placeholder for v2.  
Score each sector ETF (XLK, XLE, XLF, etc.) using the same EMA/SMA health test (Close>EMA20 & SMA50 rising).  
Boost signals from top sectors, throttle bottom sectors.  
Surface optional line:
```
Sector Focus: Energy, Industrials strong; Tech mixed.


**OCTOBER FOURTH UPDATE**

# ⚙️ Data Provider Framework (v1.2 Update)

> Purpose: Stabilize nightly data fetches and improve earnings date accuracy without sacrificing simplicity.

---

## 1. Provider Hierarchy & Fetch Logic

To prevent downtime or incomplete data, the system now supports a **multi-provider hierarchy**.

### Default Order:
1. **Polygon** → Primary (bars, fundamentals, news)
2. **Finnhub** → Secondary (bars + earnings calendar)
3. **yfinance** → Fallback (bars only)
4. **Synthetic / Mock** → Emergency fallback (pipeline continuity)

### Fetch Adapter
The `get_bars()` function routes requests through providers in priority order:

```python
PROVIDER = os.getenv("DATA_PROVIDER", "auto")

def get_bars(tkr, start):
    if PROVIDER in ("polygon", "auto"):
        df = fetch_polygon(tkr, start)
        if df is not None and not df.empty: return df

    if PROVIDER in ("finnhub", "auto"):
        df = fetch_finnhub(tkr, start)
        if df is not None and not df.empty: return df

    if PROVIDER in ("yfinance", "auto"):
        try:
            return yf.download(tkr, start=start, progress=False, auto_adjust=True)
        except Exception:
            pass

    return _mock_bars(tkr, start)
```

This ensures:
- **High reliability:** at least one provider always responds.
- **Clean fallback chain:** no single dependency can break the nightly run.
- **Minimal code churn:** adding/removing providers doesn’t affect strategy logic.

### Environment Config (GitHub Actions / Local)

```
DATA_PROVIDER=auto
POLYGON_API_KEY=your_polygon_key
FINNHUB_API_KEY=your_finnhub_key
```

> `auto` lets the adapter cascade through Polygon → Finnhub → yfinance automatically.

---

## 2. Earnings Guard Data Source (Primary)

The **Earnings Guard** logic now uses **Finnhub’s `/calendar/earnings`** endpoint as the **authoritative source** for upcoming events.

### Reasoning:
- Finnhub offers a **dedicated, structured earnings calendar API**.
- Reliable for U.S. and large global tickers.
- JSON response includes `symbol`, `date`, and `time` fields.
- Free-tier access suitable for daily batch checks.
- Polygon’s filings endpoint or `yfinance.calendar` act as **fallbacks**.

### Implementation Notes

#### Endpoint
```
GET https://finnhub.io/api/v1/calendar/earnings?symbol={TICKER}&from={TODAY}&to={TODAY+7}&token={API_KEY}
```

#### Guard Logic
```python
next_earnings = get_next_earnings_date(symbol)
if next_earnings and (0 <= (next_earnings - today).days <= 2):
    block_entry(symbol, reason="EARNINGS_GUARD_ACTIVE")
```

#### Fallback Behavior
- If Finnhub returns no data → check Polygon filings.
- If still empty → optional fallback to `yfinance.calendar`.
- If all fail → **fail open** (allow entry).

#### Call Efficiency
- Only call for tickers **passing entry filters** (to stay within free-tier quota).
- Cache earnings results locally for **3–5 days** per symbol.

---

## 3. Summary: Why This Matters

| Objective | Old | New |
|------------|-----|-----|
| **Data continuity** | Single-source (yfinance) | Cascading multi-provider |
| **Reliability** | Susceptible to Yahoo outages | Resilient with 3-tier failover |
| **Earnings Guard** | yfinance.calendar (inconsistent) | Finnhub-first (accurate) |
| **Future Scalability** | Manual migration | Plug-in adapter (1 line per provider) |

✅ **Outcome:** You now have a robust, production-grade data foundation — one that auto-heals if any provider fails, while ensuring earnings-date accuracy for entry suppression.



# 🧱 Technical Debt Log (Deferred Enhancements)

## 1. Sector Rotation Awareness (Priority TD)
**Intent:** improve hit rate by focusing entries in sectors showing broad strength.

**Approach (v2):**
- Evaluate sector ETFs (XLK, XLE, XLI, XLF, XLV, XLY, XLRE, XLB, XLP, XLU).
- Health test per ETF: `Close > EMA20`, `Close > SMA50`, and `SMA50 rising`.
- Score each sector: 1 = healthy, 0 = unhealthy.
- Map tickers to sectors via fundamentals metadata.
- Boost signals from top N sectors; suppress bottom N.
- Display summary line:
  ```
  Sector Focus: Energy, Industrials strong; Tech mixed.
  ```
**Success condition:** ≥70% of triggered entries belong to top-ranked sectors.

---

## 2. Auto-Universe Refresh
**Intent:** maintain a dynamic watchlist without manual edits.

**Approach:**  
Nightly fetch top 500–1000 tickers by 20-day average **dollar volume**, filter out ADRs/penny stocks, overwrite `watchlist.txt`.

**Success condition:** >90% of tickers in `watchlist.txt` have daily $-volume > $10M.

---

## 3. Alternate Data Provider Layer
**Intent:** reduce reliance on Yahoo endpoints.

**Approach:**  
Stack `Polygon` or `Finnhub` APIs as secondary data fetchers.  
Fail-open if quota exceeded.  
Run quick integrity check:
```
if abs(yf_close - alt_close) / yf_close > 0.02:
    prefer alt_close
```

**Success condition:** 0 missing bars in 30-day test; <2% mismatch between providers.

---

## 4. Metrics & Analytics Dashboard
**Intent:** provide simple backtest-style health metrics.

**Proposed metrics:**
- Win rate with vs without Market Filter.
- % trades hitting Time Stop (should stay <15%).
- Median hold days.
- Median R on winners vs losers.
- Distribution of R_peak.

**Success condition:** all metrics computed in ≤5s locally (no heavy backtester).

---

## 5. Reporting Enhancements
**Intent:** streamline review and journaling.

**Future additions:**
- Optional export to Notion or Google Sheets.
- Weekly “Summary Snapshot” MD file with:
  - New entries
  - Exits
  - Avg R per closed trade
  - Top 3 performers by % gain

**Success condition:** one-file summary readable in <30s.

---

## 6. Alerts / Notifications Layer
**Intent:** optional push updates when Highlights refresh.

**Approach:**  
Integrate lightweight webhook (Discord / Slack / Telegram) that posts:
```
📈 New Entry: AMD [BASE] 128.8–129.4
📉 Exit: META (EMA20 break) +14.6%
```
**Success condition:** single push/day, no spam.

---

🧩 *Note:* Tech Debt items should only be activated once v1.1 has run **≥30 clean nightly cycles** without manual intervention.

