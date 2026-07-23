#!/usr/bin/env python3
"""
Live paper-trading daemon for flat_spike_strategy.py.

Runs during the premarket session (started by cron alongside pretop20.sh, killed
at market open) and writes simulated trades to <data-dir>/trade_history.json in
paper_trading_system.py's schema, so paper_trading_analyzer.py can report on them.
Places no real orders - this exists so the strategy can be watched live for a
while before deciding whether to wire up real IBKR execution.

Candidate tickers come from today's pretop20/screener_*.json snapshots, already
being written once a minute by premarket_top20_monitor.py (started by the same
cron entry). For each candidate this pulls its own daily + premarket minute bars
from Alpaca and runs the exact same flat_spike_strategy.py functions the
backtester uses (is_flat_before, find_spike_start, has_sufficient_liquidity,
replay_to_exit) - so live behavior can never quietly drift from backtested
behavior.

Usage:
    python flat_spike_live_trader.py
    python flat_spike_live_trader.py --data-dir momentum_data/flat_spike_live_trades
"""

import argparse
import glob
import json
import logging
import os
import sys
import time
from datetime import datetime, date, timedelta, time as dt_time
from pathlib import Path

import pytz

import flat_spike_strategy as strategy
from flat_spike_strategy import Bar, DailyBar

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ET_TZ = pytz.timezone('America/New_York')
LOCAL_TZ = pytz.timezone('Asia/Kuala_Lumpur')  # matches the machine that writes pretop20/

PID_FILE = '/tmp/flat_spike_live.pid'
SCAN_INTERVAL_SECONDS = 60
MIN_CANDIDATE_PCT = 5.0  # noise floor for the pretop20 shortlist, matches the backtester's default
DAILY_LOOKBACK_DAYS = strategy.FLAT_LOOKBACK_DAYS * 3 + 10  # calendar days, matches the backtester


def _call_with_retry(fn, *args, max_retries=3, base_delay=2.0, **kwargs):
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                logger.warning(f"Giving up after {max_retries} attempts: {e}")
                return None
            delay = base_delay * (2 ** attempt)
            logger.info(f"Request failed ({e}); retrying in {delay:.0f}s...")
            time.sleep(delay)
    return None


def load_today_candidates(pretop20_dir: Path, today_et: date, min_candidate_pct: float):
    """Scan today's pretop20/screener_*.json snapshots for tickers whose premarket
    change has crossed min_candidate_pct at some point today. Just a shortlist to
    avoid pulling Alpaca data for the whole market - glob is scoped to today's
    local-time filename prefix to stay cheap against a directory with months of
    history, then each snapshot's own timestamp is converted to ET (mirrors
    flat_spike_backtester.load_daily_candidates) to confirm it's really today."""
    # The snapshot filenames use naive local (Asia/Kuala_Lumpur) time, which is
    # the same calendar date as today_et (ET) throughout this cron's operating
    # window (16:00-21:30 MYT = 04:00-09:30 ET) - used only to scope the glob
    # cheaply; each file's own timestamp is still checked against today_et below.
    pattern = str(pretop20_dir / f"screener_{today_et:%Y%m%d}_*.json")
    candidates = {}
    for f in sorted(glob.glob(pattern)):
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        ts_str = payload.get('timestamp', '')
        try:
            ts = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            continue
        if ts.tzinfo is None:
            ts = LOCAL_TZ.localize(ts)
        if ts.astimezone(ET_TZ).date() != today_et:
            continue

        for record in payload.get('data', []):
            if not isinstance(record, dict):
                continue
            ticker = record.get('name')
            if not ticker or not ticker.isalpha():
                continue
            pct = record.get('alpaca_premarket_change')
            if pct is None:
                pct = record.get('premarket_change')
            if pct is None:
                continue
            if pct >= min_candidate_pct and pct > candidates.get(ticker, float('-inf')):
                candidates[ticker] = pct
    return candidates


