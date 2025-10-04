#!/usr/bin/env python3
"""EOD publisher: run the strategy, convert CSV outputs to JSON/Markdown."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
STRATEGY = ROOT / "nine_ema_dual_strategy_bot_v2.py"
DATA_DIR.mkdir(parents=True, exist_ok=True)



KEY_FILE = ROOT.parent / "API_KEYS"


def load_local_api_keys() -> None:
    if not KEY_FILE.exists():
        return
    try:
        lines = [line.strip() for line in KEY_FILE.read_text().splitlines() if line.strip()]
    except Exception:
        return
    def maybe_set(prefix: str, key: str) -> None:
        env_name = key
        if os.environ.get(env_name):
            return
        match = None
        for line in lines:
            lower = line.lower()
            if lower.startswith(prefix):
                parts = line.split()
                if parts:
                    match = parts[-1]
                break
        if match:
            os.environ[env_name] = match

    maybe_set("polygon api key", "POLYGON_API_KEY")
    maybe_set("finnhub api key", "FINNHUB_API_KEY")
def invoke_strategy() -> None:
    load_local_api_keys()
    cmd = [
        sys.executable,
        str(STRATEGY),
        "--ledger",
        str(DATA_DIR / "ledger.csv"),
        "--emit",
        str(DATA_DIR / "out_signals.csv"),
        "--highlights",
        str(DATA_DIR / "highlights.txt"),
        "--tickers-file",
        str(ROOT / "watchlist.txt"),
    ]
    print("Running screener:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def safe_float(val):
    if pd.isna(val):
        return None
    try:
        return float(val)
    except Exception:
        return None


def safe_int(val):
    if pd.isna(val):
        return None
    try:
        return int(val)
    except Exception:
        return None




def safe_bool(val):
    if pd.isna(val):
        return None
    if isinstance(val, bool):
        return bool(val)
    if isinstance(val, (int, float)):
        try:
            return bool(int(val))
        except Exception:
            return None
    if isinstance(val, str):
        lower = val.strip().lower()
        if lower in {"true", "1", "yes"}:
            return True
        if lower in {"false", "0", "no"}:
            return False
    return None
def build_payload(signals_csv: Path, ledger_csv: Path) -> dict:
    signals = []
    if signals_csv.exists():
        df = pd.read_csv(signals_csv)
        has_market_ok = "market_ok" in df.columns
        has_market_reason = "market_reason" in df.columns
        for _, row in df.iterrows():
            record = {
                "date": str(row.get("date", "")),
                "ticker": row.get("ticker", ""),
                "strategy": row.get("strategy", ""),
                "setup": bool(row.get("setup", False)),
                "action": row.get("action", ""),
                "buy_zone_low": safe_float(row.get("buy_zone_low")),
                "buy_zone_high": safe_float(row.get("buy_zone_high")),
                "confirm_today": bool(row.get("confirm_today", False)),
                "close": safe_float(row.get("close")),
                "ema9": safe_float(row.get("ema9")),
                "ema20": safe_float(row.get("ema20")),
                "atr14": safe_float(row.get("atr14")),
                "vol": safe_int(row.get("vol")),
                "vol20": safe_int(row.get("vol20")),
                "notes": row.get("notes", ""),
            }
            record["market_ok"] = safe_bool(row.get("market_ok")) if has_market_ok else None
            if has_market_reason:
                reason = row.get("market_reason", "")
                record["market_reason"] = "" if pd.isna(reason) else str(reason)
            else:
                record["market_reason"] = ""
            signals.append(record)

    positions = []
    if ledger_csv.exists():
        ldf = pd.read_csv(ledger_csv)
        for _, row in ldf.iterrows():
            positions.append(
                {
                    "ticker": row.get("ticker", ""),
                    "strategy": row.get("strategy", ""),
                    "status": row.get("status", ""),
                    "entry_date": str(row.get("entry_date"))[:10] if not pd.isna(row.get("entry_date")) else None,
                    "entry_price": safe_float(row.get("entry_price")),
                    "exit_date": str(row.get("exit_date"))[:10] if not pd.isna(row.get("exit_date")) else None,
                    "exit_price": safe_float(row.get("exit_price")),
                    "pct_since_entry": safe_float(row.get("pct_since_entry")),
                    "r_peak": safe_float(row.get("r_peak")),
                    "days_held": safe_int(row.get("days_held")),
                    "highest_close": safe_float(row.get("highest_close")),
                    "notes": row.get("notes", ""),
                }
            )

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "universe_source": "watchlist.txt",
        "signals": signals,
        "positions": positions,
    }


def write_outputs(payload: dict, highlights_txt: Path) -> None:
    json_path = DATA_DIR / "signals.json"
    json_path.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {json_path}")

    md_path = DATA_DIR / "highlights.md"
    if highlights_txt.exists():
        content = highlights_txt.read_text().strip()
    else:
        content = "No highlights available."
    md = "## Highlights (Today)\n\n```\n" + content + "\n```\n"
    md_path.write_text(md)
    print(f"Wrote {md_path}")


def main() -> None:
    try:
        invoke_strategy()
    except subprocess.CalledProcessError as exc:
        print(f"Screener failed with exit code {exc.returncode}", file=sys.stderr)
        raise

    payload = build_payload(DATA_DIR / "out_signals.csv", DATA_DIR / "ledger.csv")
    write_outputs(payload, DATA_DIR / "highlights.txt")


if __name__ == "__main__":
    main()
