#!/usr/bin/env python3
"""
Flush-spike backtester

Replays the flush-then-reload strategy (flush_spike_strategy.py) against history.
Sibling to flat_spike_backtester.py, reusing its candidate-shortlist and minute-bar
fetch/cache infrastructure directly (identical Alpaca data either way, so this shares
flat_spike's cache dir rather than re-fetching):
  1. Uses the archived pretop20/screener_*.json snapshots as a cheap candidate
     shortlist (via flat_spike_backtester.load_daily_candidates).
  2. For each (ticker, day) candidate, pulls premarket+regular-hours minute bars
     from Alpaca (via flat_spike_backtester.fetch_day_minute_bars) - no daily-bar
     fetch or flatness check, this strategy has no prior-day requirement.
  3. Unlike flat_spike (one spike = one trade), replays find_flush_reload_start in
     a loop: each simulated trade's exit timestamp advances the bar window, so a
     ticker with several flush/reload legs in one session produces several trades.
  4. Writes results to <data-dir>/trade_history.json in the same schema
     paper_trading_system.py uses, so paper_trading_analyzer.py's reporting works
     unmodified:
         python paper_trading_analyzer.py --data-dir momentum_data/flush_spike_trades

Usage:
    python flush_spike_backtester.py --start-date 2026-06-01 --end-date 2026-07-23
    python flush_spike_backtester.py --list-candidates-only   # sanity check, no API calls
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

import flush_spike_strategy as strategy
from flat_spike_backtester import load_daily_candidates, fetch_day_minute_bars

try:
    from alpaca.data.historical import StockHistoricalDataClient
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


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
                minute_bars = fetch_day_minute_bars(client, cache_dir, ticker, day,
                                                     use_cache=not args.no_cache)
                if not minute_bars:
                    continue

                premarket_bars = [b for b in minute_bars if b.ts.time() < strategy.MARKET_OPEN_ET]
                if not premarket_bars:
                    continue

                remaining = premarket_bars
                while True:
                    entry_bar = strategy.find_flush_reload_start(
                        remaining,
                        flush_min_drop_pct=args.flush_min_drop,
                        reload_min_pct=args.reload_min_pct,
                        min_entry_price=args.min_entry_price)
                    if entry_bar is None:
                        break
                    if entry_bar.close >= args.max_entry_price:
                        # this leg's reload ran too high to enter - skip past it and
                        # keep looking for a later flush/reload leg on the same ticker
                        remaining = [b for b in remaining if b.ts > entry_bar.ts]
                        if not remaining:
                            break
                        continue
                    if not strategy.has_sufficient_liquidity(remaining, entry_bar,
                                                              min_avg_dollar_vol=args.min_dollar_vol):
                        remaining = [b for b in remaining if b.ts > entry_bar.ts]
                        if not remaining:
                            break
                        continue

                    premarket_low_so_far = min(b.low for b in remaining if b.ts <= entry_bar.ts)
                    bars_from_entry = [b for b in minute_bars if b.ts >= entry_bar.ts]

                    trade = strategy.simulate_trade(
                        ticker, entry_bar, premarket_low_so_far, bars_from_entry,
                        position_size=args.position_size,
                        range_drawdown_pct=args.range_pct,
                        trailing_recovery_minutes=args.trailing_minutes)
                    trade['alert_type'] = 'flush_spike'
                    trades.append(trade)

                    marker = '✅' if trade['profit_loss'] > 0 else '❌'
                    logger.info(f"{marker} {ticker} {day} entry ${trade['entry_price']} -> "
                                f"exit ${trade['exit_price']} ({trade['profit_pct']:+.1f}%) "
                                f"[{trade['exit_reason']}]")

                    exit_ts = datetime.fromisoformat(trade['exit_timestamp'])
                    remaining = [b for b in premarket_bars if b.ts > exit_ts]
                    if not remaining:
                        break
            except Exception as e:
                logger.warning(f"⚠️  {ticker} {day}: {e}")

            time.sleep(args.request_delay)
        if args.limit and processed >= args.limit:
            break

    return trades


def save_trades(trades, data_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True)
    trade_file = data_dir / 'trade_history.json'
    import json
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
    parser = argparse.ArgumentParser(description='Backtest the flush-then-reload strategy')
    parser.add_argument('--start-date', type=str, required=True, help='YYYY-MM-DD')
    parser.add_argument('--end-date', type=str, required=True, help='YYYY-MM-DD')
    parser.add_argument('--pretop20-dir', type=str, default='pretop20')
    parser.add_argument('--data-dir', type=str, default='momentum_data/flush_spike_trades')
    parser.add_argument('--cache-dir', type=str, default='momentum_data/flat_spike_cache',
                         help='Shared with flat_spike_backtester - same minute bars either way')
    parser.add_argument('--no-cache', action='store_true', help='Force re-fetch from Alpaca')
    parser.add_argument('--min-candidate-pct', type=float, default=5.0,
                         help='Noise floor for candidate shortlist (default: 5.0)')
    parser.add_argument('--flush-min-drop', type=float, default=strategy.FLUSH_MIN_DROP_PCT,
                         help='Peak-to-trough drop %% required to count as a flush (default: %(default)s)')
    parser.add_argument('--reload-min-pct', type=float, default=strategy.RELOAD_MIN_PCT,
                         help='Rebound %% off the flush low required to trigger entry (default: %(default)s)')
    parser.add_argument('--range-pct', type=float, default=strategy.RANGE_DRAWDOWN_PCT,
                         help='Retracement trigger as a %% of the day\'s range (peak minus '
                              'premarket low), not a %% of price (default: %(default)s)')
    parser.add_argument('--trailing-minutes', type=int, default=strategy.TRAILING_RECOVERY_MINUTES)
    parser.add_argument('--min-entry-price', type=float, default=strategy.MIN_ENTRY_PRICE,
                         help='Skip candidates whose entry price is below this (default: %(default)s)')
    parser.add_argument('--max-entry-price', type=float, default=strategy.MAX_ENTRY_PRICE,
                         help='Skip candidates whose entry price is at/above this (default: %(default)s)')
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
