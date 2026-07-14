#!/usr/bin/env python3
"""
Premarket Top 20 Volume Monitor
Monitors the top 20 tickers by premarket volume every 1 minute.
Sends Telegram notification when ticker positions change.

Usage:
    python premarket_top20_monitor.py --bot-token YOUR_TOKEN --chat-id YOUR_CHAT_ID
"""

import json
import time
import rookiepy
import argparse
import sys
import os
import requests
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import logging
import pytz
from telegram import Bot

from tradingview_screener import Query

# Alpaca imports for real-time price/volume data
try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.historical.screener import ScreenerClient
    from alpaca.data.requests import (StockBarsRequest, StockLatestTradeRequest,
                                      MostActivesRequest, MarketMoversRequest)
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import DataFeed
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    print("⚠️  alpaca-py not installed. Run: pip install alpaca-py")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('premarket_top20_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Storage file for last known positions
POSITIONS_FILE = "premarket_top20_positions.json"

# Log directory for screener data and notifications
LOG_DIR = Path("pretop20")
LOG_DIR.mkdir(exist_ok=True)

ET_TZ = pytz.timezone('America/New_York')

# Candle-spike detection: flag a symbol when its latest 10-minute premarket
# candle range (high-low) is this many times the average range of the prior
# candles, so it can be promoted into the watch list before volume/change
# rankings would otherwise surface it.
CANDLE_SPIKE_BUCKET_MINUTES = 10
CANDLE_SPIKE_RATIO_THRESHOLD = 3.0
CANDLE_SPIKE_BASELINE_BUCKETS = 6  # up to 1 hour of prior candles
CANDLE_SPIKE_MIN_BASELINE_BUCKETS = 2  # need some history to avoid noise
CANDLE_SPIKE_MIN_BARS_IN_BUCKET = 3  # ignore just-started/mostly-empty buckets

# Alpaca screener candidate source: the TradingView scanner serves this
# account 15-minute delayed data (update_mode: delayed_streaming_900), so a
# ticker spiking now won't crack TradingView's volume/change rankings until
# ~15 minutes later. Alpaca's screener endpoints are real-time and close
# that gap by feeding extra candidates into the merge.
ALPACA_SCREENER_TOP = 50        # how many gainers/most-actives to request
ALPACA_GAINER_MIN_CHANGE = 10.0  # only take gainers up at least this %
ALPACA_MOST_ACTIVES_KEEP = 20    # most-active-by-volume symbols to keep

class PremarketTop20Monitor:
    def __init__(self, telegram_bot_token=None, telegram_chat_id=None):
        """Initialize the monitor"""
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.telegram_bot = None

        if telegram_bot_token and telegram_chat_id:
            self.telegram_bot = Bot(token=telegram_bot_token)
            logger.info("✅ Telegram bot initialized")
        else:
            logger.warning("⚠️  No Telegram credentials provided - notifications disabled")

        # Get TradingView cookies
        self.cookies = self._get_tradingview_cookies()

        # Load previous positions
        self.previous_positions = self._load_positions()

        # Top 10 "new ticker" tracking for notifications
        # Tickers that have ever been in top 10 this session (won't show number emoji again if they return)
        self.top10_ever_seen = set()
        # Consecutive appearances in top 10 (resets when ticker drops out, but ticker still remembered in ever_seen)
        self.top10_consecutive_count = {}
        # Maximum notifications to show the number emoji (1️⃣ through 5️⃣)
        self.top10_new_threshold = 5
        # Tickers that "exploded" into top 10 (appeared without being in top 20 first)
        # These keep the explosion emoji for all 5 appearances
        self.top10_exploded = set()

        # Previous volumes for calculating total volume % (volume delta share)
        self.previous_volumes = {}

        # High gainer (>40%) tracking
        # Count of notifications sent while ticker is above 40%
        self.high_gainer_notification_count = {}
        # Peak premarket_change seen while ticker is above 40%
        self.high_gainer_peak = {}

        # Alpaca price cache to avoid excessive API calls
        self.alpaca_price_cache = {}  # {symbol: {'price': float, 'volume': int, 'timestamp': datetime}}
        self.alpaca_price_cache_duration = 60  # Cache prices for 1 minute

        # Initialize Alpaca client for real-time market data
        self.alpaca_client = None
        self.alpaca_screener_client = None
        if ALPACA_AVAILABLE:
            try:
                api_key = os.environ.get('APCA_API_KEY_ID')
                api_secret = os.environ.get('APCA_API_SECRET_KEY')

                if api_key and api_secret:
                    self.alpaca_client = StockHistoricalDataClient(api_key, api_secret)
                    self.alpaca_screener_client = ScreenerClient(api_key, api_secret)
                    logger.info("✅ Alpaca market data client initialized successfully")
                else:
                    logger.warning("⚠️  Alpaca API keys not found in environment. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Alpaca client: {e}")

    def _get_tradingview_cookies(self):
        """Get TradingView cookies for API access"""
        try:
            # Get cookies from Firefox
            cookies_list = rookiepy.firefox(['.tradingview.com'])

            # Convert list of cookies to dictionary format
            cookies = {}
            if cookies_list:
                for cookie in cookies_list:
                    if isinstance(cookie, dict):
                        name = cookie.get('name')
                        value = cookie.get('value')
                        if name and value:
                            cookies[name] = value

                logger.info(f"✅ Got {len(cookies)} TradingView cookies from Firefox")
                return cookies
            else:
                logger.warning("⚠️  No TradingView cookies found - using without cookies")
                return {}
        except Exception as e:
            logger.warning(f"⚠️  Could not get cookies: {e} - using without cookies")
            return {}

    def _load_positions(self):
        """Load previous ticker positions from file"""
        if os.path.exists(POSITIONS_FILE):
            try:
                with open(POSITIONS_FILE, 'r') as f:
                    data = json.load(f)
                    logger.info(f"📁 Loaded previous positions: {len(data)} tickers")
                    return data
            except Exception as e:
                logger.error(f"❌ Error loading positions: {e}")
        return {}

    def _save_positions(self, positions):
        """Save current ticker positions to file"""
        try:
            with open(POSITIONS_FILE, 'w') as f:
                json.dump(positions, f, indent=2)
            logger.debug(f"💾 Saved {len(positions)} ticker positions")
        except Exception as e:
            logger.error(f"❌ Error saving positions: {e}")

    def _get_new_ticker_emoji(self, symbol, position):
        """
        Get the 'new ticker' emoji for tickers that are new to the top 10.

        Returns:
            str: Number emoji (1️⃣-5️⃣) if ticker is new to top 10 and within threshold,
                 with optional 💥 explosion emoji if ticker suddenly appeared (wasn't in top 20 before),
                 empty string otherwise
        """
        # Only track top 10 positions
        if position > 10:
            return ""

        # If ticker has been seen before in top 10 but dropped out, no emoji
        if symbol in self.top10_ever_seen and symbol not in self.top10_consecutive_count:
            return ""

        # Get consecutive count (0 if first time)
        count = self.top10_consecutive_count.get(symbol, 0)

        # If count exceeds threshold, no longer "new"
        if count >= self.top10_new_threshold:
            return ""

        # Map count to number emoji (count is 0-indexed, emoji is 1-indexed)
        number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        base_emoji = number_emojis[count]

        # Check if ticker suddenly appeared in top 10 (wasn't in top 20 before)
        # Show explosion emoji for all appearances if ticker "exploded" into top 10
        explosion_emoji = ""
        if symbol in self.top10_exploded:
            # Ticker previously exploded into top 10, keep showing explosion
            explosion_emoji = "💥"
        elif count == 0 and symbol not in self.previous_positions:
            # Ticker just jumped straight into top 10 without being in top 20 first
            explosion_emoji = "💥"

        return f" {explosion_emoji}{base_emoji}"

    def _get_high_gainer_info(self, symbol, pm_change):
        """
        Get tracking info for tickers above 40% change.

        Returns:
            str: Info string showing notification count and peak status,
                 empty string if ticker is not above 40%
        """
        if pm_change is None or pm_change <= 40:
            return ""

        # Get notification count (will be incremented after this notification is sent)
        # So current display is count + 1 (this is the Nth notification)
        count = self.high_gainer_notification_count.get(symbol, 0) + 1

        # Get peak value
        peak = self.high_gainer_peak.get(symbol, pm_change)

        # Check if this is a new peak or if it has already peaked
        if pm_change >= peak:
            # New peak or same as peak - no peak indicator
            return f" [#{count}]"
        else:
            # Has peaked - show peak indicator with the peak value
            return f" [#{count} 🔻{peak:.1f}%]"

    def _update_high_gainer_tracking(self, top20_data):
        """
        Update high gainer tracking after a notification is sent.

        - Increments notification count for tickers above 40%
        - Updates peak value if current change is higher
        - Removes tracking for tickers that dropped below 40%
        """
        current_high_gainers = {}

        for record in top20_data:
            symbol = record.get('name')
            pm_change = record.get('alpaca_premarket_change', record.get('premarket_change', 0))

            if symbol and pm_change and pm_change > 40:
                current_high_gainers[symbol] = pm_change

        # Update tracking for current high gainers
        for symbol, pm_change in current_high_gainers.items():
            # Increment notification count
            self.high_gainer_notification_count[symbol] = \
                self.high_gainer_notification_count.get(symbol, 0) + 1

            # Update peak if current is higher
            current_peak = self.high_gainer_peak.get(symbol, 0)
            if pm_change > current_peak:
                self.high_gainer_peak[symbol] = pm_change
                logger.debug(f"📈 {symbol} new peak: {pm_change:.2f}%")

        # Remove tracking for tickers that dropped below 40%
        symbols_to_remove = []
        for symbol in self.high_gainer_notification_count:
            if symbol not in current_high_gainers:
                symbols_to_remove.append(symbol)

        for symbol in symbols_to_remove:
            del self.high_gainer_notification_count[symbol]
            if symbol in self.high_gainer_peak:
                del self.high_gainer_peak[symbol]
            logger.debug(f"📉 {symbol} dropped below 40%, reset tracking")

    def _update_top10_tracking(self, top20_data):
        """
        Update the top 10 tracking after a notification is sent.

        - Adds new tickers to ever_seen set
        - Increments consecutive count for tickers in top 10
        - Removes tickers from consecutive_count if they dropped out of top 10
        - Tracks tickers that "exploded" into top 10 (appeared without being in top 20 first)
        """
        # Get current top 10 symbols
        current_top10 = set()
        for idx, record in enumerate(top20_data[:10], 1):
            symbol = record.get('name')
            if symbol:
                current_top10.add(symbol)

        # Remove tickers from consecutive_count if they dropped out of top 10
        dropped_tickers = set(self.top10_consecutive_count.keys()) - current_top10
        for symbol in dropped_tickers:
            del self.top10_consecutive_count[symbol]
            logger.debug(f"📉 {symbol} dropped out of top 10, resetting consecutive count")

        # Update tracking for current top 10
        for symbol in current_top10:
            if symbol not in self.top10_ever_seen:
                # First time ever in top 10
                self.top10_ever_seen.add(symbol)
                self.top10_consecutive_count[symbol] = 1
                # Check if ticker "exploded" into top 10 (wasn't in top 20 before)
                if symbol not in self.previous_positions:
                    self.top10_exploded.add(symbol)
                    logger.debug(f"💥 {symbol} EXPLODED into top 10 (wasn't in top 20 before)")
                else:
                    logger.debug(f"🆕 {symbol} is NEW to top 10 (was in top 20 before)")
            elif symbol in self.top10_consecutive_count:
                # Was in top 10 last time, increment count
                self.top10_consecutive_count[symbol] += 1
                logger.debug(f"📊 {symbol} consecutive top 10 count: {self.top10_consecutive_count[symbol]}")
            # If in ever_seen but not in consecutive_count, ticker returned after dropping out
            # Don't restart counting - they're no longer "new"

    def _get_tradingview_link(self, symbol):
        """Generate TradingView chart link for the symbol"""
        return f"https://www.tradingview.com/chart/?symbol={symbol}"

    def _fetch_query_records(self, query, label):
        """Helper to execute a query and return a list of valid records with premarket volume > 0"""
        try:
            data = query.get_scanner_data(cookies=self.cookies)

            df_data = None
            if isinstance(data, tuple) and len(data) == 2:
                _, df_data = data
            else:
                df_data = data

            if df_data is None:
                logger.error(f"❌ No data returned from {label} query")
                return []

            all_records = []
            if hasattr(df_data, 'to_dict'):
                all_records = df_data.to_dict('records')
            elif isinstance(df_data, list):
                all_records = df_data
            elif isinstance(df_data, dict):
                all_records = [df_data]
            else:
                logger.error(f"❌ Unexpected data format from {label}: {type(df_data)}")
                return []

            valid = []
            for record in all_records:
                if not isinstance(record, dict):
                    continue
                pm_volume = record.get('premarket_volume')
                if pm_volume and pm_volume > 0:
                    valid.append(record)

            logger.info(f"✅ {label}: {len(valid)} tickers with premarket volume")
            return valid
        except Exception as e:
            logger.error(f"❌ Error in {label} query: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []

    def _update_prices_with_alpaca(self, records):
        """
        Overlay real-time price/change/volume from Alpaca onto TradingView screener records.
        TradingView's screener snapshot can lag; Alpaca gives us a live quote per symbol plus
        today's actual premarket minute-bar volume. Adds 'alpaca_price', 'alpaca_previous_close',
        'alpaca_premarket_change', and 'alpaca_premarket_volume' without removing the original
        TradingView fields. Uses a short-lived cache to avoid re-fetching the same symbol within
        a scan cycle.

        Args:
            records: List of dicts from TradingView screener

        Returns:
            Updated list of records with current price/change/volume from Alpaca where available
        """
        if not self.alpaca_client:
            return records

        if not records:
            return records

        try:
            current_time = datetime.now()

            # Alpaca rejects the whole batch on TV-style class/preferred
            # symbols (e.g. DCOM/P), so only fetch plain alphabetic symbols
            all_symbols = [record['name'] for record in records
                           if record.get('name') and record['name'].isalpha()]
            symbols_to_fetch = []
            cached_count = 0

            for symbol in all_symbols:
                if symbol in self.alpaca_price_cache:
                    cache_entry = self.alpaca_price_cache[symbol]
                    cache_age = (current_time - cache_entry['timestamp']).total_seconds()
                    if cache_age < self.alpaca_price_cache_duration:
                        cached_count += 1
                        continue
                symbols_to_fetch.append(symbol)

            logger.info(f"Alpaca price update: {len(symbols_to_fetch)} to fetch, {cached_count} from cache")

            if symbols_to_fetch:
                # Latest trade for live price
                trade_request = StockLatestTradeRequest(symbol_or_symbols=symbols_to_fetch, feed=DataFeed.SIP)
                latest_trades = self.alpaca_client.get_stock_latest_trade(trade_request)

                # Daily bars to get previous close
                end_time = datetime.now()
                start_time = end_time - timedelta(days=5)  # Ensure at least 2 trading days
                daily_bars_request = StockBarsRequest(
                    symbol_or_symbols=symbols_to_fetch,
                    timeframe=TimeFrame.Day,
                    start=start_time,
                    end=end_time,
                    feed=DataFeed.SIP
                )
                daily_bars_data = self.alpaca_client.get_stock_bars(daily_bars_request)

                # Today's minute bars (extended hours) to sum actual premarket volume
                minute_start = end_time - timedelta(days=1)
                minute_bars_request = StockBarsRequest(
                    symbol_or_symbols=symbols_to_fetch,
                    timeframe=TimeFrame.Minute,
                    start=minute_start,
                    end=end_time,
                    feed=DataFeed.SIP
                )
                minute_bars_data = self.alpaca_client.get_stock_bars(minute_bars_request)

                today = end_time.date()

                for symbol in symbols_to_fetch:
                    cache_entry = {'timestamp': current_time, 'price': None, 'previous_close': None, 'premarket_volume': None}

                    if symbol in latest_trades:
                        cache_entry['price'] = float(latest_trades[symbol].price)

                    if daily_bars_data and hasattr(daily_bars_data, 'data') and symbol in daily_bars_data.data:
                        symbol_daily_bars = daily_bars_data.data[symbol]
                        if symbol_daily_bars:
                            if len(symbol_daily_bars) >= 2:
                                cache_entry['previous_close'] = float(symbol_daily_bars[-2].close)
                            elif len(symbol_daily_bars) == 1:
                                cache_entry['previous_close'] = float(symbol_daily_bars[-1].close)

                    if minute_bars_data and hasattr(minute_bars_data, 'data') and symbol in minute_bars_data.data:
                        symbol_minute_bars = minute_bars_data.data[symbol]
                        premarket_volume = 0
                        for bar in symbol_minute_bars:
                            bar_time = bar.timestamp
                            if bar_time.date() != today:
                                continue
                            # Premarket is 4:00-9:30 AM ET; Alpaca timestamps are UTC.
                            # ~9:00-14:30 UTC (EST) / 8:00-13:30 UTC (EDT) - approximate as before 14:30 UTC
                            is_premarket = (bar_time.hour < 14) or (bar_time.hour == 14 and bar_time.minute < 30)
                            if is_premarket:
                                premarket_volume += bar.volume
                        cache_entry['premarket_volume'] = premarket_volume

                    self.alpaca_price_cache[symbol] = cache_entry

            updated_count = 0
            for record in records:
                symbol = record.get('name')
                if symbol not in self.alpaca_price_cache:
                    continue

                cache_entry = self.alpaca_price_cache[symbol]

                if cache_entry['price'] is not None:
                    record['alpaca_price'] = cache_entry['price']
                    updated_count += 1

                if cache_entry['previous_close'] is not None:
                    record['alpaca_previous_close'] = cache_entry['previous_close']
                    if cache_entry['price'] is not None and cache_entry['previous_close'] > 0:
                        record['alpaca_premarket_change'] = ((cache_entry['price'] - cache_entry['previous_close']) / cache_entry['previous_close']) * 100

                if cache_entry['premarket_volume'] is not None:
                    record['alpaca_premarket_volume'] = cache_entry['premarket_volume']

            logger.info(f"✅ Updated {updated_count}/{len(records)} symbols with Alpaca prices")
            return records

        except Exception as e:
            logger.error(f"Failed to update prices with Alpaca: {e}")
            return records

    @staticmethod
    def _is_common_stock_symbol(symbol):
        """
        Filter out warrants/units/rights and share-class/preferred symbols.
        Uses the Nasdaq 5th-letter convention (W=warrant, R=rights, U=unit)
        plus rejecting dotted/non-alphabetic symbols like BRK.A.
        """
        if not symbol or not symbol.isalpha():
            return False
        if len(symbol) >= 5 and symbol[-1] in ('W', 'R', 'U'):
            return False
        return True

    def _get_alpaca_screener_candidates(self):
        """
        Fetch real-time candidate tickers from Alpaca's screener endpoints:
        top gainers by % change and most-active by volume.

        These records only carry 'name' (no TradingView premarket fields);
        the Alpaca price overlay fills in real prices/volume afterwards, and
        get_top20_by_premarket_volume backfills the premarket_* fields from
        that so the chart and notifications can render them.

        Returns:
            List of minimal record dicts, gainers first.
        """
        if not self.alpaca_screener_client:
            return []

        candidates = []
        seen = set()

        def add_symbols(symbols):
            added = 0
            for symbol in symbols:
                if symbol in seen or not self._is_common_stock_symbol(symbol):
                    continue
                seen.add(symbol)
                candidates.append({
                    'name': symbol,
                    'sector': '',
                    'exchange': '',
                    'source': 'alpaca_screener',
                })
                added += 1
            return added

        gainer_count = 0
        try:
            movers = self.alpaca_screener_client.get_market_movers(
                MarketMoversRequest(top=ALPACA_SCREENER_TOP))
            gainer_count = add_symbols(
                m.symbol for m in movers.gainers
                if (m.percent_change or 0) >= ALPACA_GAINER_MIN_CHANGE)
        except Exception as e:
            logger.warning(f"⚠️  Alpaca market-movers fetch failed: {e}")

        active_count = 0
        try:
            actives = self.alpaca_screener_client.get_most_actives(
                MostActivesRequest(by='volume', top=ALPACA_SCREENER_TOP))
            active_count = add_symbols(
                a.symbol for a in actives.most_actives[:ALPACA_MOST_ACTIVES_KEEP])
        except Exception as e:
            logger.warning(f"⚠️  Alpaca most-actives fetch failed: {e}")

        if candidates:
            logger.info(f"⚡ Alpaca screener candidates: {gainer_count} gainers, {active_count} most-active")
        return candidates

    def _detect_candle_spikes(self, symbols):
        """
        Flag symbols whose latest 10-minute premarket candle (high-low range) is
        an outlier vs. their own recent candles. This catches abnormal volatility
        expansion (e.g. a breakout starting) before it necessarily shows up as a
        top-20 ranking by volume or cumulative % change.

        Args:
            symbols: List of ticker symbols to check (a broader candidate pool,
                     not just the current merged top-20/top-gainers list)

        Returns:
            Dict {symbol: {'ratio': float, 'range': float, 'baseline_avg': float,
                            'bucket_start': datetime}} for symbols exceeding
            CANDLE_SPIKE_RATIO_THRESHOLD
        """
        if not self.alpaca_client or not symbols:
            return {}

        try:
            end_time = datetime.now()
            lookback_minutes = CANDLE_SPIKE_BUCKET_MINUTES * (CANDLE_SPIKE_BASELINE_BUCKETS + 1)
            start_time = end_time - timedelta(minutes=lookback_minutes + 30)

            bars_request = StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Minute,
                start=start_time,
                end=end_time,
                feed=DataFeed.SIP
            )
            bars_data = self.alpaca_client.get_stock_bars(bars_request)

            if not bars_data or not hasattr(bars_data, 'data'):
                return {}

            today = end_time.date()
            spikes = {}

            for symbol, bars in bars_data.data.items():
                # Bucket premarket minute bars into CANDLE_SPIKE_BUCKET_MINUTES-wide candles
                buckets = {}  # bucket_start (ET datetime) -> {'high':, 'low':, 'count':}
                for bar in bars:
                    bar_time_et = bar.timestamp.astimezone(ET_TZ)
                    if bar_time_et.date() != today:
                        continue
                    is_premarket = (bar_time_et.hour, bar_time_et.minute) < (9, 30) and bar_time_et.hour >= 4
                    if not is_premarket:
                        continue

                    bucket_minute = (bar_time_et.minute // CANDLE_SPIKE_BUCKET_MINUTES) * CANDLE_SPIKE_BUCKET_MINUTES
                    bucket_start = bar_time_et.replace(minute=bucket_minute, second=0, microsecond=0)

                    b = buckets.setdefault(bucket_start, {'high': bar.high, 'low': bar.low, 'count': 0})
                    b['high'] = max(b['high'], bar.high)
                    b['low'] = min(b['low'], bar.low)
                    b['count'] += 1

                if len(buckets) < CANDLE_SPIKE_MIN_BASELINE_BUCKETS + 1:
                    continue

                ordered_starts = sorted(buckets.keys())
                latest_start = ordered_starts[-1]
                latest = buckets[latest_start]
                if latest['count'] < CANDLE_SPIKE_MIN_BARS_IN_BUCKET:
                    continue

                baseline_starts = ordered_starts[-(CANDLE_SPIKE_BASELINE_BUCKETS + 1):-1]
                baseline_ranges = [buckets[s]['high'] - buckets[s]['low'] for s in baseline_starts if buckets[s]['count'] > 0]
                if len(baseline_ranges) < CANDLE_SPIKE_MIN_BASELINE_BUCKETS:
                    continue

                baseline_avg = sum(baseline_ranges) / len(baseline_ranges)
                latest_range = latest['high'] - latest['low']
                if baseline_avg <= 0:
                    continue

                ratio = latest_range / baseline_avg
                if ratio >= CANDLE_SPIKE_RATIO_THRESHOLD:
                    spikes[symbol] = {
                        'ratio': round(ratio, 2),
                        'range': round(latest_range, 4),
                        'baseline_avg': round(baseline_avg, 4),
                        'bucket_start': latest_start.isoformat()
                    }

            if spikes:
                summary = ', '.join(f"{s}({v['ratio']}x)" for s, v in spikes.items())
                logger.info(f"🕯️ Candle spikes detected: {summary}")

            return spikes

        except Exception as e:
            logger.error(f"Failed to detect candle spikes: {e}")
            return {}

    def get_top20_by_premarket_volume(self):
        """Get top 20 tickers by premarket volume, supplemented by top gainers to catch early movers"""
        try:
            fields = ['name', 'premarket_volume', 'premarket_change', 'close', 'sector', 'exchange']

            # Primary: top 20 by premarket volume
            volume_query = (Query()
                    .select(*fields)
                    .order_by('premarket_volume', ascending=False)
                    .limit(100))

            # Secondary: top 20 by premarket change % — captures early movers with low volume
            change_query = (Query()
                    .select(*fields)
                    .order_by('premarket_change', ascending=False)
                    .limit(100))

            logger.info("📊 Fetching premarket data from TradingView (volume + change queries)...")
            volume_records = self._fetch_query_records(volume_query, "volume-sorted")
            change_records = self._fetch_query_records(change_query, "change-sorted")

            # Merge: volume top 20 first, then append any new tickers from change top 20
            seen_symbols = set()
            merged = []

            for record in volume_records[:20]:
                symbol = record.get('name')
                if symbol and symbol not in seen_symbols:
                    seen_symbols.add(symbol)
                    merged.append(record)

            added_from_change = 0
            for record in change_records[:20]:
                symbol = record.get('name')
                if symbol and symbol not in seen_symbols:
                    seen_symbols.add(symbol)
                    merged.append(record)
                    added_from_change += 1

            if added_from_change:
                logger.info(f"📈 Added {added_from_change} early movers from change-sorted query")

            # Tertiary: real-time movers from Alpaca's screener. TradingView
            # scanner data is 15-min delayed for this account, so a spike only
            # enters its rankings ~15 minutes late (e.g. UBXG on 2026-07-14
            # spiked at 8:59 ET but ranked at 9:15 ET); Alpaca catches it live.
            alpaca_candidates = self._get_alpaca_screener_candidates()
            added_from_alpaca = 0
            for record in alpaca_candidates:
                symbol = record.get('name')
                if symbol and symbol not in seen_symbols:
                    seen_symbols.add(symbol)
                    merged.append(record)
                    added_from_alpaca += 1

            if added_from_alpaca:
                logger.info(f"⚡ Added {added_from_alpaca} real-time movers from Alpaca screener")

            # Candle-spike detection: check a broader candidate pool (not just the
            # merged top-20/top-gainers) so an abnormal 10-min range can promote a
            # ticker into the watch list before its volume/change rank would.
            record_lookup = {}
            for record in volume_records[:60] + change_records[:60] + alpaca_candidates:
                symbol = record.get('name')
                if symbol and symbol not in record_lookup:
                    record_lookup[symbol] = record

            spikes = self._detect_candle_spikes(list(record_lookup.keys()))

            added_from_spike = 0
            for symbol, spike in spikes.items():
                if symbol not in seen_symbols and symbol in record_lookup:
                    seen_symbols.add(symbol)
                    merged.append(record_lookup[symbol])
                    added_from_spike += 1

            if added_from_spike:
                logger.info(f"🕯️ Added {added_from_spike} early movers from candle-spike detection")

            # Attach spike info to every merged record that qualifies, whether it was
            # already present via volume/change or just promoted above, so the chart
            # can highlight it.
            for record in merged:
                spike = spikes.get(record.get('name'))
                if spike:
                    record['candle_spike_ratio'] = spike['ratio']
                    record['candle_spike_range'] = spike['range']
                    record['candle_spike_baseline_avg'] = spike['baseline_avg']

            logger.info(f"✅ Total merged tickers: {len(merged)}")

            # Overlay real-time price/change/volume from Alpaca
            merged = self._update_prices_with_alpaca(merged)

            # Alpaca-screener candidates carry no TradingView premarket fields;
            # fill them from the overlay so the chart (which needs numeric
            # premarket_change/premarket_volume) and notifications render them.
            # Drop candidates with no premarket activity today - the Alpaca
            # screener can return the previous session's movers early on.
            filled = []
            for record in merged:
                if record.get('source') == 'alpaca_screener':
                    if record.get('alpaca_premarket_change') is None or not record.get('alpaca_premarket_volume'):
                        continue
                if record.get('premarket_change') is None and record.get('alpaca_premarket_change') is not None:
                    record['premarket_change'] = record['alpaca_premarket_change']
                if not record.get('premarket_volume') and record.get('alpaca_premarket_volume'):
                    record['premarket_volume'] = record['alpaca_premarket_volume']
                if record.get('close') is None and record.get('alpaca_previous_close') is not None:
                    record['close'] = record['alpaca_previous_close']
                filled.append(record)
            merged = filled

            # Log the screener data to file
            if merged:
                self._log_screener_data(merged)

            return merged if merged else None

        except Exception as e:
            logger.error(f"❌ Error getting screener data: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _log_screener_data(self, screener_data):
        """Log the screener data downloaded from TradingView"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            log_file = LOG_DIR / f"screener_{timestamp}.json"

            with open(log_file, 'w') as f:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'count': len(screener_data),
                    'data': screener_data
                }, f, indent=2)

            logger.info(f"📝 Logged screener data to {log_file}")
        except Exception as e:
            logger.error(f"❌ Error logging screener data: {e}")

    def _detect_position_changes(self, current_top20):
        """
        Detect if any ticker positions have changed
        Returns (has_changed, current_positions_dict)
        """
        # Create position dictionary from current data (includes position and premarket_change)
        current_positions = {}
        for idx, record in enumerate(current_top20, 1):
            symbol = record.get('name')
            if symbol:
                current_positions[symbol] = {
                    'position': idx,
                    'premarket_change': record.get('alpaca_premarket_change', record.get('premarket_change', 0))
                }

        # If this is the first run, consider it a change
        if not self.previous_positions:
            logger.info("📌 First run - will send notification")
            return True, current_positions

        # Check if any positions changed
        has_changed = False

        # Check if order changed - handle both old format (int) and new format (dict)
        def get_position(val):
            if isinstance(val, dict):
                return val.get('position', 0)
            return val  # old format was just an integer

        prev_list = sorted(self.previous_positions.items(), key=lambda x: get_position(x[1]))
        curr_list = sorted(current_positions.items(), key=lambda x: get_position(x[1]))

        if [x[0] for x in prev_list] != [x[0] for x in curr_list]:
            has_changed = True
            logger.info("🔄 Ticker positions have changed!")
        else:
            logger.info("✅ No position changes detected")

        return has_changed, current_positions

    def _calculate_total_volume_pct(self, top20_data):
        """
        Calculate each ticker's share of total volume change across all top 20 tickers.

        For the first notification (no previous volumes), uses raw volume / total volume.
        For subsequent notifications, uses volume delta / total volume delta.

        Returns:
            dict: mapping symbol -> total volume % (float)
        """
        volume_changes = {}
        for record in top20_data:
            symbol = record.get('name')
            pm_volume = record.get('alpaca_premarket_volume', record.get('premarket_volume', 0)) or 0
            if symbol:
                if self.previous_volumes:
                    # Calculate delta from previous volume (0 if ticker is new)
                    prev_vol = self.previous_volumes.get(symbol, 0)
                    volume_changes[symbol] = pm_volume - prev_vol
                else:
                    # First notification - use raw volume
                    volume_changes[symbol] = pm_volume

        total_change = sum(volume_changes.values())
        result = {}
        for symbol, change in volume_changes.items():
            if total_change > 0:
                result[symbol] = (change / total_change) * 100
            else:
                result[symbol] = 0.0
        return result

    def _format_telegram_message(self, top20_data):
        """Format the top 20 list as a Telegram message"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Calculate total volume % for each ticker
        total_volume_pct = self._calculate_total_volume_pct(top20_data)

        message = f"🌅 PREMARKET TOP 20 BY VOLUME\n"
        message += f"📅 {timestamp}\n"
        message += f"{'='*40}\n\n"

        for idx, record in enumerate(top20_data, 1):
            symbol = record.get('name', 'N/A')
            pm_volume = record.get('alpaca_premarket_volume', record.get('premarket_volume', 0))
            pm_change = record.get('alpaca_premarket_change', record.get('premarket_change', 0))

            # Format volume with commas
            volume_str = f"{pm_volume:,.0f}" if pm_volume else "N/A"

            # Format change with + or - sign
            change_str = f"{pm_change:+.2f}%" if pm_change is not None else "N/A"

            # Create TradingView link
            tv_link = self._get_tradingview_link(symbol)

            # Get high gainer tracking info (notification count and peak status)
            high_gainer_info = self._get_high_gainer_info(symbol, pm_change)

            # Add emoji based on change - use green square for >40% changes
            if pm_change and pm_change > 40:
                emoji = "🟩"  # Green square for high gainers
                # Make the change text bold for emphasis
                change_str = f"*{change_str}*{high_gainer_info}"
            elif pm_change and pm_change > 0:
                emoji = "🟢"
            elif pm_change and pm_change < 0:
                emoji = "🔴"
            else:
                emoji = "⚪"

            # Determine position change arrow and premarket change delta
            position_arrow = ""
            pm_change_delta_str = ""

            # Helper to get position from old or new format
            def get_prev_position(val):
                if isinstance(val, dict):
                    return val.get('position', 0)
                return val  # old format was just an integer

            # Helper to get previous premarket change
            def get_prev_pm_change(val):
                if isinstance(val, dict):
                    return val.get('premarket_change', None)
                return None  # old format didn't store premarket_change

            if self.previous_positions and symbol in self.previous_positions:
                prev_data = self.previous_positions[symbol]
                prev_pos = get_prev_position(prev_data)
                prev_pm_change = get_prev_pm_change(prev_data)

                if idx < prev_pos:
                    position_arrow = " ⬆️"  # Moved up (to a better/smaller position number)
                elif idx > prev_pos:
                    position_arrow = " ⬇️"  # Moved down (to a worse/larger position number)
                # If same position, no arrow

                # Calculate premarket change delta
                if prev_pm_change is not None and pm_change is not None:
                    delta = pm_change - prev_pm_change
                    if abs(delta) >= 0.01:  # Only show if change is at least 0.01%
                        delta_emoji = "📈" if delta > 0 else "📉"
                        pm_change_delta_str = f" ({delta_emoji} {delta:+.2f}%)"
            elif self.previous_positions and symbol not in self.previous_positions:
                position_arrow = " 🆕"  # New entry to top 20

            # Get "new to top 10" emoji (1️⃣-5️⃣) for tickers newly entering top 10
            new_ticker_emoji = self._get_new_ticker_emoji(symbol, idx)

            # Get total volume % for this ticker
            tvol_pct = total_volume_pct.get(symbol, 0.0)
            tvol_str = f"{tvol_pct:.1f}%"

            # Format line with clickable link (Markdown format)
            message += f"{idx}. {emoji} [{symbol}]({tv_link}){position_arrow}{new_ticker_emoji}\n"
            message += f"   📊 Volume: {volume_str}\n"
            message += f"   📈 Change: {change_str}{pm_change_delta_str}\n"
            message += f"   🔄 Total Vol: {tvol_str}\n\n"

        message += f"{'='*40}\n"
        message += f"💡 Positions tracked every 1 minute"

        return message

    async def _send_telegram_message(self, message):
        """Send message to Telegram"""
        if not self.telegram_bot or not self.telegram_chat_id:
            logger.warning("⚠️  Telegram not configured - skipping notification")
            return

        try:
            await self.telegram_bot.send_message(
                self.telegram_chat_id,
                message,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            logger.info("✅ Telegram notification sent")
            self._log_notification(message, success=True, format='markdown')
        except Exception as e:
            logger.error(f"❌ Failed to send Telegram message: {e}")
            # Try without markdown if it fails
            try:
                # Remove markdown formatting
                plain_message = message.replace('[', '').replace(']', '').replace('(', ' (')
                await self.telegram_bot.send_message(
                    self.telegram_chat_id,
                    plain_message,
                    disable_web_page_preview=True
                )
                logger.info("✅ Telegram notification sent (plain text)")
                self._log_notification(plain_message, success=True, format='plain')
            except Exception as e2:
                logger.error(f"❌ Failed to send plain text message too: {e2}")
                self._log_notification(message, success=False, error=str(e2))

    def _log_notification(self, message, success=True, format='markdown', error=None):
        """Log the notification sent to Telegram"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            log_file = LOG_DIR / f"notification_{timestamp}.txt"

            with open(log_file, 'w') as f:
                f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                f.write(f"Success: {success}\n")
                f.write(f"Format: {format}\n")
                if error:
                    f.write(f"Error: {error}\n")
                f.write(f"\n{'='*60}\n")
                f.write(f"MESSAGE CONTENT:\n")
                f.write(f"{'='*60}\n\n")
                f.write(message)
                f.write(f"\n\n{'='*60}\n")

            logger.info(f"📝 Logged notification to {log_file}")
        except Exception as e:
            logger.error(f"❌ Error logging notification: {e}")

    def _find_new_tickers(self, current_positions):
        """Find tickers that are new to the top 20 (not in previous positions)"""
        if not self.previous_positions:
            return set(current_positions.keys())
        return set(current_positions.keys()) - set(self.previous_positions.keys())

    def run_single_scan(self):
        """Run a single scan and send notification if new tickers entered top 20"""
        logger.info("🔍 Running single scan...")

        # Get top 20 by premarket volume
        top20_data = self.get_top20_by_premarket_volume()

        if not top20_data:
            logger.error("❌ Failed to get data")
            return False

        # Detect position changes
        has_changed, current_positions = self._detect_position_changes(top20_data)

        # Check for new tickers entering the top 20
        new_tickers = self._find_new_tickers(current_positions)

        if has_changed:
            # Always update tracking and save positions when data changes
            self._update_top10_tracking(top20_data)
            self._update_high_gainer_tracking(top20_data)

            self.previous_volumes = {}
            for record in top20_data:
                symbol = record.get('name')
                pm_volume = record.get('alpaca_premarket_volume', record.get('premarket_volume', 0)) or 0
                if symbol:
                    self.previous_volumes[symbol] = pm_volume

            self._save_positions(current_positions)
            self.previous_positions = current_positions

            # Only send Telegram notification if new tickers entered top 20
            if new_tickers:
                logger.info(f"📱 New tickers in top 20: {', '.join(sorted(new_tickers))} - sending notification...")
                message = self._format_telegram_message(top20_data)

                print("\n" + "="*50)
                print(message.replace('[', '').replace(']', '').replace('(', ' ('))
                print("="*50 + "\n")

                if self.telegram_bot:
                    loop = asyncio.get_event_loop()
                    loop.run_until_complete(self._send_telegram_message(message))
            else:
                logger.info("✅ Positions changed but no new tickers - skipping Telegram notification")
        else:
            logger.info("✅ No changes - skipping notification")

        return True

    def run_continuous(self):
        """Run continuous monitoring every 1 minute"""
        logger.info("🚀 Starting continuous monitoring (every 1 minute)...")
        logger.info("Press Ctrl+C to stop")

        scan_count = 0

        try:
            while True:
                scan_count += 1
                logger.info(f"\n{'='*60}")
                logger.info(f"📊 SCAN #{scan_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"{'='*60}")

                self.run_single_scan()

                # Wait 1 minute
                logger.info("⏳ Waiting 1 minute until next scan...")
                time.sleep(60)  # 1 minute = 60 seconds

        except KeyboardInterrupt:
            logger.info("\n👋 Monitoring stopped by user")
            sys.exit(0)

def main():
    parser = argparse.ArgumentParser(
        description='Premarket Top 20 Volume Monitor',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single scan
  python premarket_top20_monitor.py --single

  # Continuous monitoring with Telegram
  python premarket_top20_monitor.py --continuous --bot-token "YOUR_TOKEN" --chat-id "YOUR_CHAT_ID"

  # Reset saved positions
  python premarket_top20_monitor.py --reset
        """
    )

    parser.add_argument('--bot-token', type=str, help='Telegram bot token')
    parser.add_argument('--chat-id', type=str, help='Telegram chat ID')
    parser.add_argument('--continuous', action='store_true', help='Run continuous monitoring')
    parser.add_argument('--single', action='store_true', help='Run single scan and exit')
    parser.add_argument('--reset', action='store_true', help='Reset saved positions and exit')

    args = parser.parse_args()

    # Handle reset
    if args.reset:
        if os.path.exists(POSITIONS_FILE):
            os.remove(POSITIONS_FILE)
            logger.info(f"✅ Removed {POSITIONS_FILE}")
        else:
            logger.info(f"ℹ️  {POSITIONS_FILE} does not exist")
        sys.exit(0)

    # Create monitor
    monitor = PremarketTop20Monitor(
        telegram_bot_token=args.bot_token,
        telegram_chat_id=args.chat_id
    )

    # Write PID to file for easy process management
    pid_file = '/tmp/premarket_top20.pid'
    try:
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"📝 PID {os.getpid()} written to {pid_file}")
    except Exception as e:
        logger.warning(f"⚠️  Could not write PID file: {e}")

    try:
        # Run based on mode
        if args.continuous:
            monitor.run_continuous()
        else:
            # Default to single scan
            monitor.run_single_scan()
    finally:
        # Clean up PID file on exit
        try:
            if os.path.exists(pid_file):
                os.remove(pid_file)
                logger.info(f"🗑️  Removed PID file {pid_file}")
        except Exception as e:
            logger.warning(f"⚠️  Could not remove PID file: {e}")

if __name__ == "__main__":
    main()
