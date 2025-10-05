#!/usr/bin/env python3
"""Simple dual-EMA swing bot used by run.py.

The original strategy is fairly involved; this reimplementation keeps the same
CLI surface area but uses a lightweight ruleset:

* Identify names respecting the 9/20 EMA pair.
* Trigger entries when price trades inside the buy zone (between the EMAs).
* Exit when price closes below the 20 EMA.
* Persist a rolling ledger so repeated runs keep state.

Outputs:
  - signals CSV (per-run snapshot of actionable tickers)
  - ledger CSV (open/closed positions)
  - highlights.txt (readable summary for humans)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np
import requests
import time


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / 'data'
EARNINGS_CACHE_PATH = DATA_DIR / 'earnings_cache.json'
CACHE_TTL_DAYS = 3



def load_earnings_cache() -> Dict[str, Dict[str, str]]:
    if not EARNINGS_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(EARNINGS_CACHE_PATH.read_text())
    except Exception:
        return {}


def save_earnings_cache(cache: Dict[str, Dict[str, str]]) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        EARNINGS_CACHE_PATH.write_text(json.dumps(cache, indent=2))
    except Exception:
        pass


def parse_date(value: Optional[str]) -> Optional[datetime.date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except Exception:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except Exception:
            return None


def fetch_next_earnings_finnhub(ticker: str) -> Optional[datetime.date]:
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return None
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=7)
    url = "https://finnhub.io/api/v1/calendar/earnings"
    params = {
        "symbol": ticker.upper(),
        "from": today.isoformat(),
        "to": horizon.isoformat(),
        "token": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return None
    items = payload.get("earningsCalendar") or []
    candidates = [parse_date(item.get("date")) for item in items]
    candidates = [d for d in candidates if d and d >= today]
    if not candidates:
        return None
    return min(candidates)


def fetch_next_earnings_polygon(ticker: str) -> Optional[datetime.date]:
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        return None
    today = datetime.now(timezone.utc).date()
    url = "https://api.polygon.io/vX/reference/events/earnings"
    params = {
        "ticker": ticker.upper(),
        "order": "asc",
        "limit": 1,
        "sort": "startDate",
        "apiKey": api_key,
        "start": today.isoformat(),
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return None
    results = payload.get("results") or []
    if not results:
        return None
    date_str = results[0].get("startDate") or results[0].get("fiscalPeriod")
    return parse_date(date_str)


def fetch_next_earnings_yfinance(ticker: str) -> Optional[datetime.date]:
    try:
        import yfinance as yf  # type: ignore
    except ImportError:
        return None
    try:
        cal = yf.Ticker(ticker).calendar
    except Exception:
        return None
    if cal is None:
        return None
    value = None
    if hasattr(cal, "empty"):
        if cal.empty:
            return None
        if "Earnings Date" in cal.columns:
            value = cal.iloc[0].get("Earnings Date")
        elif len(cal.columns) > 0:
            value = cal.iloc[0][0]
    elif isinstance(cal, dict):
        value = cal.get("Earnings Date")
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return parse_date(value)
    return None


def get_next_earnings_date(ticker: str, cache: Dict[str, Dict[str, str]]) -> Optional[datetime.date]:
    today = datetime.now(timezone.utc).date()
    entry = cache.get(ticker.upper())
    if entry:
        fetched = parse_date(entry.get("fetched_at"))
        if fetched and (today - fetched).days <= CACHE_TTL_DAYS:
            cached_date = parse_date(entry.get("next_earnings"))
            if cached_date:
                return cached_date
            if entry.get("next_earnings") is None:
                return None
    # fetch fresh
    next_date = (
        fetch_next_earnings_finnhub(ticker)
        or fetch_next_earnings_polygon(ticker)
        or fetch_next_earnings_yfinance(ticker)
    )
    cache[ticker.upper()] = {
        "next_earnings": next_date.isoformat() if next_date else None,
        "fetched_at": today.isoformat(),
    }
    return next_date


def _mock_bars(ticker: str, periods: int = 180) -> pd.DataFrame:
    rng = pd.date_range(end=datetime.now(timezone.utc).date(), periods=periods, freq="B")
    base = np.linspace(0, 1, periods)
    prices = 100 + 5 * np.sin(2 * np.pi * base) + np.linspace(0, 15, periods)
    df = pd.DataFrame(index=rng)
    noise = np.random.normal(0, 0.01, periods)
    df["close"] = prices * (1 + noise) + (hash(ticker) % 500) * 0.05
    df["open"] = df["close"].shift(1).fillna(df["close"]) * (1 + np.random.normal(0, 0.002, periods))
    upper = np.abs(np.random.normal(0.005, 0.003, periods))
    lower = np.abs(np.random.normal(0.005, 0.003, periods))
    df["high"] = np.maximum(df["open"], df["close"]) * (1 + upper)
    df["low"] = np.minimum(df["open"], df["close"]) * (1 - lower)
    df["volume"] = (1_000_000 + np.random.randint(0, 750_000, periods)).astype(int)
    df.attrs["source"] = "synthetic"
    return df




def fetch_polygon_daily_bars(ticker: str, start: datetime) -> pd.DataFrame:
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        return pd.DataFrame()
    start_str = start.date().strftime("%Y-%m-%d")
    end_str = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker.upper()}/range/1/day/{start_str}/{end_str}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 5000,
        "apiKey": api_key,
    }
    for attempt in range(2):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            payload = None
        if not payload:
            return pd.DataFrame()
        if payload.get("status") == "ERROR":
            error_msg = (payload.get("error") or "").lower()
            if "exceeded" in error_msg and attempt == 0:
                time.sleep(2)
                continue
            return pd.DataFrame()
        results = payload.get("results") or []
        if not results:
            if attempt == 0:
                time.sleep(1)
                continue
            return pd.DataFrame()
        rows = []
        for item in results:
            ts = item.get("t")
            if ts is None:
                continue
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            rows.append(
                {
                    "date": dt,
                    "open": item.get("o"),
                    "high": item.get("h"),
                    "low": item.get("l"),
                    "close": item.get("c"),
                    "volume": item.get("v"),
                }
            )
        if rows:
            df = pd.DataFrame(rows).set_index("date").sort_index()
            df.attrs["source"] = "polygon"
            return df
    return pd.DataFrame()

def fetch_finnhub_daily_bars(ticker: str, start: datetime) -> pd.DataFrame:
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return pd.DataFrame()
    url = "https://finnhub.io/api/v1/stock/candle"
    for symbol in (ticker.upper(), f"US:{ticker.upper()}"):
        params = {
            "symbol": symbol,
            "resolution": "D",
            "from": int(start.replace(tzinfo=timezone.utc).timestamp()),
            "to": int(datetime.now(timezone.utc).timestamp()),
            "token": api_key,
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            data = None
        if not data or data.get("s") != "ok":
            continue
        times = data.get("t") or []
        if not times:
            continue
        df = pd.DataFrame(
            {
                "date": [datetime.fromtimestamp(ts, tz=timezone.utc) for ts in times],
                "open": data.get("o", []),
                "high": data.get("h", []),
                "low": data.get("l", []),
                "close": data.get("c", []),
                "volume": data.get("v", []),
            }
        )
        df = df.set_index("date").sort_index()
        df.attrs["source"] = "finnhub"
        return df
    return pd.DataFrame()

def get_bars(ticker: str, start: datetime) -> pd.DataFrame:
    """Fetch daily bars favoring Polygon -> Finnhub -> yfinance -> synthetic."""
    for fetcher in (fetch_polygon_daily_bars, fetch_finnhub_daily_bars):
        try:
            alt = fetcher(ticker, start)
        except Exception:
            alt = pd.DataFrame()
        if alt is not None and not alt.empty:
            return alt

    try:
        import yfinance as yf  # type: ignore
    except ImportError as exc:  # pragma: no cover - surfaced to caller
        raise RuntimeError("yfinance is required; run `pip install -r requirements.txt`.") from exc

    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
            threads=False,
        )
        if df.empty:
            df = yf.Ticker(ticker).history(period="2y", auto_adjust=True, actions=False)
        if not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [str(col[0]).lower() for col in df.columns]
            else:
                df = df.rename(columns=str.lower)
            keep = [col for col in ("open", "high", "low", "close", "volume") if col in df.columns]
            df = df[keep]
            df.attrs["source"] = "yfinance"
            return df
    except Exception:
        pass

    fallback = _mock_bars(ticker)
    fallback.attrs["source"] = "synthetic"
    return fallback


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def check_market_filter(start: datetime) -> Tuple[bool, str]:
    """Return (market_ok, reason) using SPY & QQQ trend health."""
    spy = get_bars("SPY", start)
    qqq = get_bars("QQQ", start)

    if spy.empty or qqq.empty:
        return True, "market_check_skipped: insufficient_data"

    spy_source = spy.attrs.get("source")
    qqq_source = qqq.attrs.get("source")
    if spy_source == "synthetic" or qqq_source == "synthetic":
        return True, "market_check_skipped: synthetic_data"

    spy = spy.sort_index()
    qqq = qqq.sort_index()

    if len(spy) < 60 or len(qqq) < 60:
        return True, "market_check_skipped: insufficient_data"

    spy["ema20"] = _ema(spy["close"], 20)
    spy["sma50"] = _sma(spy["close"], 50)
    qqq["ema20"] = _ema(qqq["close"], 20)
    qqq["sma50"] = _sma(qqq["close"], 50)

    spy_latest = spy.iloc[-1]
    qqq_latest = qqq.iloc[-1]
    spy_prev = spy.iloc[-6]
    qqq_prev = qqq.iloc[-6]

    def healthy(latest, prev) -> bool:
        return (
            latest["close"] > latest["ema20"]
            and latest["close"] > latest["sma50"]
            and latest["sma50"] > prev["sma50"]
        )

    spy_ok = healthy(spy_latest, spy_prev)
    qqq_ok = healthy(qqq_latest, qqq_prev)

    if spy_ok and qqq_ok:
        return True, "market_ok: SPY & QQQ in uptrend"

    reasons: List[str] = []
    if not spy_ok:
        reasons.append("SPY below EMA20/SMA50 or SMA50 not rising")
    if not qqq_ok:
        reasons.append("QQQ below EMA20/SMA50 or SMA50 not rising")
    return False, " ; ".join(reasons)


@dataclass
class Position:
    ticker: str
    strategy: str = "BASE"
    status: str = "OPEN"
    entry_date: Optional[str] = None
    entry_price: Optional[float] = None
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    pct_since_entry: Optional[float] = None
    r_peak: Optional[float] = None
    days_held: Optional[int] = None
    highest_close: Optional[float] = None
    notes: str = ""

    # Internal only fields, not persisted directly
    _entry_idx: Optional[int] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "ticker": self.ticker,
            "strategy": self.strategy,
            "status": self.status,
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "exit_date": self.exit_date,
            "exit_price": self.exit_price,
            "pct_since_entry": self.pct_since_entry,
            "r_peak": self.r_peak,
            "days_held": self.days_held,
            "highest_close": self.highest_close,
            "notes": self.notes,
        }


def load_existing_ledger(path: str) -> Dict[str, Position]:
    if not os.path.exists(path):
        return {}
    df = pd.read_csv(path)
    ledger: Dict[str, Position] = {}
    for _, row in df.iterrows():
        pos = Position(
            ticker=row.get("ticker", ""),
            strategy=row.get("strategy", "BASE"),
            status=row.get("status", "OPEN"),
            entry_date=row.get("entry_date") if not pd.isna(row.get("entry_date")) else None,
            entry_price=float(row.get("entry_price")) if not pd.isna(row.get("entry_price")) else None,
            exit_date=row.get("exit_date") if not pd.isna(row.get("exit_date")) else None,
            exit_price=float(row.get("exit_price")) if not pd.isna(row.get("exit_price")) else None,
            pct_since_entry=float(row.get("pct_since_entry")) if not pd.isna(row.get("pct_since_entry")) else None,
            r_peak=float(row.get("r_peak")) if not pd.isna(row.get("r_peak")) else None,
            days_held=int(row.get("days_held")) if not pd.isna(row.get("days_held")) else None,
            highest_close=float(row.get("highest_close")) if not pd.isna(row.get("highest_close")) else None,
            notes=row.get("notes", ""),
        )
        ledger[pos.ticker] = pos
    return ledger


def write_csv(path: str, rows: List[Dict[str, object]], fieldnames: List[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def format_float(value: Optional[float], digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return f"{value:.{digits}f}"


def run_strategy(args: argparse.Namespace) -> None:
    start = datetime.now(timezone.utc) - timedelta(days=args.lookback_days)
    tickers = [t.strip().upper() for t in open(args.tickers_file).read().splitlines() if t.strip()]

    existing_ledger = load_existing_ledger(args.ledger)
    updated_positions: Dict[str, Position] = {}
    closed_today: List[Position] = []
    entries_today: List[Position] = []
    signal_rows: List[Dict[str, object]] = []
    suppressed_today: List[Dict[str, object]] = []
    filter_events: List[Dict[str, str]] = []

    earnings_cache = load_earnings_cache()
    market_ok, market_reason = check_market_filter(start)

    today_date = datetime.now(timezone.utc).date()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for ticker in tickers:
        df = get_bars(ticker, start)
        if df.empty or len(df) < 30:
            continue

        df = df.sort_index()
        if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
            df.index = df.index.tz_convert(None)
        if len(df) < 25:
            filter_events.append({"ticker": ticker, "filter": "INSUFFICIENT_HISTORY", "detail": "<25 bars after fetch"})
            continue

        df["dollar_volume"] = df["close"] * df["volume"]
        avg_dollar_volume = float(df["dollar_volume"].tail(20).mean())
        if avg_dollar_volume < 5_000_000:
            filter_events.append({"ticker": ticker, "filter": "LOW_DOLLAR_VOLUME", "detail": f"20d avg ${avg_dollar_volume/1_000_000:.1f}M"})
            continue

        prev_close = float(df["close"].iloc[-2]) if len(df) >= 2 else float("nan")
        open_today = float(df["open"].iloc[-1])
        if prev_close and not math.isnan(prev_close) and prev_close != 0:
            gap_pct = abs(open_today - prev_close) / prev_close
        else:
            gap_pct = 0.0
        if gap_pct > 0.08:
            filter_events.append({"ticker": ticker, "filter": "GAP_FILTER_TRIGGERED", "detail": f"gap {gap_pct*100:.1f}%"})
            continue

        latest = df.iloc[-1]
        if prev_close and not math.isnan(prev_close) and prev_close != 0:
            close_change = abs(latest["close"] - prev_close) / prev_close
        else:
            close_change = 0.0
        range_pct = (latest["high"] - latest["low"]) / latest["close"] if latest["close"] else 0.0
        if range_pct > 0.2 or close_change > 0.2:
            filter_events.append({"ticker": ticker, "filter": "DATA_SANITY_FLAG", "detail": f"range {range_pct*100:.1f}% change {close_change*100:.1f}%"})
            continue

        df["ema9"] = df["close"].ewm(span=9, adjust=False).mean()
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
        df["atr14"] = compute_atr(df, 14)
        df["vol20"] = df["volume"].rolling(20).mean()

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        latest_date = df.index[-1].strftime("%Y-%m-%d")

        buy_zone_low = float(round(min(latest["ema9"], latest["ema20"]), 2))
        buy_zone_high = float(round(max(latest["ema9"], latest["ema20"]), 2))
        in_buy_zone = buy_zone_low <= latest["close"] <= buy_zone_high
        setup = bool(latest["ema9"] > latest["ema20"])
        action = "WATCH"
        notes = ""
        entry_triggered = False
        suppressed_entry = False
        next_earnings_date = None

        allow_entries = market_ok or market_reason.startswith("market_check_skipped")

        if setup and allow_entries:
            next_earnings_date = get_next_earnings_date(ticker, earnings_cache)
            if next_earnings_date:
                days_until = (next_earnings_date - today_date).days
                if 0 <= days_until <= 2:
                    action = "EARNINGS_GUARD_ACTIVE"
                    notes = f"Earnings {next_earnings_date.isoformat()}"
                    suppressed_entry = True
        if setup and in_buy_zone and not suppressed_entry:
            if allow_entries:
                action = "BUY_ZONE_TRIGGERED"
                notes = "Price inside EMA buy zone"
                entry_triggered = True
            else:
                action = "MARKET_FILTER_ACTIVE"
                notes = f"Market filter active: {market_reason}"
                suppressed_entry = True
        elif setup and latest["close"] > buy_zone_high:
            action = "WAIT_FOR_PULLBACK"
            notes = "Price extended above buy zone"
        elif latest["close"] < latest["ema20"]:
            action = "EXIT_CANDIDATE"
            notes = "Close below EMA20"

        if suppressed_entry:
            suppressed_today.append(
                {
                    "ticker": ticker,
                    "strategy": "BASE",
                    "buy_zone_low": buy_zone_low,
                    "buy_zone_high": buy_zone_high,
                    "close": float(round(latest["close"], 2)),
                    "reason": notes or action,
                }
            )

        confirm_today = bool(latest["close"] > prev["close"])

        if setup:
            market_flag = None if market_reason.startswith("market_check_skipped") else bool(market_ok)
            signal_rows.append(
                {
                    "date": latest_date,
                    "ticker": ticker,
                    "strategy": "BASE",
                    "setup": True,
                    "action": action,
                    "buy_zone_low": buy_zone_low,
                    "buy_zone_high": buy_zone_high,
                    "confirm_today": confirm_today,
                    "close": float(round(latest["close"], 2)),
                    "ema9": float(round(latest["ema9"], 2)),
                    "ema20": float(round(latest["ema20"], 2)),
                    "atr14": float(round(latest["atr14"], 2)) if not pd.isna(latest["atr14"]) else None,
                    "vol": int(latest["volume"]) if not pd.isna(latest["volume"]) else None,
                    "vol20": int(round(latest["vol20"])) if not pd.isna(latest["vol20"]) else None,
                    "notes": notes,
                    "market_ok": market_flag,
                    "market_reason": market_reason,
                    "next_earnings": next_earnings_date.isoformat() if next_earnings_date else None,
                }
            )

        existing = existing_ledger.get(ticker)
        if existing and existing.status == "OPEN":
            entry_price = existing.entry_price or latest["close"]
            entry_date = existing.entry_date or latest_date
            entry_ts = pd.to_datetime(entry_date)
            if hasattr(entry_ts, 'tz_convert') and entry_ts.tzinfo is not None:
                entry_ts = entry_ts.tz_convert(None)
            if entry_ts in df.index:
                entry_idx = int(df.index.get_loc(entry_ts))
            else:
                entry_idx = int(df.index.searchsorted(entry_ts))
                if entry_idx >= len(df):
                    entry_idx = len(df) - 1
            entry_idx = max(entry_idx, 0)
            window = df.iloc[entry_idx:]
            highest_close = float(round(window["close"].max(), 2))
            pct_since_entry = float(round((latest["close"] / entry_price - 1) * 100, 2))
            peak_r = None
            if not window["atr14"].isna().all():
                atr_at_entry = window["atr14"].iloc[0]
                if atr_at_entry and not math.isnan(atr_at_entry) and atr_at_entry != 0:
                    peak_r = float(round((highest_close - entry_price) / atr_at_entry, 2))

            position = Position(
                ticker=ticker,
                strategy=existing.strategy,
                status="OPEN",
                entry_date=entry_date,
                entry_price=entry_price,
                pct_since_entry=pct_since_entry,
                r_peak=peak_r,
                days_held=int((pd.to_datetime(latest_date) - pd.to_datetime(entry_date)).days),
                highest_close=highest_close,
                notes=existing.notes,
            )

            if latest["close"] < latest["ema20"]:
                position.status = "CLOSED"
                position.exit_date = latest_date
                position.exit_price = float(round(latest["close"], 2))
                position.notes = "EMA20_break_exit"
                closed_today.append(position)
            else:
                updated_positions[ticker] = position
            continue

        if action == "BUY_ZONE_TRIGGERED" and ticker not in updated_positions:
            position = Position(
                ticker=ticker,
                strategy="BASE",
                status="OPEN",
                entry_date=latest_date,
                entry_price=float(round(latest["close"], 2)),
                pct_since_entry=0.0,
                r_peak=0.0,
                days_held=0,
                highest_close=float(round(latest["close"], 2)),
                notes="Entered on buy zone trigger",
            )
            updated_positions[ticker] = position
            entries_today.append(position)

    # Merge with any existing closed positions we still need to carry forward.
    for ticker, position in existing_ledger.items():
        if position.status == "CLOSED":
            updated_positions.setdefault(ticker, position)

    ledger_rows = [pos.to_dict() for pos in updated_positions.values()]
    ledger_rows.sort(key=lambda r: (r["status"] != "OPEN", r["ticker"]))

    write_csv(
        args.emit,
        signal_rows,
        [
            "date",
            "ticker",
            "strategy",
            "setup",
            "action",
            "buy_zone_low",
            "buy_zone_high",
            "confirm_today",
            "close",
            "ema9",
            "ema20",
            "atr14",
            "vol",
            "vol20",
            "notes",
            "market_ok",
            "market_reason",
            "next_earnings",
        ],
    )

    write_csv(
        args.ledger,
        ledger_rows,
        [
            "ticker",
            "strategy",
            "status",
            "entry_date",
            "entry_price",
            "exit_date",
            "exit_price",
            "pct_since_entry",
            "r_peak",
            "days_held",
            "highest_close",
            "notes",
        ],
    )

    highlights_lines: List[str] = ["=== HIGHLIGHTS (Today) ==="]
    if market_reason.startswith("market_check_skipped"):
        highlights_lines.append(f"Market Check: ℹ️ {market_reason}")
    elif market_ok:
        highlights_lines.append("Market Check: ✅ SPY & QQQ uptrend — new entries allowed.")
    else:
        highlights_lines.append(f"Market Check: ⚠️ {market_reason} — pause new entries.")
    highlights_lines.append("")

    if entries_today:
        highlights_lines.append("Entries:")
        for pos in entries_today:
            highlights_lines.append(
                f"{pos.ticker} [{pos.strategy}] → ENTERED @ {format_float(pos.entry_price)} | Buy Zone"
            )
    if suppressed_today:
        highlights_lines.append("Entries (suppressed by guards):")
        for info in suppressed_today:
            highlights_lines.append(
                f"{info['ticker']} [{info['strategy']}] → {info['reason']} | Buy Zone [{format_float(info['buy_zone_low'])}, {format_float(info['buy_zone_high'])}]"
            )
    if filter_events:
        highlights_lines.append("Screening filters triggered:")
        for event in filter_events:
            highlights_lines.append(
                f"{event['ticker']} — {event['filter']} ({event['detail']})"
            )
    if closed_today:
        highlights_lines.append("Exits:")
        for pos in closed_today:
            highlights_lines.append(
                f"{pos.ticker} [{pos.strategy}] → EXIT {pos.notes} @ {format_float(pos.exit_price)}"
            )

    open_positions = [pos for pos in updated_positions.values() if pos.status == "OPEN"]
    open_positions.sort(key=lambda p: (p.pct_since_entry or 0), reverse=True)

    if open_positions:
        highlights_lines.append("")
        highlights_lines.append("Open Positions (top):")
        for pos in open_positions[:5]:
            highlights_lines.append(
                f"{pos.ticker} [{pos.strategy}] {format_float(pos.pct_since_entry)}% | R_peak {format_float(pos.r_peak)} | Held {pos.days_held}d"
            )

    if not entries_today and not suppressed_today and not closed_today and not open_positions:
        highlights_lines.append("No active positions. Review watchlist tomorrow.")


    with open(args.highlights, "w") as handle:
        handle.write("\n".join(highlights_lines))

    save_earnings_cache(earnings_cache)

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate swing signals and ledger CSVs.")
    parser.add_argument("--ledger", required=True, help="Path to ledger CSV output")
    parser.add_argument("--emit", required=True, help="Path to signals CSV output")
    parser.add_argument("--highlights", required=True, help="Path to highlights text output")
    parser.add_argument("--tickers-file", required=True, help="Universe tickers file (one per line)")
    parser.add_argument("--lookback-days", type=int, default=250, help="History window for indicators")
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_strategy(parse_args())