def fetch_daily_bars(client, ticker: str, today_et: date):
    """Daily bars for the window ending the trading day before today."""
    start = ET_TZ.localize(datetime.combine(today_et - timedelta(days=DAILY_LOOKBACK_DAYS), dt_time(0, 0)))
    end = ET_TZ.localize(datetime.combine(today_et, dt_time(0, 0)))
    request = StockBarsRequest(symbol_or_symbols=ticker, timeframe=TimeFrame.Day,
                                start=start, end=end, feed=DataFeed.SIP)
    bars_data = _call_with_retry(client.get_stock_bars, request)

    daily_bars = []
    if bars_data and hasattr(bars_data, 'data') and ticker in bars_data.data:
        for bar in bars_data.data[ticker]:
            bar_date = bar.timestamp.astimezone(ET_TZ).date()
            if bar_date < today_et:
                daily_bars.append(DailyBar(date=bar_date, open=float(bar.open), high=float(bar.high),
                                            low=float(bar.low), close=float(bar.close)))
    return daily_bars


def fetch_premarket_minute_bars(client, ticker: str, today_et: date):
    """Minute bars for today so far, from 4:00am ET through now."""
    start = ET_TZ.localize(datetime.combine(today_et, dt_time(4, 0)))
    end = datetime.now(ET_TZ)
    request = StockBarsRequest(symbol_or_symbols=ticker, timeframe=TimeFrame.Minute,
                                start=start, end=end, feed=DataFeed.SIP)
    bars_data = _call_with_retry(client.get_stock_bars, request)

    bars = []
    if bars_data and hasattr(bars_data, 'data') and ticker in bars_data.data:
        for bar in bars_data.data[ticker]:
            bar_ts_et = bar.timestamp.astimezone(ET_TZ)
            if bar_ts_et.date() != today_et or bar_ts_et.time() >= strategy.MARKET_OPEN_ET:
                continue
            bars.append(Bar(ts=bar_ts_et, open=float(bar.open), high=float(bar.high),
                             low=float(bar.low), close=float(bar.close), volume=float(bar.volume)))
    bars.sort(key=lambda b: b.ts)
    return bars


