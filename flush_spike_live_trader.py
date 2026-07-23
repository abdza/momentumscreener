#!/usr/bin/env python3
"""
Live paper-trading daemon for flush_spike_strategy.py.

Sibling to flat_spike_live_trader.py, run by cron over the same premarket window
(started alongside pretop20.sh, killed at market open). Writes simulated trades to
<data-dir>/trade_history.json in paper_trading_system.py's schema, so
paper_trading_analyzer.py can report on them. Places no real orders.

Candidate tickers come from the same pretop20/screener_*.json snapshots flat_spike
uses - reuses flat_spike_live_trader.load_today_candidates and
fetch_premarket_minute_bars directly rather than redefining them, since candidate
sourcing and bar fetching don't depend on which strategy reads the result.

Unlike flat_spike (one clean spike = one trade, ticker is "decided" for the rest of
the day either way), this strategy can fire multiple flush/reload legs on the same
ticker in one session, so a ticker only drops out of consideration for the *rest of
the current search window* - after a trade closes, the search resumes on bars after
that trade's exit, looking for another leg.

Usage:
    python flush_spike_live_trader.py
    python flush_spike_live_trader.py --data-dir momentum_data/flush_spike_live_trades
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, date
from pathlib import Path

import pytz
from telegram import Bot

import flush_spike_strategy as strategy
from flat_spike_live_trader import load_today_candidates, fetch_premarket_minute_bars

from alpaca.data.historical import StockHistoricalDataClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ET_TZ = pytz.timezone('America/New_York')

PID_FILE = '/tmp/flush_spike_live.pid'
SCAN_INTERVAL_SECONDS = 60
MIN_CANDIDATE_PCT = 5.0  # noise floor for the pretop20 shortlist, matches the backtester's default


class LiveTrader:
    def __init__(self, pretop20_dir: Path, data_dir: Path):
        api_key = os.environ.get('APCA_API_KEY_ID')
        api_secret = os.environ.get('APCA_API_SECRET_KEY')
        if not api_key or not api_secret:
            logger.error("Alpaca API keys not found. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY "
                          "(e.g. `source secrets.env` before running).")
            sys.exit(1)
        self.client = StockHistoricalDataClient(api_key, api_secret)

        telegram_bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        telegram_chat_id = os.environ.get('TELEGRAM_CHAT_ID')
        self.telegram_chat_id = telegram_chat_id
        self.telegram_bot = None
        if telegram_bot_token and telegram_chat_id:
            self.telegram_bot = Bot(token=telegram_bot_token)
            logger.info("✅ Telegram bot initialized")
        else:
            logger.warning("⚠️  No Telegram credentials found (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID) - "
                            "trade notifications disabled")

        self.pretop20_dir = pretop20_dir
        self.data_dir = data_dir
        self.trade_file = data_dir / 'trade_history.json'
        data_dir.mkdir(parents=True, exist_ok=True)
        self.trades = self._load_existing_trades()

        self.today = None  # reset per-day state lazily in scan_once
        self.open_positions = {}   # ticker -> (entry_bar, premarket_low_so_far)
        self.reentry_after = {}    # ticker -> timestamp of that ticker's last trade exit

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
        self.reentry_after = {}

    async def _send_telegram_message(self, message):
        if not self.telegram_bot or not self.telegram_chat_id:
            return
        try:
            await self.telegram_bot.send_message(
                self.telegram_chat_id,
                message,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"❌ Failed to send Telegram message: {e}")
            try:
                plain_message = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', message)
                plain_message = plain_message.replace('*', '').replace('`', '')
                await self.telegram_bot.send_message(
                    self.telegram_chat_id,
                    plain_message,
                    disable_web_page_preview=True
                )
            except Exception as e2:
                logger.error(f"❌ Failed to send plain text message too: {e2}")

    def _notify(self, message):
        if not self.telegram_bot:
            return
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self._send_telegram_message(message))
        except Exception as e:
            logger.warning(f"⚠️  Telegram notification failed: {e}")

    def scan_once(self):
        today_et = datetime.now(ET_TZ).date()
        if today_et != self.today:
            self._reset_for_new_day(today_et)

        candidates = load_today_candidates(self.pretop20_dir, today_et, MIN_CANDIDATE_PCT)
        for ticker in sorted(candidates):
            if ticker in self.open_positions:
                continue

            minute_bars = fetch_premarket_minute_bars(self.client, ticker, today_et)
            if not minute_bars:
                continue  # data not available yet this tick

            since = self.reentry_after.get(ticker)
            search_bars = [b for b in minute_bars if since is None or b.ts > since]
            if not search_bars:
                continue

            entry_bar = strategy.find_flush_reload_start(search_bars)
            if entry_bar is None:
                continue  # no leg yet - keep checking as more premarket bars accumulate

            if entry_bar.close >= strategy.MAX_ENTRY_PRICE:
                logger.info(f"⏭️  {ticker}: reload at ${entry_bar.close:.2f} >= "
                            f"MAX_ENTRY_PRICE ${strategy.MAX_ENTRY_PRICE}, skipping this leg")
                self.reentry_after[ticker] = entry_bar.ts
                continue
            if not strategy.has_sufficient_liquidity(search_bars, entry_bar):
                logger.info(f"⏭️  {ticker}: reload found but pre-entry liquidity too thin, "
                            f"skipping this leg")
                self.reentry_after[ticker] = entry_bar.ts
                continue

            premarket_low_so_far = min(b.low for b in search_bars if b.ts <= entry_bar.ts)
            self.open_positions[ticker] = (entry_bar, premarket_low_so_far)
            logger.info(f"📈 OPENED {ticker} @ ${entry_bar.close:.2f} ({entry_bar.ts.strftime('%H:%M')} ET)")
            self._notify(
                f"🌊 *FLUSH BUY* [{ticker}](https://www.tradingview.com/chart/?symbol={ticker})\n"
                f"Entry: ${entry_bar.close:.2f} @ {entry_bar.ts.strftime('%H:%M')} ET"
            )

        for ticker in list(self.open_positions.keys()):
            entry_bar, premarket_low_so_far = self.open_positions[ticker]
            bars = fetch_premarket_minute_bars(self.client, ticker, today_et)
            if not bars:
                continue
            position, exit_info = strategy.replay_to_exit(ticker, entry_bar, premarket_low_so_far, bars)
            if exit_info is not None:
                trade = strategy.build_trade_result(position, *exit_info)
                trade['alert_type'] = 'flush_spike'
                self.trades.append(trade)
                self._save_trades()
                del self.open_positions[ticker]
                self.reentry_after[ticker] = exit_info[0]
                marker = '✅' if trade['profit_loss'] > 0 else '❌'
                logger.info(f"📉 CLOSED {ticker} {marker} {trade['profit_pct']:+.1f}% "
                            f"[{trade['exit_reason']}]")
                self._notify(
                    f"🌊 *FLUSH SELL* [{ticker}](https://www.tradingview.com/chart/?symbol={ticker}) {marker}\n"
                    f"Exit: ${trade['exit_price']:.2f}  P/L: {trade['profit_pct']:+.1f}% "
                    f"(${trade['profit_loss']:+.2f})\n"
                    f"Reason: {trade['exit_reason'].replace('_', ' ')}"
                )

    def run(self):
        logger.info(f"🚀 flush_spike live paper trader started (data-dir={self.data_dir})")
        while True:
            try:
                self.scan_once()
            except Exception as e:
                logger.warning(f"⚠️  Scan error: {e}")
            time.sleep(SCAN_INTERVAL_SECONDS)


def parse_arguments():
    parser = argparse.ArgumentParser(description='Live paper-trading daemon for the flush-spike strategy')
    parser.add_argument('--pretop20-dir', type=str, default='pretop20')
    parser.add_argument('--data-dir', type=str, default='momentum_data/flush_spike_live_trades')
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
