#!/usr/bin/env python3
"""
Flat-spike backtester

Replays the flat-then-premarket-spike strategy (flat_spike_strategy.py) against
history:
  1. Uses the archived pretop20/screener_*.json snapshots as a cheap candidate
     shortlist - tickers that showed a meaningful premarket move on a given day.
  2. For each (ticker, day) candidate, pulls daily bars from Alpaca to check it was
     flat over the preceding days, then premarket+regular-hours minute bars to find
     the spike and replay the trade.
  3. Writes results to <data-dir>/trade_history.json in the same schema
     paper_trading_system.py uses, so paper_trading_analyzer.py's reporting works
     unmodified:
         python paper_trading_analyzer.py --data-dir momentum_data/flat_spike_trades

Usage:
    python flat_spike_backtester.py --start-date 2026-06-01 --end-date 2026-07-21
    python flat_spike_backtester.py --list-candidates-only   # sanity check, no API calls
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path

import pytz

import flat_spike_strategy as strategy
from flat_spike_strategy import Bar, DailyBar

try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import DataFeed
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ET_TZ = pytz.timezone('America/New_York')
LOCAL_TZ = pytz.timezone('Asia/Kuala_Lumpur')  # matches the machine that writes pretop20/


def load_daily_candidates(pretop20_dir: Path, start_date: date, end_date: date,
                           min_candidate_pct: float):
    """
    Walk the archived screener snapshots and build {day: {ticker: max_pct_seen}} for
    tickers whose premarket change crossed min_candidate_pct at some point that day.
    This is just a shortlist to avoid pulling Alpaca data for the whole market - the
    actual entry signal is decided later from real minute bars.
    """
    candidates = {}
    files = sorted(pretop20_dir.glob('screener_*.json'))
    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Skipping unreadable {f.name}: {e}")
            continue

        ts_str = payload.get('timestamp', '')
        try:
            ts = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            continue
        if ts.tzinfo is None:
            ts = LOCAL_TZ.localize(ts)
        ts_et = ts.astimezone(ET_TZ)
        day = ts_et.date()

        if day < start_date or day > end_date:
            continue

        day_bucket = candidates.setdefault(day, {})
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
            if pct >= min_candidate_pct:
                if pct > day_bucket.get(ticker, float('-inf')):
                    day_bucket[ticker] = pct

    return {d: c for d, c in candidates.items() if c}


def _call_with_retry(fn, *args, max_retries=5, base_delay=2.0, **kwargs):
    """Small retry-with-backoff wrapper - no existing Alpaca rate-limit handling
    in this repo, and we're hitting the API for many symbol/day pairs here."""
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


def _cache_path(cache_dir: Path, symbol: str, day: date, kind: str) -> Path:
    return cache_dir / f"{symbol}_{day.isoformat()}_{kind}.json"


def _bars_to_cache(bars):
    return [{'t': b.ts.isoformat(), 'o': b.open, 'h': b.high, 'l': b.low,
             'c': b.close, 'v': b.volume} for b in bars]


def _bars_from_cache(rows):
    return [Bar(ts=datetime.fromisoformat(r['t']), open=r['o'], high=r['h'],
                low=r['l'], close=r['c'], volume=r.get('v', 0.0)) for r in rows]


def fetch_daily_bars(client, cache_dir: Path, symbol: str, spike_day: date,
                      lookback_days: int, use_cache: bool = True):
    """Daily bars for the window ending the trading day before spike_day."""
    cache_file = _cache_path(cache_dir, symbol, spike_day, 'daily')
    if use_cache and cache_file.exists():
        with open(cache_file, 'r', encoding='utf-8') as f:
            rows = json.load(f)
        return [DailyBar(date=date.fromisoformat(r['d']), open=r['o'], high=r['h'],
                          low=r['l'], close=r['c']) for r in rows]

    start = ET_TZ.localize(datetime.combine(spike_day - timedelta(days=lookback_days * 3 + 10),
                                             dt_time(0, 0)))
    end = ET_TZ.localize(datetime.combine(spike_day, dt_time(0, 0)))

    request = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day,
                                start=start, end=end, feed=DataFeed.SIP)
    bars_data = _call_with_retry(client.get_stock_bars, request)

    daily_bars = []
    if bars_data and hasattr(bars_data, 'data') and symbol in bars_data.data:
        for bar in bars_data.data[symbol]:
            bar_date = bar.timestamp.astimezone(ET_TZ).date()
            if bar_date < spike_day:
                daily_bars.append(DailyBar(date=bar_date, open=float(bar.open),
                                            high=float(bar.high), low=float(bar.low),
                                            close=float(bar.close)))

    cache_dir.mkdir(parents=True, exist_ok=True)
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump([{'d': b.date.isoformat(), 'o': b.open, 'h': b.high, 'l': b.low,
                     'c': b.close} for b in daily_bars], f)
    return daily_bars