class LiveTrader:
    def __init__(self, pretop20_dir: Path, data_dir: Path):
        api_key = os.environ.get('APCA_API_KEY_ID')
        api_secret = os.environ.get('APCA_API_SECRET_KEY')
        if not api_key or not api_secret:
            logger.error("Alpaca API keys not found. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY "
                          "(e.g. `source secrets.env` before running).")
            sys.exit(1)
        self.client = StockHistoricalDataClient(api_key, api_secret)

        self.pretop20_dir = pretop20_dir
        self.data_dir = data_dir
        self.trade_file = data_dir / 'trade_history.json'
        data_dir.mkdir(parents=True, exist_ok=True)
        self.trades = self._load_existing_trades()

        self.today = None  # reset per-day state lazily in scan_once
        self.open_positions = {}   # ticker -> Bar (entry_bar) + premarket_low_so_far, tracked as tuple
        self.flatness_cache = {}   # ticker -> (flat_ok, baseline_close)
        self.decided_today = set()  # tickers with a final entry/reject decision for today

    def _load_existing_trades(self):
        if self.trade_file.exists():
            with open(self.trade_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    def _save_trades(self):
        with open(self.trade_file, 'w', encoding='utf-8') as f:
            json.dump(self.trades, f, indent=2)

    def _reset_for_new_day(self, today_et: date):
        logger.info(f"📅 New trading day: {today_et}")
        self.today = today_et
        self.open_positions = {}
        self.flatness_cache = {}
        self.decided_today = set()

    def _get_flatness(self, ticker: str, today_et: date):
        if ticker not in self.flatness_cache:
            daily_bars = fetch_daily_bars(self.client, ticker, today_et)
            flat_ok = strategy.is_flat_before(daily_bars, today_et)
            baseline = daily_bars[-1].close if flat_ok and daily_bars else None
            self.flatness_cache[ticker] = (flat_ok, baseline)
        return self.flatness_cache[ticker]

    def scan_once(self):
        today_et = datetime.now(ET_TZ).date()
        if today_et != self.today:
            self._reset_for_new_day(today_et)

        candidates = load_today_candidates(self.pretop20_dir, today_et, MIN_CANDIDATE_PCT)
        for ticker in sorted(candidates):
            if ticker in self.decided_today or ticker in self.open_positions:
                continue

            flat_ok, baseline = self._get_flatness(ticker, today_et)
            if not flat_ok:
                self.decided_today.add(ticker)  # daily bars won't change intraday, no point rechecking
                continue

            minute_bars = fetch_premarket_minute_bars(self.client, ticker, today_et)
            if not minute_bars:
                continue  # data not available yet this tick - try again next tick, don't mark decided

            spike_bar = strategy.find_spike_start(minute_bars, baseline)
            if spike_bar is None:
                continue  # no spike yet - keep checking as more premarket bars accumulate

            # A qualifying first-crossing bar exists now; this is a fixed fact
            # about today's history, so the decision about it won't change later.
            self.decided_today.add(ticker)

            if spike_bar.close < strategy.MIN_ENTRY_PRICE:
                logger.info(f"⏭️  {ticker}: spike at ${spike_bar.close:.2f} < "
                            f"MIN_ENTRY_PRICE ${strategy.MIN_ENTRY_PRICE}, skipping")
                continue
            if not strategy.has_sufficient_liquidity(minute_bars, spike_bar):
                logger.info(f"⏭️  {ticker}: spike found but pre-entry liquidity too thin, skipping")
                continue

            premarket_low_so_far = min(b.low for b in minute_bars if b.ts <= spike_bar.ts)
            self.open_positions[ticker] = (spike_bar, premarket_low_so_far)
            logger.info(f"📈 OPENED {ticker} @ ${spike_bar.close:.2f} ({spike_bar.ts.strftime('%H:%M')} ET)")

        for ticker in list(self.open_positions.keys()):
            entry_bar, premarket_low_so_far = self.open_positions[ticker]
            bars = fetch_premarket_minute_bars(self.client, ticker, today_et)
            if not bars:
                continue
            position, exit_info = strategy.replay_to_exit(ticker, entry_bar, premarket_low_so_far, bars)
            if exit_info is not None:
                trade = strategy.build_trade_result(position, *exit_info)
                self.trades.append(trade)
                self._save_trades()
                del self.open_positions[ticker]
                marker = '✅' if trade['profit_loss'] > 0 else '❌'
                logger.info(f"📉 CLOSED {ticker} {marker} {trade['profit_pct']:+.1f}% "
                            f"[{trade['exit_reason']}]")

    def run(self):
        logger.info(f"🚀 flat_spike live paper trader started (data-dir={self.data_dir})")
        while True:
            try:
                self.scan_once()
            except Exception as e:
                logger.warning(f"⚠️  Scan error: {e}")
            time.sleep(SCAN_INTERVAL_SECONDS)


def parse_arguments():
    parser = argparse.ArgumentParser(description='Live paper-trading daemon for the flat-spike strategy')
    parser.add_argument('--pretop20-dir', type=str, default='pretop20')
    parser.add_argument('--data-dir', type=str, default='momentum_data/flat_spike_live_trades')
    args = parser.parse_args()
    return args


def main():
    args = parse_arguments()

    try:
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"📝 PID {os.getpid()} written to {PID_FILE}")
    except Exception as e:
        logger.warning(f"⚠️  Could not write PID file: {e}")

    try:
        trader = LiveTrader(Path(args.pretop20_dir), Path(args.data_dir))
        trader.run()
    finally:
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
                logger.info(f"🗑️  Removed PID file {PID_FILE}")
        except Exception as e:
            logger.warning(f"⚠️  Could not remove PID file: {e}")


if __name__ == '__main__':
    main()
