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

Besides those system-found entries, the daemon also listens on Telegram for
manually declared positions: `/b TICKER [price]` tells it "I'm in this one", and
from then on it watches that ticker with the *same* exit rules (premarket-low
stop, range trailing stop, 9:20 force close) and messages when to sell. These are
tracked separately from system trades - open ones in <data-dir>/manual_positions.json
(so a restart mid-session doesn't lose them, since unlike system entries they
can't be re-derived from market data), closed ones in <data-dir>/manual_trades.json
(kept out of trade_history.json so they don't skew the strategy's own stats).

The Telegram listener lives here rather than in flush_spike_live_trader.py - the
two daemons run over the same window and share one bot token, and Telegram only
allows one getUpdates consumer per token. The exit rules are shared code
(flush_spike_strategy re-exports flat_spike's check_exit/replay_to_exit), so a
manual position is watched identically either way.

Usage:
    python flat_spike_live_trader.py
    python flat_spike_live_trader.py --data-dir momentum_data/flat_spike_live_trades

Telegram commands (accepted only from TELEGRAM_CHAT_ID):
    /b TICKER [price]   track a position you entered yourself (price defaults to last print)
    /s TICKER           stop tracking it now and record the trade
    /positions          list what's currently being watched
    /help               command reference
"""

import argparse
import asyncio
import glob
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, date, timedelta, time as dt_time
from pathlib import Path

import pytz
from telegram import Bot

import flat_spike_strategy as strategy
from flat_spike_strategy import Bar, DailyBar

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# httpx logs every request at INFO - with a getUpdates poll every few seconds that
# buries the trade log, and each line contains the bot token in the URL.
logging.getLogger('httpx').setLevel(logging.WARNING)

ET_TZ = pytz.timezone('America/New_York')
LOCAL_TZ = pytz.timezone('Asia/Kuala_Lumpur')  # matches the machine that writes pretop20/

PID_FILE = '/tmp/flat_spike_live.pid'
SCAN_INTERVAL_SECONDS = 60
MIN_CANDIDATE_PCT = 5.0  # noise floor for the pretop20 shortlist, matches the backtester's default
DAILY_LOOKBACK_DAYS = strategy.FLAT_LOOKBACK_DAYS * 3 + 10  # calendar days, matches the backtester

MANUAL_POSITIONS_FILENAME = 'manual_positions.json'
MANUAL_TRADES_FILENAME = 'manual_trades.json'
# Seconds each getUpdates call holds the connection open waiting for a command.
# The waiting doubles as the pause between scans, so commands land within
# ~TELEGRAM_POLL_TIMEOUT_SECONDS instead of at the next scan boundary.
TELEGRAM_POLL_TIMEOUT_SECONDS = 20

HELP_TEXT = (
    "📱 *flat\\_spike live trader*\n\n"
    "• `/b TICKER [price]` - track a position you bought yourself; I'll tell you when "
    "the exit rules say to sell. Price defaults to the last premarket print.\n"
    "• `/s TICKER` - stop tracking and record the trade at the current price\n"
    "• `/positions` - list what's being watched right now\n"
    "• `/help` - this message\n\n"
    "Exit rules (same ones the system uses): price back to today's premarket low, "
    f"a pullback off the peak worth {strategy.RANGE_DRAWDOWN_PCT:.0f}% of the day's range "
    f"that doesn't recover within {strategy.TRAILING_RECOVERY_MINUTES} minutes, or "
    f"{strategy.PREMARKET_END_ET.strftime('%H:%M')} ET force close.\n\n"
    "Example: `/b AAPL` or `/b AAPL 12.34`"
)


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

        # One long-lived loop for every Telegram call: the bot's HTTP client binds
        # to the loop it first runs on, so it can't be shared across fresh loops.
        self._loop = asyncio.new_event_loop()
        self._telegram_update_offset = None

        self.pretop20_dir = pretop20_dir
        self.data_dir = data_dir
        self.trade_file = data_dir / 'trade_history.json'
        self.manual_trade_file = data_dir / MANUAL_TRADES_FILENAME
        self.manual_positions_file = data_dir / MANUAL_POSITIONS_FILENAME
        data_dir.mkdir(parents=True, exist_ok=True)
        self.trades = self._read_json(self.trade_file, [])
        self.manual_trades = self._read_json(self.manual_trade_file, [])

        self.today = None  # reset per-day state lazily in scan_once
        self.open_positions = {}   # ticker -> Bar (entry_bar) + premarket_low_so_far, tracked as tuple
        self.manual_positions = {}  # same shape, for user-declared positions (/b TICKER)
        self.flatness_cache = {}   # ticker -> (flat_ok, baseline_close)
        self.decided_today = set()  # tickers with a final entry/reject decision for today

    @staticmethod
    def _read_json(path: Path, default):
        if not path.exists():
            return default
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"⚠️  Could not read {path}: {e}")
            return default

    def _save_trades(self):
        with open(self.trade_file, 'w', encoding='utf-8') as f:
            json.dump(self.trades, f, indent=2)

    def _save_manual_trades(self):
        with open(self.manual_trade_file, 'w', encoding='utf-8') as f:
            json.dump(self.manual_trades, f, indent=2)

    def _save_manual_positions(self):
        """Persist open manual positions on every change. A system entry can be
        rebuilt from market data after a restart; a manual one only exists because
        the user said so, so it has to survive on disk."""
        payload = {
            'date': self.today.isoformat() if self.today else None,
            'positions': {
                ticker: {
                    'ts': entry_bar.ts.isoformat(),
                    'open': entry_bar.open,
                    'high': entry_bar.high,
                    'low': entry_bar.low,
                    'close': entry_bar.close,
                    'volume': entry_bar.volume,
                    'premarket_low_so_far': premarket_low,
                }
                for ticker, (entry_bar, premarket_low) in self.manual_positions.items()
            },
        }
        try:
            with open(self.manual_positions_file, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2)
        except OSError as e:
            logger.warning(f"⚠️  Could not save manual positions: {e}")

    def _load_manual_positions(self, today_et: date):
        """Restore manual positions written by an earlier run of the same session.
        Anything left over from a previous day is dropped - this strategy is
        premarket-only, so a stale position has nothing left to exit into."""
        payload = self._read_json(self.manual_positions_file, {})
        if not isinstance(payload, dict) or payload.get('date') != today_et.isoformat():
            return {}
        restored = {}
        for ticker, record in (payload.get('positions') or {}).items():
            try:
                bar = Bar(ts=datetime.fromisoformat(record['ts']), open=float(record['open']),
                          high=float(record['high']), low=float(record['low']),
                          close=float(record['close']), volume=float(record.get('volume', 0.0)))
                restored[ticker] = (bar, float(record['premarket_low_so_far']))
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"⚠️  Skipping unreadable manual position for {ticker}: {e}")
        if restored:
            logger.info(f"↩️  Restored {len(restored)} manual position(s): {', '.join(sorted(restored))}")
        return restored

    def _reset_for_new_day(self, today_et: date):
        logger.info(f"📅 New trading day: {today_et}")
        self.today = today_et
        self.open_positions = {}
        self.flatness_cache = {}
        self.decided_today = set()
        self.manual_positions = self._load_manual_positions(today_et)

    async def _send_telegram_message(self, message):
        """Send message to Telegram - mirrors premarket_top20_monitor.py's approach."""
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
            self._loop.run_until_complete(self._send_telegram_message(message))
        except Exception as e:
            logger.warning(f"⚠️  Telegram notification failed: {e}")

    # ---------------------------------------------------------------- commands

    def _drain_pending_updates(self):
        """Acknowledge whatever piled up while the daemon was down without acting on
        it. A '/b TICKER' sent hours ago refers to a price the user saw then, and
        this strategy's positions don't survive the session anyway."""
        if not self.telegram_bot:
            return
        try:
            # offset=-1 returns only the most recent update; stepping past it marks
            # the whole backlog as seen.
            updates = self._loop.run_until_complete(
                self.telegram_bot.get_updates(offset=-1, timeout=0, allowed_updates=['message']))
        except Exception as e:
            logger.warning(f"⚠️  Could not drain pending Telegram updates: {e}")
            return
        if updates:
            self._telegram_update_offset = updates[-1].update_id + 1
            logger.info(f"📭 Skipped {len(updates)} stale Telegram update(s) from before startup")

    def _poll_telegram_commands(self, timeout_seconds: int):
        """Long-poll Telegram once for user commands. Blocks up to timeout_seconds
        server-side, so callers can use it in place of a plain sleep."""
        try:
            updates = self._loop.run_until_complete(self.telegram_bot.get_updates(
                offset=self._telegram_update_offset,
                timeout=timeout_seconds,
                allowed_updates=['message'],
            ))
        except Exception as e:
            # A 409 Conflict here means something else is polling the same bot token.
            logger.warning(f"⚠️  Telegram getUpdates failed: {e}")
            time.sleep(5)  # don't hammer the API while it's unhappy
            return

        for update in updates or []:
            self._telegram_update_offset = update.update_id + 1
            message = update.message
            if not message or not message.text:
                continue
            if str(message.chat_id) != str(self.telegram_chat_id):
                logger.info(f"🚫 Ignoring message from unauthorized chat {message.chat_id}")
                continue
            logger.info(f"📱 Command: {message.text!r}")
            try:
                self._handle_command(message.text.strip())
            except Exception as e:
                logger.warning(f"⚠️  Error handling command {message.text!r}: {e}")
                self._notify(f"⚠️ Couldn't handle that command: {e}")

    def _handle_command(self, text: str):
        parts = text.split()
        if not parts:
            return
        command = parts[0].lower().split('@')[0]  # '/b@somebot' in group chats
        args = parts[1:]
        if command in ('/b', '/buy'):
            self._cmd_buy(args)
        elif command in ('/s', '/sell'):
            self._cmd_sell(args)
        elif command in ('/p', '/positions'):
            self._cmd_positions()
        elif command in ('/help', '/start'):
            self._notify(HELP_TEXT)
        # Anything else is ignored on purpose - this chat also carries alerts from
        # the other trackers, and answering their commands would just be noise.

    @staticmethod
    def _parse_ticker(raw: str):
        ticker = raw.upper().lstrip('$')
        if not ticker.isalpha() or len(ticker) > 5:
            return None
        return ticker

    def _cmd_buy(self, args):
        if not args:
            self._notify("⚠️ Usage: `/b TICKER [price]` - e.g. `/b AAPL` or `/b AAPL 12.34`")
            return
        ticker = self._parse_ticker(args[0])
        if not ticker:
            self._notify(f"⚠️ `{args[0]}` doesn't look like a ticker symbol.")
            return

        entry_price = None
        if len(args) > 1:
            try:
                entry_price = float(args[1])
            except ValueError:
                self._notify(f"⚠️ `{args[1]}` isn't a valid price.")
                return
            if entry_price <= 0:
                self._notify("⚠️ Entry price must be greater than zero.")
                return

        if ticker in self.manual_positions:
            held_bar, _ = self.manual_positions[ticker]
            self._notify(f"ℹ️ Already tracking {ticker} from ${held_bar.close:.2f}. "
                         f"Send `/s {ticker}` first if you want to re-enter at a new price.")
            return
        if ticker in self.open_positions:
            self._notify(f"ℹ️ The system is already in {ticker} - you'll get the SELL alert "
                         f"for it on the same rules.")
            return

        today_et = datetime.now(ET_TZ).date()
        bars = fetch_premarket_minute_bars(self.client, ticker, today_et)
        if not bars:
            self._notify(f"⚠️ No premarket bars for {ticker} today, so there's nothing to watch it "
                         f"against. Check the symbol, or try again once it prints.")
            return

        last_bar = bars[-1]
        if entry_price is None:
            entry_price = last_bar.close
        # Only ts and close matter downstream (check_exit skips bars at/before the
        # entry time), so a flat synthetic bar at the user's price is enough.
        entry_bar = Bar(ts=last_bar.ts, open=entry_price, high=entry_price, low=entry_price,
                        close=entry_price, volume=last_bar.volume)
        premarket_low_so_far = min(b.low for b in bars if b.ts <= entry_bar.ts)

        self.manual_positions[ticker] = (entry_bar, premarket_low_so_far)
        self._save_manual_positions()
        logger.info(f"👤 MANUAL OPEN {ticker} @ ${entry_price:.2f} "
                    f"({entry_bar.ts.strftime('%H:%M')} ET)")
        self._notify(
            f"👤 *TRACKING* [{ticker}](https://www.tradingview.com/chart/?symbol={ticker})\n"
            f"Entry: ${entry_price:.2f} @ {entry_bar.ts.strftime('%H:%M')} ET\n"
            f"Stop: premarket low ${premarket_low_so_far:.2f}\n"
            f"Watching for the sell signal on the usual rules - `/s {ticker}` to stop."
        )

    def _cmd_sell(self, args):
        if not args:
            self._notify("⚠️ Usage: `/s TICKER` - e.g. `/s AAPL`")
            return
        ticker = self._parse_ticker(args[0])
        if not ticker or ticker not in self.manual_positions:
            tracked = ', '.join(sorted(self.manual_positions)) or 'none'
            self._notify(f"⚠️ Not tracking `{args[0]}`. Currently tracking: {tracked}")
            return

        entry_bar, premarket_low_so_far = self.manual_positions[ticker]
        today_et = datetime.now(ET_TZ).date()
        bars = fetch_premarket_minute_bars(self.client, ticker, today_et)
        position, exit_info = strategy.replay_to_exit(ticker, entry_bar, premarket_low_so_far, bars)
        if exit_info is None:
            # No rule fired - close at the latest print. max() keeps the exit from
            # landing before entry when the user sells inside the same minute bar.
            last_bar = bars[-1] if bars else entry_bar
            exit_info = (max(last_bar.ts, entry_bar.ts), last_bar.close, 'MANUAL_SELL')
        self._close_manual_position(ticker, position, exit_info)

    def _cmd_positions(self):
        lines = []
        for ticker, (entry_bar, premarket_low) in sorted(self.manual_positions.items()):
            lines.append(f"👤 {ticker} @ ${entry_bar.close:.2f} "
                         f"({entry_bar.ts.strftime('%H:%M')} ET, stop ${premarket_low:.2f})")
        for ticker, (entry_bar, premarket_low) in sorted(self.open_positions.items()):
            lines.append(f"🤖 {ticker} @ ${entry_bar.close:.2f} "
                         f"({entry_bar.ts.strftime('%H:%M')} ET, stop ${premarket_low:.2f})")
        if not lines:
            self._notify("📭 No open positions right now.")
            return
        self._notify("📋 *Open positions*\n" + "\n".join(lines))

    def _close_manual_position(self, ticker, position, exit_info):
        trade = strategy.build_trade_result(position, *exit_info)
        trade['alert_type'] = 'manual'
        self.manual_trades.append(trade)
        self._save_manual_trades()
        del self.manual_positions[ticker]
        self._save_manual_positions()
        marker = '✅' if trade['profit_pct'] > 0 else '❌'
        logger.info(f"👤 MANUAL CLOSED {ticker} {marker} {trade['profit_pct']:+.1f}% "
                    f"[{trade['exit_reason']}]")
        self._notify(
            f"🔴 *SELL* 👤 [{ticker}](https://www.tradingview.com/chart/?symbol={ticker}) {marker}\n"
            f"Exit: ${trade['exit_price']:.2f} (entry ${trade['entry_price']:.2f})  "
            f"P/L: {trade['profit_pct']:+.1f}%\n"
            # exit_reason is UPPER_SNAKE_CASE - underscores break Telegram's legacy
            # Markdown parser (read as unclosed italics), so swap them for spaces.
            f"Reason: {trade['exit_reason'].replace('_', ' ')}"
        )

    # ------------------------------------------------------------------- scan

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
            if spike_bar.close >= strategy.MAX_ENTRY_PRICE:
                logger.info(f"⏭️  {ticker}: spike at ${spike_bar.close:.2f} >= "
                            f"MAX_ENTRY_PRICE ${strategy.MAX_ENTRY_PRICE}, skipping")
                continue
            if not strategy.has_sufficient_liquidity(minute_bars, spike_bar):
                logger.info(f"⏭️  {ticker}: spike found but pre-entry liquidity too thin, skipping")
                continue

            premarket_low_so_far = min(b.low for b in minute_bars if b.ts <= spike_bar.ts)
            self.open_positions[ticker] = (spike_bar, premarket_low_so_far)
            logger.info(f"📈 OPENED {ticker} @ ${spike_bar.close:.2f} ({spike_bar.ts.strftime('%H:%M')} ET)")
            self._notify(
                f"🟢 *BUY* [{ticker}](https://www.tradingview.com/chart/?symbol={ticker})\n"
                f"Entry: ${spike_bar.close:.2f} @ {spike_bar.ts.strftime('%H:%M')} ET"
            )

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
                self._notify(
                    f"🔴 *SELL* [{ticker}](https://www.tradingview.com/chart/?symbol={ticker}) {marker}\n"
                    f"Exit: ${trade['exit_price']:.2f}  P/L: {trade['profit_pct']:+.1f}% "
                    f"(${trade['profit_loss']:+.2f})\n"
                    # exit_reason is UPPER_SNAKE_CASE (e.g. RANGE_DRAWDOWN_NO_RECOVERY) -
                    # underscores break Telegram's legacy Markdown parser (read as
                    # unclosed italics), so swap them for spaces before sending.
                    f"Reason: {trade['exit_reason'].replace('_', ' ')}"
                )

        # Manual positions run through the same replay/exit path as system ones -
        # only the way they were opened differs.
        for ticker in list(self.manual_positions.keys()):
            entry_bar, premarket_low_so_far = self.manual_positions[ticker]
            bars = fetch_premarket_minute_bars(self.client, ticker, today_et)
            if not bars:
                continue
            position, exit_info = strategy.replay_to_exit(ticker, entry_bar, premarket_low_so_far, bars)
            if exit_info is not None:
                self._close_manual_position(ticker, position, exit_info)

    def _wait_for_next_scan(self):
        """Pause between scans. With Telegram configured the wait is spent
        long-polling for commands, so a /b lands within seconds instead of at the
        next scan boundary."""
        if not self.telegram_bot:
            time.sleep(SCAN_INTERVAL_SECONDS)
            return
        deadline = time.monotonic() + SCAN_INTERVAL_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining < 1:
                if remaining > 0:
                    time.sleep(remaining)
                return
            self._poll_telegram_commands(int(min(TELEGRAM_POLL_TIMEOUT_SECONDS, remaining)))

    def run(self):
        logger.info(f"🚀 flat_spike live paper trader started (data-dir={self.data_dir})")
        self._drain_pending_updates()
        while True:
            try:
                self.scan_once()
            except Exception as e:
                logger.warning(f"⚠️  Scan error: {e}")
            try:
                self._wait_for_next_scan()
            except Exception as e:
                # Never let the command listener take the trading loop down with it.
                logger.warning(f"⚠️  Command listener error: {e}")
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