def fetch_day_minute_bars(client, cache_dir: Path, symbol: str, day: date,
                           use_cache: bool = True):
    """Minute bars for one ET calendar day, 4:00am through market close (16:00)."""
    cache_file = _cache_path(cache_dir, symbol, day, 'minute')
    if use_cache and cache_file.exists():
        with open(cache_file, 'r', encoding='utf-8') as f:
            rows = json.load(f)
        return _bars_from_cache(rows)

    start = ET_TZ.localize(datetime.combine(day, dt_time(4, 0)))
    end = ET_TZ.localize(datetime.combine(day, dt_time(16, 0)))

    request = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute,
                                start=start, end=end, feed=DataFeed.SIP)
    bars_data = _call_with_retry(client.get_stock_bars, request)

    minute_bars = []
    if bars_data and hasattr(bars_data, 'data') and symbol in bars_data.data:
        for bar in bars_data.data[symbol]:
            bar_ts_et = bar.timestamp.astimezone(ET_TZ)
            if bar_ts_et.date() != day:
                continue
            minute_bars.append(Bar(ts=bar_ts_et, open=float(bar.open), high=float(bar.high),
                                    low=float(bar.low), close=float(bar.close),
                                    volume=float(bar.volume)))
    minute_bars.sort(key=lambda b: b.ts)

    cache_dir.mkdir(parents=True, exist_ok=True)
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(_bars_to_cache(minute_bars), f)
    return minute_bars


def run_backtest(args):
    pretop20_dir = Path(args.pretop20_dir)
    candidates = load_daily_candidates(pretop20_dir, args.start_date, args.end_date,
                                        args.min_candidate_pct)
    total_candidates = sum(len(c) for c in candidates.values())
    logger.info(f"📋 {total_candidates} (ticker, day) candidates across {len(candidates)} days")

    if args.list_candidates_only:
        for day in sorted(candidates):
            tickers = candidates[day]
            top = sorted(tickers.items(), key=lambda kv: -kv[1])[:10]
            logger.info(f"  {day}: {len(tickers)} candidates, top: "
                        f"{', '.join(f'{t}({p:.0f}%)' for t, p in top)}")
        return []

    if not ALPACA_AVAILABLE:
        logger.error("alpaca-py not installed. Run: pip install alpaca-py")
        sys.exit(1)

    api_key = os.environ.get('APCA_API_KEY_ID')
    api_secret = os.environ.get('APCA_API_SECRET_KEY')
    if not api_key or not api_secret:
        logger.error("Alpaca API keys not found. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY "
                      "(e.g. `source secrets.env` before running).")
        sys.exit(1)

    client = StockHistoricalDataClient(api_key, api_secret)

    cache_dir = Path(args.cache_dir)
    trades = []
    processed = 0

    for day in sorted(candidates):
        for ticker in sorted(candidates[day]):
            if args.limit and processed >= args.limit:
                break
            processed += 1
            try:
                daily_bars = fetch_daily_bars(client, cache_dir, ticker, day,
                                               args.flat_days, use_cache=not args.no_cache)
                if not strategy.is_flat_before(daily_bars, day,
                                                lookback_days=args.flat_days,
                                                max_daily_range_pct=args.flat_max_range,
                                                max_net_drift_pct=args.flat_max_drift,
                                                min_avg_range_pct=args.flat_min_avg_range):
                    continue

                minute_bars = fetch_day_minute_bars(client, cache_dir, ticker, day,
                                                     use_cache=not args.no_cache)
                if not minute_bars:
                    continue

                premarket_bars = [b for b in minute_bars if b.ts.time() < strategy.MARKET_OPEN_ET]
                if not premarket_bars:
                    continue

                baseline_price = daily_bars[-1].close  # most recent flat-period close
                spike_bar = strategy.find_spike_start(premarket_bars, baseline_price,
                                                        spike_min_pct=args.spike_min_pct,
                                                        spike_earliest_et=args.spike_earliest_et)
                if spike_bar is None:
                    continue
                if spike_bar.close < args.min_entry_price:
                    continue
                if not strategy.has_sufficient_liquidity(premarket_bars, spike_bar,
                                                           min_avg_dollar_vol=args.min_dollar_vol):
                    continue

                premarket_low_so_far = min(b.low for b in premarket_bars if b.ts <= spike_bar.ts)
                bars_from_entry = [b for b in minute_bars if b.ts >= spike_bar.ts]

                trade = strategy.simulate_trade(
                    ticker, spike_bar, premarket_low_so_far, bars_from_entry,
                    position_size=args.position_size,
                    range_drawdown_pct=args.range_pct,
                    trailing_recovery_minutes=args.trailing_minutes)
                trades.append(trade)

                marker = '✅' if trade['profit_loss'] > 0 else '❌'
                logger.info(f"{marker} {ticker} {day} entry ${trade['entry_price']} -> "
                            f"exit ${trade['exit_price']} ({trade['profit_pct']:+.1f}%) "
                            f"[{trade['exit_reason']}]")
            except Exception as e:
                logger.warning(f"⚠️  {ticker} {day}: {e}")

            time.sleep(args.request_delay)
        if args.limit and processed >= args.limit:
            break

    return trades


