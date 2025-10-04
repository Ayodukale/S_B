#!/usr/bin/env python3
"""Send SwingBot highlights to Discord webhooks.

Reads data/highlights.txt and data/out_signals.csv, builds a rich embed, and
POSTs to any webhooks provided via environment variables:
  - DISCORD_WEBHOOK_SWINGBOT
  - DISCORD_WEBHOOK_SWINGBOT_2

Gracefully skips if no webhook is configured.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
HIGHLIGHTS_PATH = DATA_DIR / "highlights.txt"
SIGNALS_PATH = DATA_DIR / "out_signals.csv"

ENTRY_ACTIONS = {"BUY_ZONE_TRIGGERED", "EARNINGS_GUARD_ACTIVE", "CONFIRM_BREAKOUT_ENTRY"}
WEBHOOK_VARS = ["DISCORD_WEBHOOK_SWINGBOT", "DISCORD_WEBHOOK_SWINGBOT_2"]


def load_highlights() -> str:
    if not HIGHLIGHTS_PATH.exists():
        return "No highlights generated."
    text = HIGHLIGHTS_PATH.read_text().strip()
    # Clip to Discord description limit (4096).
    return text[:4000]


def load_entry_fields() -> List[dict]:
    if not SIGNALS_PATH.exists():
        return []
    df = pd.read_csv(SIGNALS_PATH)
    if df.empty:
        return []
    entries = df[df["action"].isin(ENTRY_ACTIONS)]
    if entries.empty:
        entries = df.head(3)
    fields: List[dict] = []
    for _, row in entries.iterrows():
        name = f"{row['ticker']} — {row['strategy']}"
        parts = [f"Action: {row['action']}"]
        if not pd.isna(row.get("close")):
            parts.append(f"Close: {row['close']:.2f}")
        if not pd.isna(row.get("buy_zone_low")) and not pd.isna(row.get("buy_zone_high")):
            parts.append(f"Buy: {row['buy_zone_low']:.2f}-{row['buy_zone_high']:.2f}")
        if isinstance(row.get("next_earnings"), str) and row["next_earnings"]:
            parts.append(f"Next earnings: {row['next_earnings']}")
        value = " | ".join(parts)
        fields.append({"name": name, "value": value, "inline": False})
    return fields[:5]


def build_embed() -> dict:
    description = load_highlights()
    embed = {
        "title": "SwingBot EOD Update",
        "description": description,
        "color": 0x2563EB,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": load_entry_fields(),
    }
    return embed


def post_webhook(url: str, payload: dict) -> None:
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
    if response.status_code >= 400:
        raise RuntimeError(f"Discord webhook failed ({response.status_code}): {response.text[:200]}")


def main() -> None:
    webhooks = [os.getenv(var) for var in WEBHOOK_VARS]
    webhooks = [url for url in webhooks if url]
    if not webhooks:
        print("No Discord webhooks configured; skipping notification.")
        return

    embed = build_embed()
    payload = {
        "username": "SwingBot",
        "embeds": [embed],
    }

    for url in webhooks:
        try:
            post_webhook(url, payload)
            print(f"Sent highlights to Discord webhook: {url[-20:]}")
        except Exception as exc:
            print(f"Warning: failed to post to Discord webhook ({url[-20:]}): {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
