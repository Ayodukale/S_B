# SwingBot

SwingBot is an end-of-day swing trading agent that publishes actionable signals and highlights without requiring a dedicated server. A GitHub Action runs every weekday around 5:05 pm ET, captures market data, generates machine-readable and human-readable outputs, pushes them back to this repository, and optionally notifies Discord. A Custom GPT can read the same published files for conversational access.

## Key Features

- **Dual EMA strategy tracking** – `nine_ema_dual_strategy_bot_v2.py` screens the watchlist, tracks open positions, and enforces risk guardrails (market filter, gap/data sanity checks, low dollar-volume filter, upcoming earnings guard).
- **Automated nightly pipeline** – `.github/workflows/eod.yml` installs dependencies, runs the screener, commits updated `data/` artifacts, and posts a Discord embed summarizing the day.
- **Static publishing** – GitHub Pages hosts `data/signals.json` and `data/highlights.md`, so downstream consumers (Discord, Custom GPT) always see the latest snapshot.
- **Discord notifications** – `scripts/notify_discord.py` crafts an embed from highlights and recent entries and posts to one or two webhooks. It includes a footer link to the GPT for deep dives.
- **Custom GPT integration** – The GPT references the Pages URLs to answer questions, surface entries/exits, and provide breakdowns on demand.

## Repository Layout

```
.
├── codex.md                         # Playbook / internal documentation
├── data/                            # Nightly artifacts committed by the workflow
│   ├── highlights.md
│   ├── highlights.txt
│   ├── ledger.csv
│   ├── out_signals.csv
│   ├── signals.json
│   └── earnings_cache.json
├── index.html                       # Minimal landing page for GitHub Pages
├── requirements.txt                 # Python dependencies
├── run.py                           # Orchestration: run screener, emit JSON/MD
├── nine_ema_dual_strategy_bot_v2.py # Strategy implementation
├── scripts/
│   └── notify_discord.py            # Discord embed payload generator
└── watchlist.txt                    # Universe of tickers (editable)
```

## Getting Started

1. **Install dependencies locally**
   ```bash
   pip install -r requirements.txt
   python run.py
   ```
2. **Tailor the watchlist** – edit `watchlist.txt` (one symbol per line).
3. **Confirm outputs** – generated files appear under `data/`. Review `highlights.txt` and `signals.json` before pushing.
4. **Push to GitHub** – `git add`, `git commit`, and `git push` to trigger the workflow and update Pages.

## Automation Pipeline

- Scheduled at `05 21 * * 1-5` (5:05 pm ET weekdays).
- Uses Python 3.11 on `ubuntu-latest`.
- Steps:
  1. Check out code.
  2. Install requirements.
  3. Run `run.py` with API keys (see below).
  4. Commit new `data/` artifacts (if any).
  5. Rebase/push against `main`.
  6. Run `scripts/notify_discord.py` to alert Discord.

## Required Secrets

Set the following secrets under **GitHub → Settings → Secrets and variables → Actions**:

- `POLYGON_API_KEY` – for Polygon fallback futures.
- `FINNHUB_API_KEY` – for Finnhub primary data + earnings calendar.
- `DISCORD_WEBHOOK_SWINGBOT` – primary Discord webhook (posts as **SwingBot**).
- `DISCORD_WEBHOOK_SWINGBOT_2` *(optional)* – secondary webhook (posts as **SwingBot_2**).

The workflow automatically reuses secrets; no manual intervention is required once they are in place.

## Discord Embed Structure

Each run posts a card containing:

- Title: “SwingBot EOD Update”.
- Description: the contents of `data/highlights.txt` (truncated to Discord’s length limit).
- Fields: top entries (prioritized by actionable signals; fallback to first three tickers).
- Footer: Link to the SwingBot Custom GPT for deeper conversation.

## Custom GPT Integration

Configure your GPT’s action with:

- `https://<username>.github.io/S_B/data/signals.json`
- `https://<username>.github.io/S_B/data/highlights.md`

The GPT should always fetch `signals.json` first for structured data and `highlights.md` when a human summary is requested. The sample system prompt lives in `codex.md`.

## Local Development Tips

- `data/ledger.csv` persists positions; deleting this file resets state before a new run.
- `data/earnings_cache.json` retains earnings dates for three days to limit API calls; remove it if you want a fresh fetch.
- Synthetic data fallbacks exist for price history, but they tag the source as `synthetic` (with the market filter automatically skipping them).

## Extending the Bot

The roadmap (documented in `codex.md`) includes sector rotation scoring, auto-universe refresh, analytics dashboards, and optional notifications. Contributions welcome—fork, branch, and open a PR.