def save_trades(trades, data_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True)
    trade_file = data_dir / 'trade_history.json'
    with open(trade_file, 'w', encoding='utf-8') as f:
        json.dump(trades, f, indent=2)
    logger.info(f"💾 Wrote {len(trades)} trades to {trade_file}")


def print_summary(trades):
    if not trades:
        print("\n📭 No trades generated.")
        return
    wins = [t for t in trades if t['profit_loss'] > 0]
    total_pnl = sum(t['profit_loss'] for t in trades)
    avg_pct = sum(t['profit_pct'] for t in trades) / len(trades)
    avg_hold = sum(t['holding_time_minutes'] for t in trades) / len(trades)
    print(f"\n{'='*60}\nBACKTEST SUMMARY\n{'='*60}")
    print(f"Total trades: {len(trades)}")
    print(f"Win rate: {len(wins)/len(trades)*100:.1f}% ({len(wins)}/{len(trades)})")
    print(f"Total P&L: ${total_pnl:+.2f}")
    print(f"Avg return: {avg_pct:+.2f}%")
    print(f"Avg holding time: {avg_hold:.1f} min")
    print(f"\nFor the full report: python paper_trading_analyzer.py --data-dir <data-dir>")


def parse_arguments():
    parser = argparse.ArgumentParser(description='Backtest the flat-then-premarket-spike strategy')
    parser.add_argument('--start-date', type=str, required=True, help='YYYY-MM-DD')
    parser.add_argument('--end-date', type=str, required=True, help='YYYY-MM-DD')
    parser.add_argument('--pretop20-dir', type=str, default='pretop20')
    parser.add_argument('--data-dir', type=str, default='momentum_data/flat_spike_trades')
    parser.add_argument('--cache-dir', type=str, default='momentum_data/flat_spike_cache')
    parser.add_argument('--no-cache', action='store_true', help='Force re-fetch from Alpaca')
    parser.add_argument('--min-candidate-pct', type=float, default=5.0,
                         help='Noise floor for candidate shortlist (default: 5.0)')
    parser.add_argument('--flat-days', type=int, default=strategy.FLAT_LOOKBACK_DAYS)
    parser.add_argument('--flat-max-range', type=float, default=strategy.FLAT_MAX_DAILY_RANGE_PCT)
    parser.add_argument('--flat-max-drift', type=float, default=strategy.FLAT_MAX_NET_DRIFT_PCT)
    parser.add_argument('--flat-min-avg-range', type=float, default=strategy.FLAT_MIN_AVG_RANGE_PCT,
                         help='Reject dead-still tickers: require avg daily range over the '
                              'flat window to be at least this %% (default: %(default)s)')
    parser.add_argument('--spike-min-pct', type=float, default=strategy.SPIKE_MIN_PCT)
    parser.add_argument('--range-pct', type=float, default=strategy.RANGE_DRAWDOWN_PCT,
                         help='Retracement trigger as a %% of the day\'s range (peak minus '
                              'premarket low), not a %% of price (default: %(default)s)')
    parser.add_argument('--trailing-minutes', type=int, default=strategy.TRAILING_RECOVERY_MINUTES)
    parser.add_argument('--min-entry-price', type=float, default=strategy.MIN_ENTRY_PRICE,
                         help='Skip candidates whose entry price is below this (default: %(default)s)')
    parser.add_argument('--min-dollar-vol', type=float, default=strategy.MIN_PRE_ENTRY_DOLLAR_VOL,
                         help='Skip candidates whose avg $ volume/min before entry is below this '
                              '(default: %(default)s)')
    parser.add_argument('--position-size', type=float, default=strategy.POSITION_SIZE)
    parser.add_argument('--request-delay', type=float, default=0.2,
                         help='Seconds to sleep between symbols (be polite to the API)')
    parser.add_argument('--limit', type=int, default=None,
                         help='Cap number of (ticker, day) candidates processed - useful for a quick smoke test')
    parser.add_argument('--list-candidates-only', action='store_true',
                         help='Only print the candidate shortlist, no Alpaca calls')

    args = parser.parse_args()
    args.start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    args.end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    args.spike_earliest_et = strategy.SPIKE_EARLIEST_ET
    return args


def main():
    args = parse_arguments()
    trades = run_backtest(args)
    if args.list_candidates_only:
        return
    save_trades(trades, Path(args.data_dir))
    print_summary(trades)


if __name__ == '__main__':
    main()
