#!/usr/bin/env python3
"""
Volume Momentum Tracker - Real-time Small Caps Monitor (LONG TRADES ONLY)
Continuously monitors small cap stocks to detect:
1. Tickers moving up in volume rankings with POSITIVE price movement (bullish volume momentum)
2. Tickers with POSITIVE price spikes (bullish price momentum)
3. Pre-market volume surges (pre-market activity)
4. POSITIVE pre-market price changes and acceleration (bullish early signals)

LONG TRADES FOCUS: Only alerts on upward price movements for bullish momentum plays.
Runs every 2 minutes and compares with previous results to spot emerging momentum plays.

NEW FEATURE: Immediate alerts for very big price spikes (15%+) bypass the 3-alert rule!

Command Line Usage:
    python volume_momentum_tracker.py [options]

    Options:
        --bot-token TOKEN           Telegram bot token for notifications
        --chat-id ID               Telegram chat ID for notifications
        --continuous              Start continuous monitoring (resets counters first)
        --reset                   Reset ticker counters and exit
        --stats                   Show ticker statistics and exit
        --single                  Run single scan and exit
        --immediate-threshold PCT Set immediate alert threshold (default: 25%)
        --help                    Show this help message

    Examples:
        # Single scan
        python volume_momentum_tracker.py --single

        # Continuous monitoring with Telegram alerts (immediate alerts for 15%+ spikes)
        python volume_momentum_tracker.py --continuous --bot-token "YOUR_TOKEN" --chat-id "YOUR_CHAT_ID"

        # Set immediate alert threshold to 20%
        python volume_momentum_tracker.py --continuous --immediate-threshold 20 --bot-token "YOUR_TOKEN" --chat-id "YOUR_CHAT_ID"

        # Reset counters
        python volume_momentum_tracker.py --reset

        # Kill running process
        kill $(cat /tmp/screener.pid)
"""

import json
import time
import rookiepy
import argparse
import sys
import os
import atexit
import requests
import re
import math
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
import logging
import pandas as pd
from collections import defaultdict

from tradingview_screener import Query

# Alpaca imports for real-time premarket data
try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest, StockLatestTradeRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import DataFeed
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    print("⚠️  alpaca-py not installed. Run: pip install alpaca-py")

try:
    from paper_trading_system import PaperTradingSystem
    PAPER_TRADING_AVAILABLE = True
except ImportError:
    logger.warning("Paper trading system not available - install required dependencies")
    PAPER_TRADING_AVAILABLE = False

try:
    from market_sentiment_scorer import MarketSentimentScorer
    MARKET_SENTIMENT_AVAILABLE = True
except ImportError:
    print("⚠️  market_sentiment_scorer not available. Position sizing recommendations disabled.")
    MARKET_SENTIMENT_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('premarket_momentum_tracker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# PID file path
PID_FILE = "/tmp/premarket_screener.pid"

def get_float_shares_value(data, key='float_shares_outstanding'):
    """
    Helper function to properly extract float shares value, handling NaN and None cases
    """
    value = data.get(key, None)
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return value
    return None

class VolumeMomentumTracker:
    def __init__(self, output_dir="premarket_momentum_data", browser="firefox", telegram_bot_token=None, telegram_chat_id=None, immediate_spike_threshold=15.0, enable_paper_trading=False):
        """
        Initialize the Volume Momentum Tracker

        Args:
            output_dir (str): Directory to save data files
            browser (str): Browser to extract cookies from
            telegram_bot_token (str): Telegram bot token for notifications
            telegram_chat_id (str): Telegram chat ID for notifications
            immediate_spike_threshold (float): Price change % that triggers immediate alerts (default: 15%)
            enable_paper_trading (bool): Enable paper trading simulation (default: False)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.browser = browser
        self.cookies = self._get_cookies()

        # Immediate spike alert threshold
        self.immediate_spike_threshold = immediate_spike_threshold

        # Initialize Telegram bot if credentials provided
        self.telegram_bot = None
        self.telegram_chat_id = telegram_chat_id
        self.telegram_last_sent = {}  # Track last notification time per ticker for rate limiting
        self.session_alert_count = {}  # Track how many alerts sent per ticker in current session
        self.disregarded_tickers = set()  # Track tickers to ignore for alerts in current session
        
        # Telegram alerts log file for end-of-day analysis
        self.telegram_alerts_log = self.output_dir / "telegram_alerts_sent.jsonl"
        self.telegram_notification_interval = 30 * 60  # 30 minutes between notifications for same ticker

        # Hourly list_flat notifications log file
        self.hourly_notifications_log = self.output_dir / "hourly_notifications.jsonl"
        self.last_hourly_list_flat = None  # Track last hourly notification time

        # News cache to avoid repeated API calls
        self.news_cache = {}
        self.news_cache_duration = 15 * 60  # Cache news for 15 minutes

        # Company name cache for better news filtering
        self.company_name_cache = {}

        # VIX cache to avoid repeated API calls
        self.vix_cache = {}
        self.vix_cache_duration = 5 * 60  # Cache VIX for 5 minutes

        # Alpaca price cache to avoid excessive API calls
        self.alpaca_price_cache = {}  # {symbol: {'price': float, 'volume': int, 'timestamp': datetime}}
        self.alpaca_price_cache_duration = 60  # Cache prices for 1 minute

        # Initialize Alpaca client for real-time market data
        self.alpaca_client = None
        if ALPACA_AVAILABLE:
            try:
                api_key = os.environ.get('APCA_API_KEY_ID')
                api_secret = os.environ.get('APCA_API_SECRET_KEY')

                if api_key and api_secret:
                    self.alpaca_client = StockHistoricalDataClient(api_key, api_secret)
                    logger.info("✅ Alpaca market data client initialized successfully")
                else:
                    logger.warning("⚠️  Alpaca API keys not found in environment. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Alpaca client: {e}")

        if telegram_bot_token and telegram_chat_id:
            try:
                import telegram
                self.telegram_bot = telegram.Bot(token=telegram_bot_token)
                self.telegram_last_sent = self._load_telegram_last_sent()
                self._start_telegram_listener()  # Start listening for user commands
                logger.info("✅ Telegram bot initialized successfully")
            except ImportError:
                logger.warning("📱 python-telegram-bot not installed. Run: pip install python-telegram-bot")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Telegram bot: {e}")

        # Initialize Market Sentiment Scorer for position sizing recommendations
        self.market_scorer = None
        if MARKET_SENTIMENT_AVAILABLE:
            try:
                self.market_scorer = MarketSentimentScorer()
                logger.info("✅ Market sentiment scorer initialized successfully")
            except Exception as e:
                logger.warning(f"⚠️  Failed to initialize market sentiment scorer: {e}")

        # Historical data storage
        self.historical_data = []
        self.previous_rankings = {}
        self.price_history = {}
        self.premarket_history = {}  # Track pre-market data

        # Flat-to-spike detection
        self.flat_period_history = {}  # Track recent price data for flat detection
        self.flat_period_window = 30 * 60  # 30 minutes for flat period detection
        self.flat_volatility_threshold = 2.5  # Max % volatility to consider "flat" (optimized based on tests)
        self.min_flat_duration = 6 * 60  # Minimum 6 minutes of flat behavior (optimized for better detection)

        # After-hours to premarket spike detection
        self.afterhours_history = {}  # Track after-hours data from previous day
        self.afterhours_volatility_threshold = 3.0  # Max % volatility to consider "flat" in after-hours
        self.min_afterhours_duration = 15 * 60  # Minimum 15 minutes of after-hours data

        # Ticker frequency tracking
        self.ticker_counters = self._load_ticker_counters()
        self.ticker_alert_history = self._load_ticker_alert_history()
        
        # NEW: Ticker cooldown system
        self.ticker_cooldowns = {}  # Track last alert time per ticker
        self.cooldown_periods = {
            'high_performer': 5 * 60,      # 5 minutes for >20% avg change
            'regular': 10 * 60,            # 10 minutes for 5-20% avg change  
            'poor_performer': 20 * 60,     # 20 minutes for <5% avg change
            'default': 10 * 60             # Default 10 minutes
        }
        
        # NEW: Sector-specific tuning
        self.sector_config = {
            'Finance': {
                'relative_volume_multiplier': 1.5,    # Higher threshold to reduce noise
                'price_change_multiplier': 1.0
            },
            'Health Technology': {
                'relative_volume_multiplier': 1.5,    # Higher threshold to reduce noise
                'price_change_multiplier': 1.0
            },
            'Technology Services': {
                'relative_volume_multiplier': 0.9,    # Lower threshold for early momentum
                'price_change_multiplier': 0.9
            },
            'Electronic Technology': {
                'relative_volume_multiplier': 0.8,    # Prioritize for high momentum
                'price_change_multiplier': 0.8
            },
            'Utilities': {
                'relative_volume_multiplier': 1.0,
                'price_change_multiplier': 1.0,
                'max_ticker_concentration': 0.3       # Max 30% of alerts from one ticker
            },
            'default': {
                'relative_volume_multiplier': 1.0,
                'price_change_multiplier': 1.0
            }
        }
        
        # NEW: Enhanced flat-to-spike threshold
        self.flat_to_spike_threshold = 10.0  # Optimized from 12.1% based on test results

        # Tracking settings
        self.monitor_interval = 120  # 2 minutes in seconds
        self.max_history = 50  # Keep last 50 data points
        
        # NEW: Paper Trading System Integration
        self.enable_paper_trading = enable_paper_trading
        self.paper_trader = None
        if self.enable_paper_trading and PAPER_TRADING_AVAILABLE:
            try:
                self.paper_trader = PaperTradingSystem(
                    initial_balance=10000,
                    position_size=100,
                    data_dir=self.output_dir / "paper_trades"
                )
                logger.info("📊 Paper trading system initialized successfully")
            except Exception as e:
                logger.error(f"❌ Failed to initialize paper trading system: {e}")
                self.enable_paper_trading = False

    def _escape_markdown(self, text):
        """
        Escape special characters that could break Telegram Markdown parsing
        
        Args:
            text (str): Text to escape
            
        Returns:
            str: Escaped text safe for Markdown
        """
        if not text:
            return ""
        
        # Characters that need escaping in Telegram Markdown
        special_chars = ['[', ']', '(', ')', '*', '_', '`', '~', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        
        escaped_text = text
        for char in special_chars:
            escaped_text = escaped_text.replace(char, f'\\{char}')
        
        return escaped_text

    def _format_time_ago(self, published_date):
        """
        Format the time difference between now and published date in a readable format

        Args:
            published_date (datetime): The publication date

        Returns:
            str: Formatted time difference (e.g., "2h ago", "1d ago", "3m ago")
        """
        if not published_date:
            return "Unknown"

        try:
            now = datetime.now()
            # If published_date is timezone-aware, make now timezone-aware too
            if published_date.tzinfo is not None:
                from datetime import timezone
                now = now.replace(tzinfo=timezone.utc)

            diff = now - published_date

            # Calculate different time units
            total_seconds = int(diff.total_seconds())
            minutes = total_seconds // 60
            hours = minutes // 60
            days = hours // 24

            if days > 0:
                return f"{days}d ago"
            elif hours > 0:
                return f"{hours}h ago"
            elif minutes > 0:
                return f"{minutes}m ago"
            else:
                return "Just now"

        except Exception as e:
            logger.debug(f"Error formatting time difference: {e}")
            return "Unknown"

    def _get_company_name(self, ticker):
        """
        Get company name for a ticker symbol to improve news filtering
        Uses free sources with caching
        """
        ticker_upper = ticker.upper()
        
        # Check cache first
        if ticker_upper in self.company_name_cache:
            return self.company_name_cache[ticker_upper]
        
        company_name = None
        
        try:
            # Method 1: Try Yahoo Finance for company name (free)
            url = f"https://finance.yahoo.com/quote/{ticker_upper}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                # Look for company name in the page
                import re
                # Try to find the company name in the title or h1 tags
                name_patterns = [
                    r'<title>([^(]+)\s*\([^)]*\)\s*Stock Price',
                    r'<h1[^>]*>([^(]+)\s*\([^)]*\)',
                    r'"shortName":"([^"]+)"',
                    r'"longName":"([^"]+)"'
                ]
                
                for pattern in name_patterns:
                    match = re.search(pattern, response.text)
                    if match:
                        company_name = match.group(1).strip()
                        break
                
                # Clean up common suffixes
                if company_name:
                    company_name = re.sub(r'\s+(Inc|Corp|Corporation|Ltd|Limited|Co|Company|Group|Holdings|Technologies|Systems|Solutions|Services|Enterprises|International)(\.)?$', '', company_name, flags=re.IGNORECASE)
                    company_name = company_name.strip()
        
        except Exception as e:
            logger.debug(f"Error fetching company name for {ticker}: {e}")
        
        # Fallback: use ticker as company name
        if not company_name:
            company_name = ticker_upper
        
        # Cache the result
        self.company_name_cache[ticker_upper] = company_name
        logger.debug(f"Company name for {ticker}: {company_name}")
        
        return company_name
    
    def _create_search_keywords(self, ticker):
        """
        Create comprehensive search keywords for news filtering
        """
        ticker_upper = ticker.upper()
        company_name = self._get_company_name(ticker)
        
        keywords = [
            ticker_upper,
            ticker.lower(),
            'stock',
            'shares',
            'trading',
            'earnings',
            'revenue',
            'quarterly',
            'financial',
            'announcement',
            'results',
            'guidance',
            'outlook'
        ]
        
        # Add company name variations
        if company_name and company_name != ticker_upper:
            keywords.extend([
                company_name.lower(),
                company_name.upper(),
                company_name.title()
            ])
            
            # Add partial company name matches (for multi-word company names)
            name_words = company_name.split()
            if len(name_words) > 1:
                # Add individual words that are longer than 3 characters
                for word in name_words:
                    if len(word) > 3:
                        keywords.extend([word.lower(), word.upper(), word.title()])
        
        return list(set(keywords))  # Remove duplicates
    
    def _is_relevant_news(self, title, ticker, keywords=None):
        """
        Improved relevance checking for news articles
        """
        if not keywords:
            keywords = self._create_search_keywords(ticker)
        
        title_lower = title.lower()
        
        # Check for exact ticker match (high relevance)
        if ticker.upper() in title.upper() or ticker.lower() in title_lower:
            return True
        
        # Check for company name match (high relevance)
        company_name = self._get_company_name(ticker)
        if company_name and company_name != ticker.upper():
            if company_name.lower() in title_lower:
                return True
            
            # Check partial company name matches
            name_words = company_name.split()
            if len(name_words) > 1:
                matches = sum(1 for word in name_words if len(word) > 3 and word.lower() in title_lower)
                if matches >= len(name_words) // 2:  # At least half the words match
                    return True
        
        # Check for financial keywords (medium relevance)
        financial_keywords = ['stock', 'shares', 'earnings', 'revenue', 'financial', 'quarterly']
        if any(keyword in title_lower for keyword in financial_keywords):
            return True
        
        # Check for general business keywords (lower relevance)
        business_keywords = ['trading', 'announcement', 'results', 'guidance', 'outlook']
        if any(keyword in title_lower for keyword in business_keywords):
            return True
        
        return False
    
    def _parse_date_with_fallbacks(self, date_string, ticker):
        """
        Improved date parsing with multiple fallback methods
        """
        if not date_string:
            return datetime.now() - timedelta(hours=1)
        
        date_string = date_string.strip()
        
        # List of parsing methods to try
        parsing_methods = [
            # Method 1: RFC 2822 format (most RSS feeds)
            lambda ds: parsedate_to_datetime(ds),
            
            # Method 2: ISO format with Z
            lambda ds: datetime.fromisoformat(ds.replace('Z', '+00:00')) if 'T' in ds else None,
            
            # Method 3: ISO format without timezone
            lambda ds: datetime.fromisoformat(ds) if 'T' in ds else None,
            
            # Method 4: Common formats
            lambda ds: datetime.strptime(ds, '%Y-%m-%d %H:%M:%S'),
            lambda ds: datetime.strptime(ds, '%Y-%m-%d'),
            lambda ds: datetime.strptime(ds, '%d %b %Y %H:%M:%S'),
            lambda ds: datetime.strptime(ds, '%d %b %Y'),
            lambda ds: datetime.strptime(ds, '%B %d, %Y'),
            lambda ds: datetime.strptime(ds, '%b %d, %Y'),
            
            # Method 5: Parse relative times ("2 hours ago", "1 day ago")
            lambda ds: self._parse_relative_time(ds),
        ]
        
        for i, parse_method in enumerate(parsing_methods):
            try:
                result = parse_method(date_string)
                if result:
                    logger.debug(f"Date parsing method {i+1} succeeded for {ticker}: {result}")
                    return result
            except Exception as e:
                logger.debug(f"Date parsing method {i+1} failed for {ticker}: {e}")
                continue
        
        # If all parsing fails, return a recent time
        logger.debug(f"All date parsing methods failed for {ticker}, using fallback")
        return datetime.now() - timedelta(hours=1)
    
    def _parse_relative_time(self, time_string):
        """
        Parse relative time strings like "2 hours ago", "1 day ago"
        """
        import re
        
        time_string = time_string.lower().strip()
        
        # Pattern for "X time_unit ago"
        patterns = [
            (r'(\d+)\s*h(?:our)?s?\s*ago', 'hours'),
            (r'(\d+)\s*m(?:in(?:ute)?)?s?\s*ago', 'minutes'),
            (r'(\d+)\s*d(?:ay)?s?\s*ago', 'days'),
            (r'(\d+)\s*w(?:eek)?s?\s*ago', 'weeks'),
            (r'(\d+)\s*mo(?:nth)?s?\s*ago', 'months'),
        ]
        
        for pattern, unit in patterns:
            match = re.search(pattern, time_string)
            if match:
                value = int(match.group(1))
                if unit == 'hours':
                    return datetime.now() - timedelta(hours=value)
                elif unit == 'minutes':
                    return datetime.now() - timedelta(minutes=value)
                elif unit == 'days':
                    return datetime.now() - timedelta(days=value)
                elif unit == 'weeks':
                    return datetime.now() - timedelta(weeks=value)
                elif unit == 'months':
                    return datetime.now() - timedelta(days=value * 30)
        
        return None

    def _get_vix_data(self):
        """
        Get current VIX value and past week trend using Alpaca
        Caches result for 5 minutes to avoid excessive API calls

        Returns:
            dict: {
                'current': float,  # Current VIX value
                'week_change': float,  # % change from 1 week ago
                'week_trend': str,  # 'rising' or 'falling'
                'level': str  # 'low', 'moderate', 'elevated', 'high'
            }
        """
        # Check cache first
        current_time = datetime.now()
        if 'vix_data' in self.vix_cache and 'timestamp' in self.vix_cache:
            cache_age = (current_time - self.vix_cache['timestamp']).total_seconds()
            if cache_age < self.vix_cache_duration:
                logger.debug(f"Using cached VIX data (age: {cache_age:.0f}s)")
                return self.vix_cache['vix_data']

        if not self.alpaca_client:
            logger.warning("Alpaca client not available for VIX data")
            return None

        try:
            # Fetch VIX data using Alpaca
            # Note: Alpaca uses "VIXY" ETF as VIX proxy, or we can use SPY VIX
            # For actual VIX, we'll use the CBOE VIX Index through Alpaca
            end_date = datetime.now()
            start_date = end_date - timedelta(days=10)  # Extra days to ensure we get 7 trading days

            request_params = StockBarsRequest(
                symbol_or_symbols=["VIXY"],  # VIX ETF proxy
                timeframe=TimeFrame.Day,
                start=start_date,
                end=end_date,
                feed=DataFeed.IEX  # Use IEX feed (free tier)
            )

            bars = self.alpaca_client.get_stock_bars(request_params)

            if not bars or "VIXY" not in bars:
                logger.warning("No VIX proxy data available from Alpaca")
                return None

            vixy_bars = bars["VIXY"]
            if len(vixy_bars) < 2:
                logger.warning("Insufficient VIX proxy data")
                return None

            # Get current value (most recent close)
            current_vix = float(vixy_bars[-1].close)

            # Get value from approximately 1 week ago
            week_ago_idx = max(0, len(vixy_bars) - 6)  # ~5 trading days
            week_ago_vix = float(vixy_bars[week_ago_idx].close)

            # Calculate week change
            week_change = ((current_vix - week_ago_vix) / week_ago_vix) * 100
            week_trend = 'rising' if week_change > 0 else 'falling'

            # Determine VIX level category (adjusted for VIXY ETF values)
            # VIXY trades at different levels than VIX index
            if current_vix < 10:
                level = 'low'
            elif current_vix < 15:
                level = 'moderate'
            elif current_vix < 25:
                level = 'elevated'
            else:
                level = 'high'

            vix_data = {
                'current': current_vix,
                'week_change': week_change,
                'week_trend': week_trend,
                'level': level
            }

            # Cache the result
            self.vix_cache = {
                'vix_data': vix_data,
                'timestamp': current_time
            }

            logger.info(f"VIX (VIXY): {current_vix:.2f} ({week_trend} {week_change:+.1f}% this week, {level} volatility)")
            return vix_data

        except Exception as e:
            logger.error(f"Failed to fetch VIX data from Alpaca: {e}")
            return None

    def _calculate_premarket_relative_volume(self, symbols):
        """
        Calculate premarket relative volume for symbols by comparing current premarket volume
        to average premarket volume over the past 10 trading days.

        Args:
            symbols: List of stock symbols to calculate for

        Returns:
            Dict mapping symbol to premarket relative volume
        """
        if not self.alpaca_client or not symbols:
            return {}

        try:
            # Fetch 15 calendar days of minute bars to get ~10 trading days
            end_time = datetime.now()
            start_time = end_time - timedelta(days=15)

            # Request minute bars with extended hours to get premarket data
            bars_request = StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Minute,
                start=start_time,
                end=end_time,
                feed=DataFeed.IEX
            )

            logger.info(f"Fetching premarket historical data for {len(symbols)} symbols...")
            bars_data = self.alpaca_client.get_stock_bars(bars_request)

            premarket_rel_vol = {}

            for symbol in symbols:
                if symbol not in bars_data:
                    continue

                symbol_bars = bars_data[symbol]
                if not symbol_bars:
                    continue

                # Group bars by date and calculate premarket volume for each day
                daily_premarket_volumes = {}
                today_premarket_volume = 0
                today = end_time.date()

                for bar in symbol_bars:
                    bar_time = bar.timestamp
                    bar_date = bar_time.date()
                    bar_hour = bar_time.hour
                    bar_minute = bar_time.minute

                    # Premarket is 4:00 AM - 9:30 AM ET
                    # Note: Alpaca returns times in UTC, so we need to account for timezone
                    # For EST/EDT: premarket is roughly 9:00-14:30 UTC (EST) or 8:00-13:30 UTC (EDT)
                    # Simplified: check if it's before market open (typically before 14:30 UTC)
                    is_premarket = (bar_hour < 14) or (bar_hour == 14 and bar_minute < 30)

                    if is_premarket:
                        if bar_date == today:
                            today_premarket_volume += bar.volume
                        else:
                            if bar_date not in daily_premarket_volumes:
                                daily_premarket_volumes[bar_date] = 0
                            daily_premarket_volumes[bar_date] += bar.volume

                # Calculate average premarket volume (excluding today)
                if daily_premarket_volumes:
                    avg_premarket_volume = sum(daily_premarket_volumes.values()) / len(daily_premarket_volumes)

                    # Calculate relative volume
                    if avg_premarket_volume > 0 and today_premarket_volume > 0:
                        rel_vol = today_premarket_volume / avg_premarket_volume
                        premarket_rel_vol[symbol] = rel_vol
                        logger.debug(f"{symbol}: PM Vol {today_premarket_volume:,} / Avg {avg_premarket_volume:,.0f} = {rel_vol:.1f}x")

            logger.info(f"Calculated premarket relative volume for {len(premarket_rel_vol)} symbols")
            return premarket_rel_vol

        except Exception as e:
            logger.error(f"Failed to calculate premarket relative volume: {e}")
            return {}

    def _detect_afterhours_flat_period(self, ticker):
        """
        Detect if a ticker was in a flat period during after-hours the previous day,
        then spiked in premarket.

        Args:
            ticker: Stock symbol to analyze

        Returns:
            dict with keys:
                'was_flat_afterhours': bool,
                'afterhours_volatility': float,
                'afterhours_duration_minutes': int,
                'afterhours_avg_price': float,
                'afterhours_price_range': tuple,
                'premarket_spike_from_ah': float (percentage spike from after-hours avg)
        """
        if not self.alpaca_client:
            return {
                'was_flat_afterhours': False,
                'afterhours_volatility': 0,
                'afterhours_duration_minutes': 0,
                'afterhours_avg_price': 0,
                'afterhours_price_range': (0, 0),
                'premarket_spike_from_ah': 0,
                'reason': 'no_alpaca_client'
            }

        try:
            # Fetch minute bars from yesterday and today with extended hours
            end_time = datetime.now()
            start_time = end_time - timedelta(days=2)  # Get 2 days to ensure we have yesterday

            bars_request = StockBarsRequest(
                symbol_or_symbols=[ticker],
                timeframe=TimeFrame.Minute,
                start=start_time,
                end=end_time,
                feed=DataFeed.IEX
            )

            bars_data = self.alpaca_client.get_stock_bars(bars_request)

            if ticker not in bars_data:
                return {
                    'was_flat_afterhours': False,
                    'afterhours_volatility': 0,
                    'afterhours_duration_minutes': 0,
                    'afterhours_avg_price': 0,
                    'afterhours_price_range': (0, 0),
                    'premarket_spike_from_ah': 0,
                    'reason': 'no_data'
                }

            symbol_bars = bars_data[ticker]
            if not symbol_bars:
                return {
                    'was_flat_afterhours': False,
                    'afterhours_volatility': 0,
                    'afterhours_duration_minutes': 0,
                    'afterhours_avg_price': 0,
                    'afterhours_price_range': (0, 0),
                    'premarket_spike_from_ah': 0,
                    'reason': 'no_bars'
                }

            # Separate after-hours (previous day) and premarket (today) data
            today = end_time.date()
            yesterday = today - timedelta(days=1)

            afterhours_prices = []
            premarket_prices = []

            for bar in symbol_bars:
                bar_time = bar.timestamp
                bar_date = bar_time.date()
                bar_hour = bar_time.hour
                bar_minute = bar_time.minute

                # After-hours is 4:00 PM - 8:00 PM ET (20:00-00:00 UTC for EST, 19:00-23:00 for EDT)
                # Market close: 4:00 PM ET = 21:00 UTC (EST) or 20:00 UTC (EDT)
                # After-hours end: 8:00 PM ET = 01:00 UTC next day (EST) or 00:00 UTC (EDT)
                is_afterhours = (bar_hour >= 20 or bar_hour == 0) and bar_date >= yesterday - timedelta(days=1)

                # Premarket is 4:00 AM - 9:30 AM ET (9:00-14:30 UTC for EST, 8:00-13:30 for EDT)
                is_premarket = (bar_hour < 14) or (bar_hour == 14 and bar_minute < 30)

                if is_afterhours and bar_date >= yesterday and bar_date < today:
                    afterhours_prices.append(float(bar.close))
                elif is_premarket and bar_date == today:
                    premarket_prices.append(float(bar.close))

            # Need sufficient after-hours data
            if len(afterhours_prices) < 5:  # At least 5 minutes of data
                return {
                    'was_flat_afterhours': False,
                    'afterhours_volatility': 0,
                    'afterhours_duration_minutes': 0,
                    'afterhours_avg_price': 0,
                    'afterhours_price_range': (0, 0),
                    'premarket_spike_from_ah': 0,
                    'reason': f'insufficient_ah_data_{len(afterhours_prices)}_bars'
                }

            # Calculate after-hours statistics
            ah_avg_price = sum(afterhours_prices) / len(afterhours_prices)
            ah_min_price = min(afterhours_prices)
            ah_max_price = max(afterhours_prices)
            ah_price_range = ah_max_price - ah_min_price

            # Calculate volatility as percentage of average price
            if ah_avg_price > 0:
                ah_volatility = (ah_price_range / ah_avg_price) * 100
            else:
                ah_volatility = 0

            # Duration in minutes
            ah_duration_minutes = len(afterhours_prices)

            # Determine if after-hours was "flat"
            was_flat_afterhours = (
                ah_volatility <= self.afterhours_volatility_threshold and
                ah_duration_minutes >= (self.min_afterhours_duration / 60)
            )

            # Calculate premarket spike from after-hours average
            premarket_spike_from_ah = 0
            if premarket_prices and ah_avg_price > 0:
                current_pm_price = premarket_prices[-1]  # Most recent premarket price
                premarket_spike_from_ah = ((current_pm_price - ah_avg_price) / ah_avg_price) * 100

            result = {
                'was_flat_afterhours': was_flat_afterhours,
                'afterhours_volatility': ah_volatility,
                'afterhours_duration_minutes': ah_duration_minutes,
                'afterhours_avg_price': ah_avg_price,
                'afterhours_price_range': (ah_min_price, ah_max_price),
                'premarket_spike_from_ah': premarket_spike_from_ah,
                'reason': 'flat_detected' if was_flat_afterhours else f'volatility_{ah_volatility:.1f}%'
            }

            # Cache the result for this ticker (valid for current day only)
            cache_key = f"{ticker}_{today}"
            self.afterhours_history[cache_key] = {
                'data': result,
                'timestamp': datetime.now()
            }

            logger.debug(f"{ticker} AH Analysis: Flat={was_flat_afterhours}, Vol={ah_volatility:.1f}%, PM Spike={premarket_spike_from_ah:+.1f}%")

            return result

        except Exception as e:
            logger.error(f"Failed to detect after-hours flat period for {ticker}: {e}")
            return {
                'was_flat_afterhours': False,
                'afterhours_volatility': 0,
                'afterhours_duration_minutes': 0,
                'afterhours_avg_price': 0,
                'afterhours_price_range': (0, 0),
                'premarket_spike_from_ah': 0,
                'reason': f'error_{str(e)}'
            }

    def _update_prices_with_alpaca(self, records):
        """
        Update close price and volume in records using Alpaca latest trade data.
        This ensures we get real-time prices regardless of market hours.
        Uses caching to reduce API calls.

        Args:
            records: List of dicts from TradingView screener

        Returns:
            Updated list of records with current prices from Alpaca
        """
        if not self.alpaca_client:
            logger.warning("Alpaca client not available - using TradingView prices only")
            return records

        if not records:
            return records

        try:
            current_time = datetime.now()

            # Extract all symbols and check which need updating
            all_symbols = [record['name'] for record in records]
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

            logger.info(f"Updating prices: {len(symbols_to_fetch)} to fetch, {cached_count} from cache")

            # Fetch from Alpaca only for symbols that need updating
            if symbols_to_fetch:
                # Fetch latest trades for symbols in batch
                request_params = StockLatestTradeRequest(symbol_or_symbols=symbols_to_fetch)
                latest_trades = self.alpaca_client.get_stock_latest_trade(request_params)

                # Also fetch recent bars to get volume data and previous close
                end_time = datetime.now()
                start_time = end_time - timedelta(days=5)  # Get 5 days to ensure we have at least 2 trading days

                bars_request = StockBarsRequest(
                    symbol_or_symbols=symbols_to_fetch,
                    timeframe=TimeFrame.Day,
                    start=start_time,
                    end=end_time,
                    feed=DataFeed.IEX
                )
                bars_data = self.alpaca_client.get_stock_bars(bars_request)

                # Update cache with new data
                for symbol in symbols_to_fetch:
                    cache_entry = {'timestamp': current_time, 'price': None, 'volume': None, 'previous_close': None}

                    if symbol in latest_trades:
                        cache_entry['price'] = float(latest_trades[symbol].price)

                    # Access bars via .data attribute of BarSet
                    if bars_data and hasattr(bars_data, 'data') and symbol in bars_data.data:
                        symbol_bars = bars_data.data[symbol]
                        if symbol_bars:
                            cache_entry['volume'] = int(symbol_bars[-1].volume)
                            # Get previous day's close (includes after-market)
                            if len(symbol_bars) >= 2:
                                cache_entry['previous_close'] = float(symbol_bars[-2].close)
                            elif len(symbol_bars) == 1:
                                # If only one bar, use it as previous close
                                cache_entry['previous_close'] = float(symbol_bars[-1].close)

                    self.alpaca_price_cache[symbol] = cache_entry

            # Update records with cached/fresh Alpaca data
            updated_count = 0
            for record in records:
                symbol = record['name']

                if symbol in self.alpaca_price_cache:
                    cache_entry = self.alpaca_price_cache[symbol]

                    # Save Alpaca price as a separate field (preserve TradingView close)
                    if cache_entry['price'] is not None:
                        tradingview_close = record.get('close', 0)
                        record['alpaca_price'] = cache_entry['price']

                        # Log significant price differences between TradingView and Alpaca
                        if tradingview_close > 0:
                            price_diff_pct = ((record['alpaca_price'] - tradingview_close) / tradingview_close) * 100
                            if abs(price_diff_pct) > 1:
                                logger.debug(f"{symbol}: TradingView {tradingview_close:.2f} vs Alpaca {record['alpaca_price']:.2f} ({price_diff_pct:+.1f}%)")

                        updated_count += 1

                    # Save Alpaca volume as a separate field
                    if cache_entry['volume'] is not None:
                        record['alpaca_volume'] = cache_entry['volume']

                    # Save Alpaca previous close as a separate field and calculate change
                    if cache_entry['previous_close'] is not None:
                        record['alpaca_previous_close'] = cache_entry['previous_close']
                        # Calculate change from previous close using Alpaca data
                        if cache_entry['price'] is not None and cache_entry['previous_close'] > 0:
                            change_from_prev = ((cache_entry['price'] - cache_entry['previous_close']) / cache_entry['previous_close']) * 100
                            record['change_from_prev_close'] = change_from_prev

            logger.info(f"✅ Updated {updated_count}/{len(records)} symbols with Alpaca prices")

            # Calculate premarket relative volume for all symbols
            premarket_rel_vol = self._calculate_premarket_relative_volume(all_symbols)

            # Add premarket relative volume to records
            for record in records:
                symbol = record['name']
                if symbol in premarket_rel_vol:
                    record['premarket_relative_volume'] = premarket_rel_vol[symbol]

            return records

        except Exception as e:
            logger.error(f"Failed to update prices with Alpaca: {e}")
            # Return original records if update fails
            return records

    def _get_recent_news(self, ticker, max_headlines=3):
        """
        Get recent news headlines for a ticker (within last 3 days)

        Args:
            ticker (str): Stock ticker symbol
            max_headlines (int): Maximum number of headlines to return

        Returns:
            list: List of dictionaries with 'title', 'url', 'published_date', and 'time_ago' keys
        """
        # Check cache first
        cache_key = ticker.upper()
        current_time = datetime.now()

        if cache_key in self.news_cache:
            cached_data = self.news_cache[cache_key]
            cache_time = datetime.fromisoformat(cached_data['timestamp'])
            if (current_time - cache_time).total_seconds() < self.news_cache_duration:
                logger.debug(f"Using cached news for {ticker}")
                # Refresh time_ago for cached items
                for headline in cached_data['headlines']:
                    if headline.get('published_date'):
                        try:
                            pub_date = datetime.fromisoformat(headline['published_date'])
                            headline['time_ago'] = self._format_time_ago(pub_date)
                        except:
                            headline['time_ago'] = "Unknown"
                return cached_data['headlines']

        headlines = []

        try:
            # Method 1: Try free news APIs first
            logger.debug(f"Trying free news APIs for {ticker}...")
            headlines = self._search_free_news_api(ticker, max_headlines)
            
            # Method 2: If free APIs fail, try Google News search
            if not headlines:
                logger.debug(f"Free APIs failed, trying Google News for {ticker}...")
                headlines = self._search_google_news(ticker, max_headlines)

            # Method 3: If Google News fails or gives no timestamps, try Bing News
            if not headlines or all(h.get('published_date') is None for h in headlines):
                logger.debug(f"Google News failed or no timestamps, trying Bing for {ticker}...")
                bing_headlines = self._search_bing_news(ticker, max_headlines)
                if bing_headlines:
                    headlines = bing_headlines

            # Method 4: If both fail, try Yahoo Finance
            if not headlines or all(h.get('published_date') is None for h in headlines):
                logger.debug(f"Previous methods failed, trying Yahoo Finance for {ticker}...")
                yahoo_headlines = self._search_yahoo_finance_news(ticker, max_headlines)
                if yahoo_headlines:
                    headlines = yahoo_headlines

            # Method 5: Fallback - try a simple web search for recent news
            if not headlines:
                logger.debug(f"All standard methods failed, trying fallback search for {ticker}...")
                headlines = self._fallback_news_search(ticker, max_headlines)

            # Method 6: If still no headlines, create a default "no news found" entry
            if not headlines:
                logger.debug(f"No news found anywhere for {ticker}")
                headlines = [{
                    'title': f'No recent news found for {ticker}',
                    'url': f'https://www.google.com/search?q={ticker}+stock+news',
                    'published_date': None,
                    'source': 'Search Fallback',
                    'time_ago': 'No news found'
                }]

            # Add time_ago formatting for all headlines and ensure timestamps
            for i, headline in enumerate(headlines):
                if headline.get('published_date'):
                    try:
                        if isinstance(headline['published_date'], str):
                            pub_date = datetime.fromisoformat(headline['published_date'])
                        else:
                            pub_date = headline['published_date']
                        headline['time_ago'] = self._format_time_ago(pub_date)
                    except Exception as time_error:
                        logger.debug(f"Error formatting time for {ticker}: {time_error}")
                        # Assign graduated fallback times based on order
                        fallback_hours = (i + 1) * 2  # 2h, 4h, 6h ago
                        fallback_date = datetime.now() - timedelta(hours=fallback_hours)
                        headline['published_date'] = fallback_date.isoformat()
                        headline['time_ago'] = self._format_time_ago(fallback_date)
                else:
                    # Assign default timestamps based on position
                    fallback_hours = (i + 1) * 3  # 3h, 6h, 9h ago
                    fallback_date = datetime.now() - timedelta(hours=fallback_hours)
                    headline['published_date'] = fallback_date.isoformat()
                    headline['time_ago'] = self._format_time_ago(fallback_date)
                    logger.debug(f"Assigned fallback timestamp for {ticker}: {headline['time_ago']}")

            # Cache the results
            self.news_cache[cache_key] = {
                'timestamp': current_time.isoformat(),
                'headlines': headlines
            }

            logger.info(f"Found {len(headlines)} news headlines for {ticker} with timestamps")

        except Exception as e:
            logger.error(f"Error fetching news for {ticker}: {e}")
            # Create emergency fallback
            headlines = [{
                'title': f'Error fetching news for {ticker}',
                'url': f'https://www.google.com/search?q={ticker}+stock+news',
                'published_date': (datetime.now() - timedelta(hours=1)).isoformat(),
                'source': 'Error Fallback',
                'time_ago': '1h ago'
            }]

        return headlines

    def _fallback_news_search(self, ticker, max_headlines=3):
        """Fallback news search method using general web search"""
        headlines = []

        try:
            # Try a general Google search for recent stock news
            search_url = f"https://www.google.com/search?q={ticker}+stock+news+site:finance.yahoo.com+OR+site:marketwatch.com+OR+site:reuters.com&tbm=nws"

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }

            response = requests.get(search_url, headers=headers, timeout=10)
            response.raise_for_status()

            content = response.text

            # Look for Google search result patterns
            result_pattern = r'<h3[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>'
            matches = re.findall(result_pattern, content, re.DOTALL)

            current_time = datetime.now()

            for i, (url, title) in enumerate(matches[:max_headlines]):
                if len(headlines) >= max_headlines:
                    break

                # Clean up title
                title = re.sub(r'<[^>]*>', '', title).strip()

                if self._is_relevant_news(title, ticker):
                    # Assign staggered recent times
                    pub_time = current_time - timedelta(hours=i+1)

                    headlines.append({
                        'title': title[:100] + '...' if len(title) > 100 else title,
                        'url': url,
                        'published_date': pub_time.isoformat(),
                        'source': 'Google Search'
                    })

            logger.debug(f"Fallback search found {len(headlines)} headlines for {ticker}")

        except Exception as e:
            logger.debug(f"Fallback news search failed for {ticker}: {e}")

        return headlines

    def _search_free_news_api(self, ticker, max_headlines=3):
        """
        Try to get news from free APIs before falling back to web scraping
        """
        headlines = []
        
        # Try Financial Modeling Prep (free tier - no API key needed for some endpoints)
        try:
            url = f"https://financialmodelingprep.com/api/v3/stock_news?tickers={ticker}&limit={max_headlines}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    for item in data[:max_headlines]:
                        if isinstance(item, dict) and 'title' in item and 'url' in item:
                            # Parse the date
                            pub_date = None
                            if 'publishedDate' in item:
                                pub_date = self._parse_date_with_fallbacks(item['publishedDate'], ticker)
                            
                            headlines.append({
                                'title': item['title'][:100] + '...' if len(item['title']) > 100 else item['title'],
                                'url': item['url'],
                                'published_date': pub_date.isoformat() if pub_date else None,
                                'source': 'Financial Modeling Prep'
                            })
                            
                            if len(headlines) >= max_headlines:
                                break
        except Exception as e:
            logger.debug(f"Financial Modeling Prep API failed for {ticker}: {e}")
        
        if headlines:
            logger.debug(f"Free API found {len(headlines)} headlines for {ticker}")
            return headlines
        
        # Try a simple web search for recent stock news
        try:
            search_query = f"{ticker} stock news recent"
            url = f"https://www.google.com/search?q={search_query}&tbm=nws&num=10"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                import re
                # Look for news article patterns
                patterns = [
                    r'<h3[^>]*><a[^>]*href="([^"]+)"[^>]*>([^<]+)</a></h3>',
                    r'<a[^>]*href="([^"]+)"[^>]*><h3[^>]*>([^<]+)</h3></a>'
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, response.text)
                    for url_match, title in matches[:max_headlines]:
                        title = re.sub(r'<[^>]*>', '', title).strip()
                        if self._is_relevant_news(title, ticker):
                            headlines.append({
                                'title': title[:100] + '...' if len(title) > 100 else title,
                                'url': url_match,
                                'published_date': (datetime.now() - timedelta(hours=2)).isoformat(),
                                'source': 'Google Search'
                            })
                            
                            if len(headlines) >= max_headlines:
                                break
                    
                    if headlines:
                        break
        
        except Exception as e:
            logger.debug(f"Simple web search failed for {ticker}: {e}")
        
        return headlines
    
    def _search_google_news(self, ticker, max_headlines=3):
        """Search Google News for recent ticker news with timestamps"""
        headlines = []

        try:
            # Google News RSS feed
            three_days_ago = datetime.now() - timedelta(days=3)

            # Use Google News RSS with improved search query
            company_name = self._get_company_name(ticker)
            if company_name and company_name != ticker.upper():
                search_query = f"{company_name} OR {ticker} stock earnings financial"
            else:
                search_query = f"{ticker} stock earnings financial"
            
            url = f"https://news.google.com/rss/search?q={search_query}&hl=en-US&gl=US&ceid=US:en"

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }

            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            # Parse RSS feed (basic XML parsing)
            import xml.etree.ElementTree as ET

            root = ET.fromstring(response.content)

            for item in root.findall('.//item')[:max_headlines * 2]:  # Get more to filter by date
                try:
                    title_elem = item.find('title')
                    link_elem = item.find('link')
                    pub_date_elem = item.find('pubDate')

                    if title_elem is not None and link_elem is not None:
                        title = title_elem.text
                        link = link_elem.text
                        published_date = None

                        # Parse publication date using improved method
                        if pub_date_elem is not None and pub_date_elem.text:
                            published_date = self._parse_date_with_fallbacks(pub_date_elem.text, ticker)
                        else:
                            # No date found, assume recent
                            logger.debug(f"No pubDate found for {ticker}, assuming recent")
                            published_date = datetime.now() - timedelta(hours=1)

                        # Check if within 3 days (but allow articles without proper dates)
                        if published_date:
                            try:
                                # Handle timezone-aware vs naive datetime comparison
                                if published_date.tzinfo is not None:
                                    # Convert to naive datetime for comparison
                                    published_date_naive = published_date.replace(tzinfo=None)
                                else:
                                    published_date_naive = published_date
                                
                                if published_date_naive < three_days_ago:
                                    logger.debug(f"Article too old for {ticker}: {published_date_naive}")
                                    continue
                            except Exception as date_compare_error:
                                logger.debug(f"Date comparison error for {ticker}: {date_compare_error}")
                                # If comparison fails, assume it's recent enough
                                pass

                        # Filter out obviously unrelated news using improved relevance checking
                        if self._is_relevant_news(title, ticker):
                            headline_item = {
                                'title': title[:100] + '...' if len(title) > 100 else title,
                                'url': link,
                                'published_date': published_date.isoformat() if published_date else None,
                                'source': 'Google News'
                            }
                            headlines.append(headline_item)
                            logger.debug(f"Added Google News headline for {ticker}: {title[:50]}...")

                            if len(headlines) >= max_headlines:
                                break

                except Exception as e:
                    logger.debug(f"Error parsing news item for {ticker}: {e}")
                    continue

        except Exception as e:
            logger.debug(f"Google News search failed for {ticker}: {e}")

        return headlines

    def _search_bing_news(self, ticker, max_headlines=3):
        """Search Bing News for recent ticker news with timestamps"""
        headlines = []

        try:
            # Try multiple Bing search approaches
            search_approaches = [
                f"https://www.bing.com/news/search?q={ticker}%20stock&qft=interval%3d%223%22",  # Last 3 days
                f"https://www.bing.com/news/search?q={ticker}%20stock",  # General search
                f"https://www.bing.com/news/search?q=\"{ticker}\"%20news",  # Exact ticker match
            ]

            for search_url in search_approaches:
                if len(headlines) >= max_headlines:
                    break

                try:
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }

                    response = requests.get(search_url, headers=headers, timeout=10)
                    response.raise_for_status()
                    content = response.text

                    # Look for various timestamp patterns
                    time_patterns = [
                        r'(\d+)\s*(minute|hour|day)s?\s*ago',
                        r'(\d+)h\s*ago',
                        r'(\d+)d\s*ago',
                        r'(\d+)m\s*ago',
                        r'(\d{1,2})/(\d{1,2})/(\d{4})',  # MM/DD/YYYY
                        r'(\d{4})-(\d{2})-(\d{2})',     # YYYY-MM-DD
                    ]

                    # Look for news article patterns with better matching
                    news_patterns = [
                        r'<h3[^>]*><a[^>]*href="([^"]*)"[^>]*>([^<]*)</a></h3>',
                        r'<a[^>]*href="([^"]*)"[^>]*class="[^"]*title[^"]*"[^>]*>([^<]*)</a>',
                        r'href="([^"]*)"[^>]*>([^<]*)</a>[^<]*<span[^>]*>([^<]*ago)</span>',
                    ]

                    for pattern in news_patterns:
                        matches = re.findall(pattern, content, re.IGNORECASE)

                        for match in matches[:max_headlines * 2]:
                            if len(headlines) >= max_headlines:
                                break

                            try:
                                if len(match) == 3:  # URL, title, timestamp
                                    url_match, title, timestamp_text = match
                                    published_date = self._parse_relative_time(timestamp_text)
                                elif len(match) == 2:  # URL, title
                                    url_match, title = match
                                    # Try to find timestamp near this article
                                    published_date = self._find_nearby_timestamp(content, title, time_patterns)
                                else:
                                    continue

                                # Filter relevant news using improved relevance checking
                                if self._is_relevant_news(title, ticker):
                                    # Clean up the URL
                                    if url_match.startswith('/'):
                                        url_match = 'https://www.bing.com' + url_match

                                    headline_item = {
                                        'title': title[:100] + '...' if len(title) > 100 else title,
                                        'url': url_match,
                                        'published_date': published_date.isoformat() if published_date else None,
                                        'source': 'Bing News'
                                    }
                                    headlines.append(headline_item)
                                    logger.debug(f"Added Bing headline for {ticker}: {title[:50]}...")

                            except Exception as match_error:
                                logger.debug(f"Error processing Bing match for {ticker}: {match_error}")
                                continue

                        if headlines:  # If we found some headlines with this pattern, use them
                            break

                except Exception as url_error:
                    logger.debug(f"Bing URL failed for {ticker}: {url_error}")
                    continue

        except Exception as e:
            logger.debug(f"Bing News search failed for {ticker}: {e}")

        return headlines

    def _parse_relative_time(self, time_text):
        """Parse relative time strings like '2 hours ago', '1 day ago' into datetime"""
        try:
            time_text = time_text.lower().strip()

            # Pattern matching for different formats
            patterns = [
                (r'(\d+)\s*minute[s]?\s*ago', 'minutes'),
                (r'(\d+)\s*hour[s]?\s*ago', 'hours'),
                (r'(\d+)\s*day[s]?\s*ago', 'days'),
                (r'(\d+)m\s*ago', 'minutes'),
                (r'(\d+)h\s*ago', 'hours'),
                (r'(\d+)d\s*ago', 'days'),
            ]

            for pattern, unit in patterns:
                match = re.search(pattern, time_text)
                if match:
                    value = int(match.group(1))
                    if unit == 'minutes':
                        return datetime.now() - timedelta(minutes=value)
                    elif unit == 'hours':
                        return datetime.now() - timedelta(hours=value)
                    elif unit == 'days':
                        return datetime.now() - timedelta(days=value)

            # If no pattern matches, return a default recent time
            return datetime.now() - timedelta(hours=2)

        except Exception as e:
            logger.debug(f"Error parsing relative time '{time_text}': {e}")
            return datetime.now() - timedelta(hours=2)

    def _find_nearby_timestamp(self, content, title, time_patterns):
        """Find timestamp information near a specific article title"""
        try:
            # Escape title for regex
            title_escaped = re.escape(title[:30])

            # Look for timestamps within 200 characters of the title
            context_pattern = f'{title_escaped}.{{0,200}}'
            context_match = re.search(context_pattern, content, re.DOTALL | re.IGNORECASE)

            if context_match:
                context = context_match.group()

                # Try each time pattern
                for pattern in time_patterns:
                    time_match = re.search(pattern, context)
                    if time_match:
                        return self._parse_relative_time(time_match.group())

            # Default fallback
            return datetime.now() - timedelta(hours=3)

        except Exception as e:
            logger.debug(f"Error finding nearby timestamp: {e}")
            return datetime.now() - timedelta(hours=3)

    def _search_yahoo_finance_news(self, ticker, max_headlines=3):
        """Search Yahoo Finance for recent ticker news with timestamps"""
        headlines = []

        try:
            # Try multiple Yahoo Finance approaches
            yahoo_urls = [
                f"https://finance.yahoo.com/quote/{ticker}/news",
                f"https://finance.yahoo.com/news/?query={ticker}",
                f"https://finance.yahoo.com/lookup?s={ticker}"
            ]

            for yahoo_url in yahoo_urls:
                if len(headlines) >= max_headlines:
                    break

                try:
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }

                    response = requests.get(yahoo_url, headers=headers, timeout=10)
                    response.raise_for_status()
                    content = response.text

                    # Multiple patterns for Yahoo Finance
                    yahoo_patterns = [
                        r'<h3[^>]*><a[^>]*href="([^"]*)"[^>]*>([^<]*)</a></h3>',
                        r'href="([^"]*)"[^>]*>([^<]*)</a>[^<]*<time[^>]*>([^<]*)</time>',
                        r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>[^<]*<span[^>]*>(\d+[hmd]\s*ago)</span>',
                    ]

                    # Time patterns for Yahoo
                    time_patterns = [
                        r'(\d+)\s*(minute|hour|day)s?\s*ago',
                        r'(\d+)[hmd]\s*ago',
                        r'(yesterday)',
                        r'(today)',
                    ]

                    for pattern in yahoo_patterns:
                        matches = re.findall(pattern, content, re.IGNORECASE)

                        for match in matches[:max_headlines]:
                            if len(headlines) >= max_headlines:
                                break

                            try:
                                if len(match) == 3:  # URL, title, timestamp
                                    url_match, title, timestamp_text = match
                                    published_date = self._parse_yahoo_time(timestamp_text)
                                elif len(match) == 2:  # URL, title
                                    url_match, title = match
                                    # Try to find timestamp nearby
                                    published_date = self._find_nearby_timestamp(content, title, time_patterns)
                                else:
                                    continue

                                # Make sure URL is absolute
                                if url_match.startswith('/'):
                                    url_match = 'https://finance.yahoo.com' + url_match
                                elif not url_match.startswith('http'):
                                    continue

                                # Filter for relevant news using improved relevance checking
                                if self._is_relevant_news(title, ticker):
                                    headline_item = {
                                        'title': title[:100] + '...' if len(title) > 100 else title,
                                        'url': url_match,
                                        'published_date': published_date.isoformat() if published_date else None,
                                        'source': 'Yahoo Finance'
                                    }
                                    headlines.append(headline_item)
                                    logger.debug(f"Added Yahoo headline for {ticker}: {title[:50]}...")

                            except Exception as match_error:
                                logger.debug(f"Error processing Yahoo match for {ticker}: {match_error}")
                                continue

                        if headlines:  # If we found headlines with this pattern, use them
                            break

                except Exception as url_error:
                    logger.debug(f"Yahoo URL failed for {ticker}: {url_error}")
                    continue

        except Exception as e:
            logger.debug(f"Yahoo Finance search failed for {ticker}: {e}")

        return headlines

    def _parse_yahoo_time(self, time_text):
        """Parse Yahoo Finance specific time formats"""
        try:
            time_text = time_text.lower().strip()

            # Yahoo specific patterns
            if 'today' in time_text:
                return datetime.now() - timedelta(hours=1)
            elif 'yesterday' in time_text:
                return datetime.now() - timedelta(days=1)
            else:
                # Use the general relative time parser
                return self._parse_relative_time(time_text)

        except Exception as e:
            logger.debug(f"Error parsing Yahoo time '{time_text}': {e}")
            return datetime.now() - timedelta(hours=2)

    def _create_pid_file(self):
        """Create PID file with current process ID"""
        try:
            pid = os.getpid()
            with open(PID_FILE, 'w') as f:
                f.write(str(pid))
            logger.info(f"📁 PID file created: {PID_FILE} (PID: {pid})")
            print(f"📁 Process ID: {pid} (saved to {PID_FILE})")
            print(f"💡 To stop the process later: kill $(cat {PID_FILE})")

            # Register cleanup function to remove PID file on exit
            atexit.register(self._cleanup_pid_file)

        except Exception as e:
            logger.error(f"❌ Failed to create PID file: {e}")

    def _cleanup_pid_file(self):
        """Remove PID file on exit"""
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
                logger.info(f"🗑️  PID file removed: {PID_FILE}")
        except Exception as e:
            logger.error(f"❌ Failed to remove PID file: {e}")

    def _get_tradingview_link(self, symbol):
        """Generate TradingView chart link for the symbol"""
        return f"https://www.tradingview.com/chart/?symbol={symbol}"

    def _get_position_size_recommendation(self, market_score=None):
        """
        Get position sizing recommendation based on market sentiment
        
        Args:
            market_score (int): Market sentiment score 0-100, if None will fetch current
            
        Returns:
            dict: {
                'recommendation': str,
                'score': int,
                'category': str
            }
        """
        if not self.market_scorer:
            return {
                'recommendation': "📊 Standard position size (market sentiment unavailable)",
                'score': 50,
                'category': 'UNKNOWN'
            }
        
        try:
            if market_score is None:
                market_conditions = self.market_scorer.get_current_market_sentiment_score()
                market_score = market_conditions['score']
                category = market_conditions['category']
            else:
                # Determine category from score
                if market_score >= 80:
                    category = "EXCELLENT"
                elif market_score >= 65:
                    category = "GOOD"
                elif market_score >= 45:
                    category = "FAIR"
                else:
                    category = "POOR"
            
            # Generate position sizing recommendation
            if market_score >= 80:
                recommendation = "🚀 LARGE: Consider 1.5-2x normal position size"
            elif market_score >= 65:
                recommendation = "✅ NORMAL: Standard position size"
            elif market_score >= 45:
                recommendation = "⚠️  SMALL: Reduce to 0.5x position size"
            else:
                recommendation = "🛑 MINIMAL: Avoid or paper trade only"
            
            return {
                'recommendation': recommendation,
                'score': market_score,
                'category': category
            }
            
        except Exception as e:
            logger.warning(f"Error getting position size recommendation: {e}")
            return {
                'recommendation': "📊 Standard position size (error getting market data)",
                'score': 50,
                'category': 'ERROR'
            }

    def _calculate_gap_percentage(self, current_price, change_from_open):
        """Calculate gap percentage from previous close"""
        if not current_price or not change_from_open:
            return None
        
        try:
            # Calculate opening price: current_price / (1 + change_from_open/100)
            open_price = current_price / (1 + change_from_open / 100)
            
            # Gap is the difference between open price and previous close
            # Previous close would be the opening price if there's no gap
            # But since we don't have direct previous close, we'll use change_from_open
            # as a proxy for the gap when it's the opening movement
            gap_pct = change_from_open
            
            return gap_pct
        except (ValueError, ZeroDivisionError):
            return None

    def _analyze_winning_patterns(self, current_price, change_pct, relative_volume, sector, alert_type="price_spike"):
        """Analyze alert against winning patterns and return probability score and flags
        
        MAJOR UPDATE (September 2025): Updated scoring based on comprehensive analysis of 605 alerts:
        - Fixed price range scoring: $1-3 range now gets highest score (was incorrectly mid-range)
        - Enhanced volume scoring: Added 500x+ mega volume tier for current market conditions  
        - Reduced flat-to-spike premium: Data shows regular high-volume spikes outperform
        - Adjusted probability thresholds: Market more selective, requires higher scores
        - Updated sector weightings: Health Tech confirmed as top performer (25.3% success)
        """
        flags = []
        score = 0
        probability_category = "LOW"
        
        # UPDATED PATTERN ANALYSIS BASED ON REAL PERFORMANCE DATA - SEPTEMBER 2025
        # Comprehensive analysis of 605 alerts (21 days): Key findings from market data:
        # - Success rate: 41.2% multi-alert patterns, Volume threshold critical: 50x+=50%, 200x+=63%, 400x+=65%
        # - Price sweet spot: $1-3 range = 44.8% of successes (highest), Under $1 = 26.4%, Over $3 = 28.7%
        # - Sector performance: Health Tech 25.3% success rate, Tech Services 14.9%, Finance 12.6%
        # - Recent market shift: Average volume for successes increased from 156x to 676x in last week
        # - Market more selective: Requires higher volume thresholds for success
        
        if alert_type == "afterhours_flat_to_premarket_spike":
            flags.append("🌙 AH-FLAT→PM-SPIKE")
            score += 50  # High value pattern - stock was quiet after-hours, then spiked in premarket

            # Extra bonus for larger after-hours to premarket spikes
            if change_pct >= 75:
                flags.append("🚀 BIG AH→PM SPIKE")
                score += 45  # Significant bonus for large spikes
        elif alert_type == "flat_to_spike":
            flags.append("🎯 FLAT-TO-SPIKE")
            score += 40  # Reduced from 60 - data shows regular spikes with high volume outperform

            # Extra bonus for larger flat-to-spike patterns
            if change_pct >= 75:
                flags.append("🚀 BIG FLAT-TO-SPIKE")
                score += 40  # Maximum bonus for large flat-to-spike
        elif alert_type == "immediate_spike":
            flags.append("⚡ IMMEDIATE SPIKE")
            score += 45  # 20-50% success rate (best performing type)
            
            # Extra bonus for larger immediate spikes
            if change_pct >= 75:
                flags.append("🚀 BIG IMMEDIATE SPIKE")
                score += 25  # Higher chance for bigger spikes
        elif alert_type == "price_spike":
            flags.append("📈 PRICE SPIKE")
            score += 35  # 50% success rate on good days
            
            if change_pct >= 75:
                flags.append("🚀 BIG PRICE SPIKE")
                score += 20
        elif alert_type == "volume_climber":
            flags.append("📊 VOLUME CLIMBER")
            score += 25  # 33% success rate (LASE had 117% gain)
        elif alert_type in ["premarket_price", "premarket_volume", "new_premarket_move"]:
            flags.append("🌅 PREMARKET")
            score -= 20  # 0% success rate in recent data
        
        # Price range analysis based on recent real data - UPDATED WITH LATEST FINDINGS
        if current_price < 1:
            flags.append("🎯 Under $1")
            score += 20  # 26.4% of successful patterns - increased scoring
        elif current_price < 3:
            flags.append("💎 Under $3") 
            score += 30  # SWEET SPOT: 44.8% of successful patterns - highest score
        elif current_price < 6:
            flags.append("💰 Mid-Range")
            score += 20  # Reduced from 25 - data shows $1-3 range is better
        else:
            flags.append("📈 Higher Price")
            score += 5   # Higher prices can work but less frequent
        
        # Initial change percentage analysis based on real winners
        if change_pct >= 145:
            flags.append("🚀 MASSIVE SPIKE 145%+")
            score += 35  # PMNT had 145.6% but failed, mixed results
        elif change_pct >= 100:
            flags.append("🔥 BIG SPIKE 100%+") 
            score += 30  # LASE had 117% gain (winner), PRFX 121% (failed)
        elif change_pct >= 50:
            flags.append("⚡ STRONG SPIKE 50%+")
            score += 25  # GXAI 53.6% (winner), SNGX 57.4% (winner)
        elif change_pct >= 30:
            flags.append("📈 SOLID MOVE 30%+")
            score += 15  # VELO 34.2%, ADD 36.1%, VCIG 32.6% (mixed results)
        elif change_pct >= 15:
            score += 10  # Moderate moves
        
        # Relative volume analysis based on real winners - UPDATED SCORING
        if relative_volume and relative_volume >= 500:
            flags.append("🌊 MEGA VOLUME 500x+")
            score += 50  # NEW: Current market requires extreme volume - 676x avg in recent successes
        elif relative_volume and relative_volume >= 400:
            flags.append("🌊 EXTREME VOL 400x+")
            score += 45  # Increased from 35 - 65% success rate
        elif relative_volume and relative_volume >= 200:
            flags.append("📈 VERY HIGH VOL 200x+")
            score += 35  # Increased from 30 - 63% success rate
        elif relative_volume and relative_volume >= 50:
            flags.append("📊 HIGH VOL 50x+")
            score += 20  # PMNT 68x (failed), TIVC 73x (failed), SRXH 31-168x (winner)
        elif relative_volume and relative_volume >= 10:
            flags.append("📊 GOOD VOL 10x+")
            score += 10  # Mixed results in this range
        elif relative_volume and relative_volume < 5:
            score -= 10  # Low volume typically fails
        
        # Sector analysis based on real winners from recent data - UPDATED WITH LATEST ANALYSIS
        successful_sectors = {
            "Health Technology": 40,  # 25.3% success rate - best performing sector
            "Electronic Technology": 35,  # Strong recent performance, increased score
            "Technology Services": 25,  # 14.9% success rate - emerging sector
            "Finance": 20,  # 12.6% success rate - consistent but lower
            "Transportation": 15,  # Reduced from previous analysis
            "Distribution Services": 10,  # Reduced scoring
            "Producer Manufacturing": 5,  # Lower success rate
            "Retail Trade": 5,  # Lower success rate
            "Consumer Services": 10,  # Slight increase based on recent data
        }
        
        if sector in successful_sectors:
            sector_score = successful_sectors[sector]
            if sector_score >= 35:
                flags.append(f"💊 BIOTECH/HEALTH")
                score += 25  # Health Technology is hot sector - 25.3% success rate
            elif sector_score >= 20:
                flags.append(f"🏭 GOOD SECTOR")
                score += 15
            elif sector_score >= 10:
                flags.append(f"📋 OK SECTOR")
                score += 5
        else:
            score -= 5  # Unknown sectors are riskier
        
        # Calculate probability category based on updated score - ADJUSTED FOR CURRENT MARKET
        # Recent market analysis shows higher volume requirements and more selectivity
        if score >= 110:
            probability_category = "VERY HIGH"
        elif score >= 85:
            probability_category = "HIGH"
        elif score >= 55:
            probability_category = "MEDIUM"
        elif score >= 30:
            probability_category = "LOW"
        else:
            probability_category = "VERY LOW"
        
        # Estimate success probability percentage based on real performance data
        # Analysis shows: Higher volume thresholds in recent market (avg 676x for successes)
        # Market has become more selective - adjust probabilities accordingly
        if score >= 140:
            estimated_probability = 45.0  # Exceptional conditions with mega volume (500x+)
        elif score >= 110:
            estimated_probability = 35.0  # Very high tier (adjusted upward)
        elif score >= 85:
            estimated_probability = 28.0  # High tier 
        elif score >= 55:
            estimated_probability = 22.0  # Medium tier 
        elif score >= 30:
            estimated_probability = 16.0  # Low tier 
        else:
            estimated_probability = 8.0   # Very low tier - slightly higher base
        
        # Calculate recommended stop-loss based on historical data
        # 87.9% of winners never dropped below alert price
        # Maximum drawdown seen: 12.0%, Optimal stop-loss: 15%
        recommended_stop_loss = self._calculate_stop_loss_recommendation(score, current_price, change_pct)
        
        return {
            'flags': flags,
            'score': score,
            'probability_category': probability_category,
            'estimated_probability': estimated_probability,
            'recommended_stop_loss': recommended_stop_loss
        }

    def _calculate_stop_loss_recommendation(self, score, current_price, change_pct):
        """Calculate recommended stop-loss percentage based on pattern analysis"""
        
        # Base stop-loss from historical analysis: 15% saves 100% of winners
        base_stop_loss = 15.0
        
        # Adjust based on pattern strength and price characteristics
        if score >= 80:
            # Very high probability - can be more aggressive since 87.9% never drop
            adjusted_stop_loss = 10.0
            confidence = "High confidence - tight stop"
        elif score >= 60:
            # High probability - standard recommendation
            adjusted_stop_loss = 12.0
            confidence = "Good confidence - moderate stop"
        elif score >= 40:
            # Medium probability - slightly more conservative
            adjusted_stop_loss = 15.0
            confidence = "Standard confidence - safe stop"
        else:
            # Low probability - more conservative
            adjusted_stop_loss = 20.0
            confidence = "Low confidence - wide stop"
        
        # Additional adjustments based on price characteristics
        if current_price < 1.0:
            # Penny stocks can be more volatile
            adjusted_stop_loss += 5.0
            confidence += " (penny stock adjustment)"
        elif current_price > 20.0:
            # Higher priced stocks may be less volatile
            adjusted_stop_loss -= 3.0
            confidence += " (high price adjustment)"
        
        # Ensure minimum and maximum bounds
        adjusted_stop_loss = max(8.0, min(25.0, adjusted_stop_loss))
        
        return {
            'percentage': adjusted_stop_loss,
            'confidence': confidence,
            'stop_price': current_price * (1 - adjusted_stop_loss / 100),
            'historical_note': "87.9% of winners never dropped below alert price"
        }
    
    def calculate_momentum_score(self, price_change, relative_volume, change_from_open, alert_type="price_spike"):
        """
        NEW: Calculate composite momentum score for alert prioritization
        Based on analysis recommendation: (price_change × 0.4) + (rel_volume × 0.3) + (change_from_open × 0.3)
        """
        try:
            # Normalize relative volume (cap at 1000x for scoring)
            normalized_rel_vol = min(relative_volume, 1000) / 10  # Scale down for scoring
            
            # Apply weights from analysis
            score = (
                (abs(price_change) * 0.4) +           # 40% weight on price change
                (normalized_rel_vol * 0.3) +          # 30% weight on relative volume  
                (abs(change_from_open) * 0.3)         # 30% weight on change from open
            )
            
            # Bonus for flat-to-spike patterns
            if alert_type == "afterhours_flat_to_premarket_spike":
                score *= 1.3  # 30% bonus for after-hours flat to premarket spike
            elif alert_type == "flat_to_spike":
                score *= 1.2  # 20% bonus for flat-to-spike

            return round(score, 2)
        except:
            return 0.0
    
    def get_ticker_cooldown_category(self, ticker):
        """Determine cooldown category based on ticker's historical performance"""
        if ticker not in self.ticker_alert_history:
            return 'default'
        
        # Calculate average change for this ticker
        history = self.ticker_alert_history[ticker]
        if len(history) == 0:
            return 'default'
        
        avg_change = sum(entry.get('change_pct', 0) for entry in history) / len(history)
        
        if avg_change >= 20:
            return 'high_performer'
        elif avg_change >= 5:
            return 'regular'
        else:
            return 'poor_performer'
    
    def is_ticker_in_cooldown(self, ticker):
        """Check if ticker is currently in cooldown period"""
        if ticker not in self.ticker_cooldowns:
            return False
        
        cooldown_category = self.get_ticker_cooldown_category(ticker)
        cooldown_duration = self.cooldown_periods.get(cooldown_category, self.cooldown_periods['default'])
        
        last_alert_time = self.ticker_cooldowns[ticker]
        time_since_last = (datetime.now() - last_alert_time).total_seconds()
        
        return time_since_last < cooldown_duration
    
    def get_sector_adjusted_thresholds(self, sector, base_relative_volume=3.0, base_price_change=10.0):
        """Apply sector-specific threshold adjustments"""
        config = self.sector_config.get(sector, self.sector_config['default'])
        
        adjusted_rel_vol = base_relative_volume * config['relative_volume_multiplier']
        adjusted_price_change = base_price_change * config['price_change_multiplier']
        
        return adjusted_rel_vol, adjusted_price_change
    
    def should_send_alert(self, ticker, sector, price_change, relative_volume, change_from_open, alert_type="price_spike"):
        """
        NEW: Comprehensive alert filtering with momentum scoring, cooldowns, and sector tuning
        """
        # Calculate momentum score
        momentum_score = self.calculate_momentum_score(price_change, relative_volume, change_from_open, alert_type)
        
        # High priority alerts (>50) bypass cooldowns
        if momentum_score > 50:
            logger.info(f"🚀 HIGH PRIORITY ALERT: {ticker} score={momentum_score} (bypassing cooldown)")
            return True, momentum_score, "high_priority"
        
        # Check cooldown for regular alerts
        if self.is_ticker_in_cooldown(ticker):
            logger.info(f"⏰ COOLDOWN: {ticker} still in cooldown period")
            return False, momentum_score, "cooldown"
        
        # Apply sector-specific thresholds
        adj_rel_vol, adj_price_change = self.get_sector_adjusted_thresholds(sector)
        
        # Check if meets adjusted thresholds
        if relative_volume >= adj_rel_vol and abs(price_change) >= adj_price_change:
            # Check for Utilities sector concentration (PCG/PC over-concentration issue)
            if sector == "Utilities" and self.sector_config['Utilities'].get('max_ticker_concentration'):
                if self._check_ticker_concentration(ticker, sector):
                    logger.info(f"📊 CONCENTRATION LIMIT: {ticker} exceeds sector concentration limits")
                    return False, momentum_score, "concentration_limit"
            
            return True, momentum_score, "approved"
        
        return False, momentum_score, "below_threshold"
    
    def _check_ticker_concentration(self, ticker, sector):
        """Check if ticker exceeds concentration limits for its sector"""
        # Simple implementation - could be enhanced with time-based windows
        if not hasattr(self, '_recent_alerts_count'):
            self._recent_alerts_count = {}
        
        # Reset counter periodically (every hour)
        current_hour = datetime.now().hour
        if not hasattr(self, '_last_reset_hour') or self._last_reset_hour != current_hour:
            self._recent_alerts_count = {}
            self._last_reset_hour = current_hour
        
        total_alerts = sum(self._recent_alerts_count.values())
        ticker_alerts = self._recent_alerts_count.get(ticker, 0)
        
        if total_alerts == 0:
            return False
        
        concentration = ticker_alerts / total_alerts
        max_concentration = self.sector_config.get(sector, {}).get('max_ticker_concentration', 1.0)
        
        return concentration > max_concentration
    
    def update_ticker_cooldown(self, ticker):
        """Update the last alert time for ticker cooldown tracking"""
        self.ticker_cooldowns[ticker] = datetime.now()
        
        # Update concentration tracking
        if not hasattr(self, '_recent_alerts_count'):
            self._recent_alerts_count = {}
        self._recent_alerts_count[ticker] = self._recent_alerts_count.get(ticker, 0) + 1
    
    def check_paper_trading_exits(self, current_data):
        """
        Check all active paper trading positions for exit signals
        
        Args:
            current_data (list): Current screener data
        """
        if not self.enable_paper_trading or not self.paper_trader:
            return
        
        try:
            # Build price dictionary from current data
            price_data = {}
            for record in current_data:
                ticker = record.get('name')
                price = record.get('close', 0)
                if ticker and price > 0:
                    price_data[ticker] = price
            
            # Check for exits (including EOD cutoff check)
            exits = self.paper_trader.check_all_positions_for_exits(price_data, current_time=datetime.now())
            
            for exit_info in exits:
                exit_reason = exit_info.get('exit_reason', 'UNKNOWN')
                if 'EOD_CUTOFF' in exit_reason:
                    logger.info(f"🚨 EOD AUTO EXIT: {exit_info['ticker']} - P&L: ${exit_info['profit_loss']:+.2f} ({exit_info['profit_pct']:+.2f}%) - FORCED CLOSE AT 3:45PM ET")
                else:
                    logger.info(f"📊 AUTO EXIT: {exit_info['ticker']} - P&L: ${exit_info['profit_loss']:+.2f} ({exit_info['profit_pct']:+.2f}%)")
                
        except Exception as e:
            logger.error(f"❌ Error checking paper trading exits: {e}")
    
    def get_paper_trading_summary(self):
        """Get paper trading performance summary"""
        if not self.enable_paper_trading or not self.paper_trader:
            return "Paper trading not enabled"
        
        try:
            return self.paper_trader.generate_performance_report()
        except Exception as e:
            return f"Error generating paper trading report: {e}"
    
    def _log_telegram_alert_sent(self, ticker, alert_count, current_price, change_pct, volume, relative_volume, sector, alert_types, is_immediate_spike=False, pattern_analysis=None, disregarded=False, paper_trade_info=None):
        """Log the details of a successfully sent Telegram alert for end-of-day analysis"""
        try:
            alert_log_entry = {
                'timestamp': datetime.now().isoformat(),
                'ticker': ticker,
                'alert_price': current_price,
                'change_pct': change_pct,
                'volume': volume,
                'relative_volume': relative_volume,
                'sector': sector,
                'alert_types': alert_types,
                'alert_count': alert_count,
                'is_immediate_spike': is_immediate_spike,
                'alert_type': 'immediate_spike' if is_immediate_spike else alert_types[0] if alert_types else 'price_spike',
                'disregarded': disregarded,
                'paper_trade_info': paper_trade_info
            }
            
            # Include pattern analysis data if provided
            if pattern_analysis:
                alert_log_entry.update({
                    'win_probability_category': pattern_analysis.get('probability_category', 'UNKNOWN'),
                    'estimated_win_probability': pattern_analysis.get('estimated_probability', 0),
                    'pattern_flags': pattern_analysis.get('flags', []),
                    'pattern_score': pattern_analysis.get('score', 0)
                })
            
            # Append to JSONL file (one JSON object per line)
            with open(self.telegram_alerts_log, 'a', encoding='utf-8') as f:
                f.write(json.dumps(alert_log_entry) + '\n')
            
            logger.debug(f"📝 Logged Telegram alert for {ticker} to {self.telegram_alerts_log}")
            
        except Exception as e:
            logger.error(f"❌ Failed to log Telegram alert for {ticker}: {e}")

    def _log_hourly_notification(self, notification_type, tickers_data, message_content):
        """Log hourly notification for later performance analysis"""
        try:
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'notification_type': notification_type,
                'tickers_count': len(tickers_data) if tickers_data else 0,
                'tickers': [
                    {
                        'ticker': item.get('ticker', 'N/A'),
                        'price': item.get('price', 0),
                        'intraday_movement': item.get('intraday_movement', 0),
                        'flatness': item.get('flatness', 0),
                        'volume_ratio': item.get('volume_ratio', 0),
                        'float': item.get('float', 0)
                    }
                    for item in (tickers_data or [])
                ],
                'message_length': len(message_content) if message_content else 0
            }

            # Append to JSONL file
            with open(self.hourly_notifications_log, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry) + '\n')

            logger.info(f"📝 Logged hourly {notification_type} notification with {len(tickers_data) if tickers_data else 0} tickers")

        except Exception as e:
            logger.error(f"❌ Failed to log hourly notification: {e}")

    def _generate_list_flat_content(self):
        """Generate the list_flat content for reuse in command handler and hourly notifications"""
        try:
            # Get latest screener data
            screener_data = self.get_volume_screener_data()

            if not screener_data:
                return None, "❌ No screener data available.", []

            if not self.alpaca_client:
                return None, "❌ Alpaca client not available. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY.", []

            # Calculate ACTUAL flatness and intraday movement using historical data
            logger.info("📊 Calculating flatness and intraday movement with Alpaca data...")
            tickers_with_data = []

            # Collect all tickers for batch request
            tickers = [record.get('name', 'N/A') for record in screener_data]
            ticker_data_map = {record.get('name', 'N/A'): record for record in screener_data}

            # Fetch historical data in batch from Alpaca
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)  # Extra days to ensure we get enough data

            try:
                request_params = StockBarsRequest(
                    symbol_or_symbols=tickers,
                    timeframe=TimeFrame.Day,
                    start=start_date,
                    end=end_date,
                    feed=DataFeed.IEX  # Use IEX feed (free tier)
                )

                bars = self.alpaca_client.get_stock_bars(request_params)
            except Exception as e:
                logger.error(f"Failed to fetch batch data from Alpaca: {e}")
                return None, f"❌ Error fetching market data: {str(e)}", []

            for ticker in tickers:
                record = ticker_data_map[ticker]
                current_price = record.get('close', 0)
                current_volume = record.get('volume', 0)
                float_shares = record.get('float_shares_outstanding', 0)

                try:
                    if ticker not in bars or len(bars[ticker]) < 2:
                        logger.debug(f"⚠️ {ticker}: Insufficient historical data from Alpaca")
                        continue

                    ticker_bars = bars[ticker]

                    # Get actual prices from last 2 days
                    prev_bar = ticker_bars[-2]
                    today_bar = ticker_bars[-1]

                    prev_close = float(prev_bar.close)
                    today_open = float(today_bar.open)
                    today_close = float(today_bar.close)
                    prev_volume = float(prev_bar.volume)

                    # Calculate ACTUAL gap from previous close (flatness)
                    gap_amount = abs(today_open - prev_close)
                    gap_pct = (gap_amount / prev_close) * 100 if prev_close > 0 else float('inf')

                    # Calculate intraday movement
                    intraday_change = today_close - today_open
                    intraday_pct = (intraday_change / today_open) * 100 if today_open > 0 else 0

                    # Volume ratio
                    volume_ratio = current_volume / prev_volume if prev_volume > 0 else 0

                    tickers_with_data.append({
                        'ticker': ticker,
                        'flatness': gap_pct,
                        'intraday_movement': intraday_pct,
                        'price': current_price,
                        'volume': current_volume,
                        'float': float_shares,
                        'prev_volume': prev_volume,
                        'volume_ratio': volume_ratio,
                        'today_open': today_open,
                        'prev_close': prev_close
                    })

                    logger.debug(f"{ticker}: Gap={gap_pct:.2f}%, Intraday={intraday_pct:+.2f}%, Vol ratio={volume_ratio:.1f}x")

                except Exception as e:
                    logger.debug(f"⚠️ {ticker}: Error processing Alpaca data: {e}")
                    continue

            logger.info(f"✅ Processed {len(tickers_with_data)} tickers with Alpaca data")

            # OPTIMIZED PARAMETERS based on notification log analysis:
            # - Volume ratio minimum: 1.5x (was 1x) - median from logs is 64.3x
            # - Minimum intraday movement: 2% - 14% of alerts were <5% (noise)
            # - Max results: 15 (was 20) - focus on quality signals
            MIN_VOLUME_RATIO = 1.5
            MIN_INTRADAY_MOVEMENT = 2.0  # Filter out low-movement noise
            MAX_RESULTS = 15

            # Filter by volume and intraday movement
            filtered_tickers = []
            for item in tickers_with_data:
                ticker = item['ticker']
                volume_ratio = item.get('volume_ratio', 0)
                intraday_movement = abs(item.get('intraday_movement', 0))

                # Apply optimized filters
                # if volume_ratio >= MIN_VOLUME_RATIO and intraday_movement >= MIN_INTRADAY_MOVEMENT:
                #     filtered_tickers.append(item)
                #     logger.debug(f"✅ {ticker}: Gap={item['flatness']:.2f}%, Intraday={item['intraday_movement']:+.2f}%, Vol={volume_ratio:.1f}x")
                # else:
                     #if volume_ratio < MIN_VOLUME_RATIO:
                     #   logger.debug(f"⚠️ {ticker}: Vol only {volume_ratio:.1f}x (needs {MIN_VOLUME_RATIO}x)")
                    # elif intraday_movement < MIN_INTRADAY_MOVEMENT:
                        # logger.debug(f"⚠️ {ticker}: Intraday only {intraday_movement:.1f}% (needs {MIN_INTRADAY_MOVEMENT}%)")

            # Sort by intraday movement (descending)
            filtered_tickers.sort(key=lambda x: x['intraday_movement'], reverse=True)

            # Get top results
            top_results = filtered_tickers[:MAX_RESULTS]

            # Get VIX data
            vix_data = self._get_vix_data()
            vix_str = "N/A"
            if vix_data:
                vix_str = f"{vix_data['current']:.2f} ({vix_data['level']}, {vix_data['week_trend']} {vix_data['week_change']:+.1f}%)"

            # Build response
            if len(top_results) == 0:
                response = f"📊 Stocks in Play (Optimized Filters)\n"
                response += f"📈 VIX: {vix_str}\n\n"
                response += "❌ No stocks found matching criteria:\n"
                response += f"• Volume ≥ {MIN_VOLUME_RATIO}x previous day volume\n"
                response += f"• Intraday movement ≥ {MIN_INTRADAY_MOVEMENT}%"
            else:
                response = f"📊 Top {len(top_results)} Stocks in Play\n"
                response += f"📈 VIX: {vix_str}\n"
                response += f"Filters: Vol≥{MIN_VOLUME_RATIO}x, Move≥{MIN_INTRADAY_MOVEMENT}%\n\n"

                for i, item in enumerate(top_results, 1):
                    ticker = item['ticker']
                    price = item['price']
                    volume = item['volume']
                    float_shares = item['float']
                    flatness = item['flatness']
                    volume_ratio = item.get('volume_ratio', 0)
                    intraday_movement = item.get('intraday_movement', 0)

                    # Format float shares in millions
                    float_m = float_shares / 1_000_000 if float_shares else 0

                    # Format volume in millions
                    vol_m = volume / 1_000_000 if volume else 0

                    # Get TradingView link
                    tv_link = self._get_tradingview_link(ticker)

                    response += f"{i}. [{ticker}]({tv_link}) - Intraday: {intraday_movement:+.1f}% | Gap: {flatness:.2f}%\n"
                    response += f"   💰 ${price:.2f} | 📊 Float: {float_m:.1f}M | 📈 Vol: {vol_m:.1f}M ({volume_ratio:.0f}x)\n\n"

                logger.info(f"📋 Generated list of {len(top_results)} stocks sorted by intraday movement")

            return response, None, top_results

        except Exception as e:
            logger.error(f"❌ Error generating list_flat content: {e}")
            return None, f"❌ Error generating flat stocks list: {str(e)}", []

    async def _send_hourly_list_flat(self, context):
        """Send hourly list_flat notification (job callback for scheduled task)"""
        try:
            logger.info("⏰ Sending hourly list_flat notification...")

            # Generate the list_flat content
            response, error, tickers_data = self._generate_list_flat_content()

            if error:
                message = f"⏰ Hourly Update\n\n{error}"
            else:
                # Add hourly indicator to the response
                current_time = datetime.now().strftime("%H:%M")
                message = f"⏰ Hourly Update ({current_time})\n\n{response}"

            # Send the message
            await context.bot.send_message(
                chat_id=self.telegram_chat_id,
                text=message,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )

            # Log the notification
            self._log_hourly_notification('list_flat', tickers_data, message)
            self.last_hourly_list_flat = datetime.now()

            logger.info(f"✅ Hourly list_flat notification sent successfully")

        except Exception as e:
            logger.error(f"❌ Failed to send hourly list_flat notification: {e}")

    def _send_telegram_alert(self, ticker, alert_count, current_price, change_pct, volume, relative_volume, sector, alert_types, is_immediate_spike=False, gap_pct=None, float_shares=None):
        """Send Telegram alert for high-frequency ticker or immediate big spike with rate limiting and news headlines with timestamps"""
        if not self.telegram_bot or not self.telegram_chat_id:
            return

        # Check rate limiting - don't send if we sent a notification for this ticker recently
        current_time = datetime.now()
        last_sent_time = self.telegram_last_sent.get(ticker)

        if last_sent_time and not is_immediate_spike:  # Skip rate limiting for immediate spikes
            time_since_last = (current_time - datetime.fromisoformat(last_sent_time)).total_seconds()
            if time_since_last < self.telegram_notification_interval:
                logger.debug(f"Rate limiting: Skipping Telegram alert for {ticker} (sent {time_since_last:.0f}s ago)")
                return

        # Check if ticker is disregarded by user
        if ticker in self.disregarded_tickers:
            logger.info(f"📵 Alert disregarded for {ticker} ({change_pct:+.1f}%, {alert_count} alerts) - user disabled alerts for this ticker")
            # Log the disregarded alert for end-of-day analysis
            self._log_telegram_alert_sent(ticker, alert_count, current_price, change_pct, volume, relative_volume, sector, alert_types, is_immediate_spike, None, disregarded=True, paper_trade_info=None)
            return

        # NEW: Apply enhanced filtering with momentum scoring and cooldowns
        if not is_immediate_spike:  # Skip for immediate spikes (they override everything)
            change_from_open = gap_pct if gap_pct is not None else 0  # Use gap_pct as proxy for change_from_open
            alert_type = alert_types[0] if alert_types else "price_spike"
            
            should_send, momentum_score, reason = self.should_send_alert(
                ticker, sector, change_pct, relative_volume, change_from_open, alert_type
            )
            
            if not should_send:
                logger.info(f"🚫 FILTERED: {ticker} ({change_pct:+.1f}%, score={momentum_score}) - {reason}")
                return
            else:
                logger.info(f"✅ APPROVED: {ticker} ({change_pct:+.1f}%, score={momentum_score}) - {reason}")
                # Update cooldown tracking
                self.update_ticker_cooldown(ticker)

        # NEW: Paper Trading Integration - Process alert for trading simulation
        paper_trade_info = ""
        if self.enable_paper_trading and self.paper_trader:
            try:
                trade_action = self.paper_trader.process_alert(
                    ticker=ticker,
                    current_price=current_price,
                    alert_type=alert_types[0] if alert_types else "price_spike"
                )
                
                # Determine paper trade result for telegram message
                if trade_action['entry']:
                    logger.info(f"📊 PAPER TRADE ENTRY: {ticker} at ${current_price:.4f}")
                    paper_trade_info = f"✅ Paper Trade: BOUGHT at ${current_price:.4f}"
                elif trade_action['trade_decision_reason']:
                    logger.info(f"📊 PAPER TRADE REJECTED: {ticker} - {trade_action['trade_decision_reason']}")
                    paper_trade_info = f"❌ Paper Trade: NOT BOUGHT - {trade_action['trade_decision_reason']}"
                
                if trade_action['exit']:
                    exit_info = trade_action['exit']
                    logger.info(f"📊 PAPER TRADE EXIT: {ticker} - P&L: ${exit_info['profit_loss']:+.2f} ({exit_info['profit_pct']:+.2f}%)")
                    paper_trade_info += f"\n📊 Previous Position: SOLD - P&L: ${exit_info['profit_loss']:+.2f} ({exit_info['profit_pct']:+.2f}%)"
                    
            except Exception as e:
                logger.error(f"❌ Paper trading error for {ticker}: {e}")
                paper_trade_info = f"❌ Paper Trade: ERROR - {str(e)}"

        try:
            import asyncio

            # Analyze winning patterns
            primary_alert_type = alert_types[0] if alert_types else "price_spike"
            pattern_analysis = self._analyze_winning_patterns(
                current_price, change_pct, relative_volume, sector, primary_alert_type
            )
            
            # Get recent news headlines
            logger.info(f"Fetching recent news for {ticker}...")
            recent_news = self._get_recent_news(ticker, max_headlines=3)

            # Get VIX data for market context
            logger.info(f"Fetching VIX data...")
            vix_data = self._get_vix_data()

            tradingview_link = self._get_tradingview_link(ticker)
            alert_types_str = ', '.join(alert_types[:3])  # First 3 alert types
            if len(alert_types) > 3:
                alert_types_str += f" +{len(alert_types)-3}"

            # Format relative volume display
            rel_vol_str = f"{relative_volume:.1f}x" if relative_volume and relative_volume > 0 else "N/A"
            
            # Format float shares display
            float_str = f"{float_shares:,.0f}" if float_shares and float_shares > 0 else "N/A"
            
            # Format gap display
            gap_str = f"{gap_pct:+.1f}%" if gap_pct is not None else "N/A"
            
            # Create winning pattern flags string
            pattern_flags_str = " ".join(pattern_analysis['flags']) if pattern_analysis['flags'] else "📊 Standard Alert"
            probability_str = f"{pattern_analysis['probability_category']} ({pattern_analysis['estimated_probability']:.1f}%)"
            
            # Create stop-loss recommendation string
            stop_loss = pattern_analysis['recommended_stop_loss']
            stop_loss_str = f"{stop_loss['percentage']:.1f}% (${stop_loss['stop_price']:.2f})"
            
            # Calculate 30% target price
            target_price = current_price * 1.30
            target_str = f"30.0% (${target_price:.2f})"
            
            # Get position sizing recommendation based on market conditions
            position_sizing = self._get_position_size_recommendation()

            # Get current session alert count (before increment)
            current_session_count = self.session_alert_count.get(ticker, 0)

            # Format VIX information string
            vix_str = ""
            if vix_data:
                # VIX emoji based on level
                vix_emoji = {
                    'low': '🟢',
                    'moderate': '🟡',
                    'elevated': '🟠',
                    'high': '🔴'
                }.get(vix_data['level'], '⚪')

                # Trend emoji
                trend_emoji = '📈' if vix_data['week_trend'] == 'rising' else '📉'

                vix_str = (f"\n📊 VIX: {vix_emoji} {vix_data['current']:.2f} "
                          f"({trend_emoji} {vix_data['week_trend']} {vix_data['week_change']:+.1f}% this week, "
                          f"{vix_data['level']} volatility)")
            else:
                vix_str = "\n📊 VIX: N/A"

            # Different message for immediate spikes vs regular high frequency
            if is_immediate_spike:
                message = (
                    f"🚨 IMMEDIATE BIG SPIKE ALERT! 🚨\n\n"
                    f"📊 Ticker: {ticker}\n"
                    f"⚡ MASSIVE SPIKE: {change_pct:+.1f}% (≥{self.immediate_spike_threshold:.0f}%)\n"
                    f"💰 Current Price: ${current_price:.2f}\n"
                    f"📈 Volume: {volume:,}\n"
                    f"📊 Relative Volume: {rel_vol_str}\n"
                    f"🏦 Float: {float_str}\n"
                    f"📈 Gap: {gap_str}\n"
                    f"🏭 Sector: {sector}\n\n"
                    f"🎯 WIN PROBABILITY: {probability_str}\n"
                    f"🚀 PATTERN FLAGS: {pattern_flags_str}\n"
                    f"🛑 RECOMMENDED STOP: {stop_loss_str}\n"
                    f"🎯 TARGET PRICE: {target_str}\n"
                    f"💰 POSITION SIZE: {position_sizing['recommendation']}\n"
                    f"📊 MARKET CONDITIONS: {position_sizing['score']}/100 ({position_sizing['category']}){vix_str}\n\n"
                    f"🔥 This ticker just spiked {change_pct:+.1f}% - immediate alert triggered!\n"
                    f"📈 Previous alerts: {alert_count}\n"
                    f"📱 Session alerts: {current_session_count + 1} (this session)\n"
                    f"🎯 Alert Types: {alert_types_str}\n\n"
                    f"📊 View Chart: {tradingview_link}"
                )
                
                # Add paper trading information to immediate spike message
                if paper_trade_info:
                    message += f"\n\n💰 {paper_trade_info}"
            else:
                message = (
                    f"🔥 HIGH FREQUENCY MOMENTUM ALERT 🔥\n\n"
                    f"📊 Ticker: {ticker}\n"
                    f"⚡ Alert Count: {alert_count} times\n"
                    f"📱 Session alerts: {current_session_count + 1} (this session)\n"
                    f"💰 Current Price: ${current_price:.2f} ({change_pct:+.1f}%)\n"
                    f"📈 Volume: {volume:,}\n"
                    f"📊 Relative Volume: {rel_vol_str}\n"
                    f"🏦 Float: {float_str}\n"
                    f"📈 Gap: {gap_str}\n"
                    f"🏭 Sector: {sector}\n\n"
                    f"🎯 WIN PROBABILITY: {probability_str}\n"
                    f"🚀 PATTERN FLAGS: {pattern_flags_str}\n"
                    f"🛑 RECOMMENDED STOP: {stop_loss_str}\n"
                    f"🎯 TARGET PRICE: {target_str}\n"
                    f"💰 POSITION SIZE: {position_sizing['recommendation']}\n"
                    f"📊 MARKET CONDITIONS: {position_sizing['score']}/100 ({position_sizing['category']}){vix_str}\n\n"
                    f"📋 This ticker has triggered {alert_count} momentum alerts, "
                    f"indicating sustained bullish activity!\n"
                    f"🎯 Alert Types: {alert_types_str}\n\n"
                    f"📊 View Chart: {tradingview_link}"
                )
            
            # Add paper trading information if available
            if paper_trade_info:
                message += f"\n\n💰 {paper_trade_info}"

            # Add recent news headlines if available with timestamps
            if recent_news:
                message += f"\n\n📰 Recent Headlines:"
                for i, news_item in enumerate(recent_news, 1):
                    # Include timestamp in the display
                    time_info = news_item.get('time_ago', 'Unknown time')
                    title = news_item['title']
                    url = news_item['url']

                    # Escape markdown special characters in title
                    escaped_title = self._escape_markdown(title)
                    
                    # Telegram supports markdown links: [text](url)
                    message += f"\n{i}. ({time_info}) [{escaped_title}]({url})"
            else:
                message += f"\n\n📰 No recent headlines found for {ticker}"

            # Handle async send_message properly
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # Send message with Markdown parsing enabled for clickable links
            loop.run_until_complete(
                self.telegram_bot.send_message(
                    self.telegram_chat_id,
                    message,
                    parse_mode='Markdown',
                    disable_web_page_preview=True  # Prevent telegram from showing preview for every link
                )
            )

            # Update last sent time for rate limiting
            self.telegram_last_sent[ticker] = current_time.isoformat()
            
            # Increment session alert count
            self.session_alert_count[ticker] = self.session_alert_count.get(ticker, 0) + 1
            
            alert_type = "IMMEDIATE SPIKE" if is_immediate_spike else "HIGH FREQUENCY"
            logger.info(f"📱 Telegram {alert_type} alert sent for {ticker} ({change_pct:+.1f}%, {alert_count} alerts, {self.session_alert_count[ticker]} session alerts) with {len(recent_news)} news headlines")
            
            # Log the successful Telegram alert for end-of-day analysis
            self._log_telegram_alert_sent(ticker, alert_count, current_price, change_pct, volume, relative_volume, sector, alert_types, is_immediate_spike, pattern_analysis, paper_trade_info=paper_trade_info)

        except Exception as e:
            logger.error(f"❌ Failed to send Telegram alert for {ticker}: {e}")
            # Try sending without markdown if it fails
            try:
                rel_vol_str = f"{relative_volume:.1f}x" if relative_volume and relative_volume > 0 else "N/A"
                float_str = f"{float_shares:,.0f}" if float_shares and float_shares > 0 else "N/A"
                
                # Recreate pattern analysis for simple message
                primary_alert_type = alert_types[0] if alert_types else "price_spike"
                pattern_analysis = self._analyze_winning_patterns(
                    current_price, change_pct, relative_volume, sector, primary_alert_type
                )
                pattern_flags_str = " ".join(pattern_analysis['flags']) if pattern_analysis['flags'] else "📊 Standard Alert"
                probability_str = f"{pattern_analysis['probability_category']} ({pattern_analysis['estimated_probability']:.1f}%)"
                stop_loss = pattern_analysis['recommended_stop_loss']
                stop_loss_str = f"{stop_loss['percentage']:.1f}% (${stop_loss['stop_price']:.2f})"
                
                # Calculate 30% target price
                target_price = current_price * 1.30
                target_str = f"30.0% (${target_price:.2f})"
                
                # Get position sizing recommendation
                position_sizing = self._get_position_size_recommendation()
                
                if is_immediate_spike:
                    simple_message = (
                        f"🚨 IMMEDIATE BIG SPIKE ALERT! 🚨\n\n"
                        f"📊 Ticker: {ticker}\n"
                        f"⚡ MASSIVE SPIKE: {change_pct:+.1f}% (≥{self.immediate_spike_threshold:.0f}%)\n"
                        f"💰 Current Price: ${current_price:.2f}\n"
                        f"📈 Volume: {volume:,}\n"
                        f"📊 Relative Volume: {rel_vol_str}\n"
                        f"🏦 Float: {float_str}\n"
                        f"🏭 Sector: {sector}\n\n"
                        f"🎯 WIN PROBABILITY: {probability_str}\n"
                        f"🚀 PATTERN FLAGS: {pattern_flags_str}\n"
                        f"🛑 RECOMMENDED STOP: {stop_loss_str}\n"
                        f"🎯 TARGET PRICE: {target_str}\n"
                        f"💰 POSITION SIZE: {position_sizing['recommendation']}\n"
                        f"📊 MARKET CONDITIONS: {position_sizing['score']}/100 ({position_sizing['category']})\n\n"
                        f"📊 Chart: {tradingview_link}"
                    )
                else:
                    simple_message = (
                        f"🔥 HIGH FREQUENCY MOMENTUM ALERT 🔥\n\n"
                        f"📊 Ticker: {ticker}\n"
                        f"⚡ Alert Count: {alert_count} times\n"
                        f"💰 Current Price: ${current_price:.2f} ({change_pct:+.1f}%)\n"
                        f"📈 Volume: {volume:,}\n"
                        f"📊 Relative Volume: {rel_vol_str}\n"
                        f"🏦 Float: {float_str}\n"
                        f"🏭 Sector: {sector}\n\n"
                        f"🎯 WIN PROBABILITY: {probability_str}\n"
                        f"🚀 PATTERN FLAGS: {pattern_flags_str}\n"
                        f"🛑 RECOMMENDED STOP: {stop_loss_str}\n"
                        f"🎯 TARGET PRICE: {target_str}\n"
                        f"💰 POSITION SIZE: {position_sizing['recommendation']}\n"
                        f"📊 MARKET CONDITIONS: {position_sizing['score']}/100 ({position_sizing['category']})\n\n"
                        f"📊 Chart: {tradingview_link}"
                    )

                if recent_news:
                    simple_message += f"\n\nRecent Headlines:"
                    for i, news_item in enumerate(recent_news, 1):
                        time_info = news_item.get('time_ago', 'Unknown time')
                        simple_message += f"\n{i}. ({time_info}) {news_item['title']}"
                        simple_message += f"\n   {news_item['url']}"

                loop.run_until_complete(
                    self.telegram_bot.send_message(self.telegram_chat_id, simple_message)
                )
                alert_type = "IMMEDIATE SPIKE" if is_immediate_spike else "HIGH FREQUENCY"
                logger.info(f"📱 Sent simplified Telegram {alert_type} alert for {ticker}")
                
                # Log the successful Telegram alert for end-of-day analysis
                self._log_telegram_alert_sent(ticker, alert_count, current_price, change_pct, volume, relative_volume, sector, alert_types, is_immediate_spike, pattern_analysis, paper_trade_info=paper_trade_info)

            except Exception as e2:
                logger.error(f"❌ Failed to send even simplified alert: {e2}")

    def _send_immediate_spike_alert(self, ticker, alert_data):
        """Send immediate alert for very big price spikes"""
        if not self.telegram_bot or not self.telegram_chat_id:
            return

        history = self.ticker_alert_history.get(ticker, {})
        alert_types = list(history.get('alert_types', {}).keys())
        alert_count = self.ticker_counters.get(ticker, 1)

        # Get current data from the alert
        current_price = alert_data.get('current_price', alert_data.get('price', 0))
        change_pct = alert_data.get('change_pct', alert_data.get('premarket_change', 0))
        volume = alert_data.get('volume', 0)
        # Extract relative volume from different possible keys
        relative_volume = alert_data.get('relative_volume',
                        alert_data.get('relative_volume_10d_calc', 0))
        sector = alert_data.get('sector', 'Unknown')
        float_shares = get_float_shares_value(alert_data)
        
        # Calculate gap percentage
        change_from_open = alert_data.get('change_from_open', 0)
        gap_pct = self._calculate_gap_percentage(current_price, change_from_open)

        self._send_telegram_alert(ticker, alert_count, current_price, change_pct, volume, relative_volume, sector, alert_types, is_immediate_spike=True, gap_pct=gap_pct, float_shares=float_shares)

    def _check_high_frequency_alerts(self, ticker, alert_data):
        """Check if ticker qualifies for Telegram notification (sends every time for 3+ alerts with rate limiting)"""
        if not self.telegram_bot or not self.telegram_chat_id:
            return

        alert_count = self.ticker_counters.get(ticker, 0)

        # Send Telegram alert every time for tickers with 3+ alerts (with rate limiting)
        if alert_count >= 3:
            history = self.ticker_alert_history.get(ticker, {})
            alert_types = list(history.get('alert_types', {}).keys())

            # Get current data from the alert
            current_price = alert_data.get('current_price', alert_data.get('price', 0))
            change_pct = alert_data.get('change_pct', alert_data.get('premarket_change', 0))
            volume = alert_data.get('volume', 0)
            # Extract relative volume from different possible keys
            relative_volume = alert_data.get('relative_volume',
                            alert_data.get('relative_volume_10d_calc', 0))
            sector = alert_data.get('sector', 'Unknown')
            float_shares = get_float_shares_value(alert_data)
            
            # Calculate gap percentage
            change_from_open = alert_data.get('change_from_open', 0)
            gap_pct = self._calculate_gap_percentage(current_price, change_from_open)

            self._send_telegram_alert(ticker, alert_count, current_price, change_pct, volume, relative_volume, sector, alert_types, is_immediate_spike=False, gap_pct=gap_pct, float_shares=float_shares)

    def _get_cookies(self):
        """Get cookies from browser using rookiepy"""
        try:
            cookies_list = rookiepy.load()
            cookies = {}
            for cookie in cookies_list:
                if 'tradingview.com' in cookie.get('domain', ''):
                    cookies[cookie['name']] = cookie['value']
            logger.info(f"Successfully extracted {len(cookies)} cookies")
            return cookies
        except Exception as e:
            logger.error(f"Failed to extract cookies: {e}")
            return {}

    def _load_ticker_counters(self):
        """Load ticker appearance counters from file"""
        counter_file = self.output_dir / "ticker_counters.json"
        try:
            if counter_file.exists():
                with open(counter_file, 'r') as f:
                    counters = json.load(f)
                logger.info(f"Loaded ticker counters for {len(counters)} tickers")
                return counters
        except Exception as e:
            logger.warning(f"Could not load ticker counters: {e}")

        return {}

    def _load_ticker_alert_history(self):
        """Load detailed ticker alert history from file"""
        history_file = self.output_dir / "ticker_alert_history.json"
        try:
            if history_file.exists():
                with open(history_file, 'r') as f:
                    history = json.load(f)
                logger.info(f"Loaded alert history for {len(history)} tickers")
                return history
        except Exception as e:
            logger.warning(f"Could not load ticker alert history: {e}")

        return {}

    def _load_telegram_last_sent(self):
        """Load telegram last sent times from file"""
        last_sent_file = self.output_dir / "telegram_last_sent.json"
        try:
            if last_sent_file.exists():
                with open(last_sent_file, 'r') as f:
                    last_sent = json.load(f)
                logger.info(f"Loaded telegram last sent times for {len(last_sent)} tickers")
                return last_sent
        except Exception as e:
            logger.warning(f"Could not load telegram last sent times: {e}")

        return {}

    def _save_telegram_last_sent(self):
        """Save telegram last sent times to file"""
        try:
            last_sent_file = self.output_dir / "telegram_last_sent.json"
            with open(last_sent_file, 'w') as f:
                json.dump(self.telegram_last_sent, f, indent=2)
            logger.debug("Telegram last sent times saved")
        except Exception as e:
            logger.error(f"Could not save telegram last sent times: {e}")

    def _save_ticker_data(self):
        """Save ticker counters and history to files"""
        try:
            # Save counters
            counter_file = self.output_dir / "ticker_counters.json"
            with open(counter_file, 'w') as f:
                json.dump(self.ticker_counters, f, indent=2)

            # Save detailed history
            history_file = self.output_dir / "ticker_alert_history.json"
            with open(history_file, 'w') as f:
                json.dump(self.ticker_alert_history, f, indent=2, default=str)

            # Save telegram last sent times
            self._save_telegram_last_sent()

            logger.debug("Ticker tracking data saved")
        except Exception as e:
            logger.error(f"Could not save ticker data: {e}")

    def _update_ticker_counter(self, ticker, alert_type, alert_data=None):
        """Update ticker appearance counter and history"""
        # Update main counter
        if ticker not in self.ticker_counters:
            self.ticker_counters[ticker] = 0
        self.ticker_counters[ticker] += 1

        # Update detailed history
        if ticker not in self.ticker_alert_history:
            self.ticker_alert_history[ticker] = {
                'total_appearances': 0,
                'alert_types': {},
                'first_seen': datetime.now().isoformat(),
                'last_seen': datetime.now().isoformat(),
                'recent_alerts': []
            }

        history = self.ticker_alert_history[ticker]
        history['total_appearances'] += 1
        history['last_seen'] = datetime.now().isoformat()

        # Track by alert type
        if alert_type not in history['alert_types']:
            history['alert_types'][alert_type] = 0
        history['alert_types'][alert_type] += 1

        # Keep recent alerts (last 10)
        alert_record = {
            'timestamp': datetime.now().isoformat(),
            'alert_type': alert_type,
            'data': alert_data
        }
        history['recent_alerts'].append(alert_record)
        if len(history['recent_alerts']) > 10:
            history['recent_alerts'].pop(0)

        # Check for immediate spike alert (very big price spikes)
        if alert_data and alert_type == 'price_spike':
            change_pct = alert_data.get('change_pct', 0)
            if change_pct >= self.immediate_spike_threshold:
                logger.info(f"🚨 IMMEDIATE SPIKE DETECTED: {ticker} +{change_pct:.1f}% (≥{self.immediate_spike_threshold:.0f}%)")
                print(f"🚨 IMMEDIATE SPIKE: {ticker} +{change_pct:.1f}% - Sending immediate alert!")
                self._send_immediate_spike_alert(ticker, alert_data)
                return  # Skip regular high frequency check since we already sent immediate alert

        # Check if this ticker qualifies for regular Telegram notification
        if alert_data:
            self._check_high_frequency_alerts(ticker, alert_data)

    def _add_counter_to_alerts(self, alerts, default_alert_type):
        """Add appearance counter to alert data and sort by frequency"""
        # First pass: Update counters and add appearance_count to all alerts
        for alert in alerts:
            ticker = alert['ticker']
            
            # Use individual alert_type if available, otherwise use default
            individual_alert_type = alert.get('alert_type', default_alert_type)

            # Update counter
            self._update_ticker_counter(ticker, individual_alert_type, alert)

            # Add counter to alert data
            alert['appearance_count'] = self.ticker_counters.get(ticker, 0)
            alert['alert_types_count'] = len(self.ticker_alert_history.get(ticker, {}).get('alert_types', {}))

        # Second pass: Sort by appearance count (highest first), then by the original metric
        try:
            if default_alert_type == 'volume_climber':
                alerts.sort(key=lambda x: (x.get('appearance_count', 0), x.get('rank_change', 0)), reverse=True)
            elif default_alert_type == 'volume_newcomer':
                alerts.sort(key=lambda x: (x.get('appearance_count', 0), -x.get('current_rank', 999)), reverse=True)
            elif default_alert_type in ['price_spike', 'premarket_price', 'flat_to_spike']:
                alerts.sort(key=lambda x: (x.get('appearance_count', 0), abs(x.get('change_pct', x.get('premarket_change', 0)))), reverse=True)
            elif default_alert_type == 'premarket_volume':
                alerts.sort(key=lambda x: (x.get('appearance_count', 0), x.get('premarket_volume', 0)), reverse=True)
            elif default_alert_type == 'sustained_positive':
                alerts.sort(key=lambda x: (x.get('appearance_count', 0), x.get('change_from_prev_close', 0)), reverse=True)
        except Exception as e:
            logger.error(f"Error sorting alerts for {default_alert_type}: {e}")
            # Fall back to simple sort by appearance count only
            alerts.sort(key=lambda x: x.get('appearance_count', 0), reverse=True)

        return alerts

    def get_volume_screener_data(self, limit=200):
        """Get small cap data sorted by volume descending"""
        try:
            # Remove the problematic .where() filters - do manual filtering instead
            query = (Query()
                    .select(
                        'name',                      # Symbol/Name
                        'relative_volume_10d_calc',  # Relative volume
                        'volume',                    # Volume (primary sort)
                        'Value.Traded',             # Price * vol
                        'change_from_open',         # Change from open %
                        'change|5',                 # Change %
                        'close',                    # Price
                        'float_shares_outstanding', # Float
                        'premarket_change',         # Pre-market change %
                        'premarket_volume',         # Pre-market volume
                        'sector',                   # Sector
                        'exchange'                  # Exchange
                    )
                    .order_by('premarket_volume', ascending=False)  # Sort by premarket volume descending
                    .limit(limit * 3))  # Get more data to filter manually

            logger.info("Fetching volume screener data...")
            data = query.get_scanner_data(cookies=self.cookies)

            # Process the data
            if isinstance(data, tuple) and len(data) == 2:
                total_count, df_data = data
                if hasattr(df_data, 'to_dict'):
                    all_records = df_data.to_dict('records')
                    logger.info(f"Retrieved {len(all_records)} total records")

                    # Manual filtering for price < $20 and no OTC
                    filtered_records = []
                    for record in all_records:
                        price = record.get('close', 999)
                        exchange = record.get('exchange', '').upper()

                        if price < 20 and exchange != 'OTC':
                            filtered_records.append(record)

                        # Stop when we have enough filtered records
                        if len(filtered_records) >= limit:
                            break

                    logger.info(f"After filtering (price < $20, no OTC): {len(filtered_records)} records")
                    # Update prices with Alpaca for real-time data
                    filtered_records = self._update_prices_with_alpaca(filtered_records)
                    return filtered_records
                else:
                    logger.error(f"Unexpected data format: {type(df_data)}")
                    return None
            else:
                logger.error(f"Unexpected response format: {type(data)}")
                return None

        except Exception as e:
            logger.error(f"Error getting volume screener data: {e}")
            # Try even simpler query if the above fails
            try:
                logger.info("Trying simplified query without all columns...")
                simple_query = (Query()
                              .select('name', 'volume', 'close', 'change|5', 'premarket_change','premarket_volume', 'sector', 'exchange', 'float_shares_outstanding')
                              .order_by('premarket_volume', ascending=False)
                              .limit(limit * 2))

                data = simple_query.get_scanner_data(cookies=self.cookies)

                if isinstance(data, tuple) and len(data) == 2:
                    total_count, df_data = data
                    if hasattr(df_data, 'to_dict'):
                        all_records = df_data.to_dict('records')
                        logger.info(f"Retrieved {len(all_records)} records with simplified query")

                        # Manual filtering
                        filtered_records = []
                        for record in all_records:
                            price = record.get('close', 999)
                            exchange = record.get('exchange', '').upper()

                            if price < 20 and exchange != 'OTC':
                                filtered_records.append(record)

                            if len(filtered_records) >= limit:
                                break

                        logger.info(f"Simplified query filtered results: {len(filtered_records)} records")
                        # Update prices with Alpaca for real-time data
                        filtered_records = self._update_prices_with_alpaca(filtered_records)
                        return filtered_records

            except Exception as e2:
                logger.error(f"Simplified query also failed: {e2}")
                return None

    def analyze_volume_movement(self, current_data, previous_data):
        """Analyze which tickers are moving up in volume rankings"""
        if not previous_data:
            return [], []

        # Create ranking maps
        current_rankings = {record['name']: idx for idx, record in enumerate(current_data)}
        previous_rankings = {record['name']: idx for idx, record in enumerate(previous_data)}

        volume_climbers = []
        volume_newcomers = []

        for ticker, current_rank in current_rankings.items():
            if ticker in previous_rankings:
                previous_rank = previous_rankings[ticker]
                rank_change = previous_rank - current_rank  # Positive = moved up

                if rank_change > 5:  # Moved up at least 5 positions
                    # Get current data for this ticker
                    current_ticker_data = next((r for r in current_data if r['name'] == ticker), None)
                    if current_ticker_data:
                        change_pct = current_ticker_data.get('change|5', 0)

                        # ONLY ALERT IF PRICE IS ALSO GOING UP (long trades only)
                        if change_pct > 0:  # Must have positive price movement
                            volume_climbers.append({
                                'ticker': ticker,
                                'rank_change': rank_change,
                                'current_rank': current_rank + 1,  # 1-based ranking
                                'previous_rank': previous_rank + 1,
                                'volume': current_ticker_data.get('volume', 0),
                                'price': current_ticker_data.get('close', 0),
                                'change_pct': change_pct,
                                'relative_volume': current_ticker_data.get('relative_volume_10d_calc', 0),
                                'sector': current_ticker_data.get('sector', 'Unknown'),
                                'change_from_open': current_ticker_data.get('change_from_open', 0)
                            })
            else:
                # New ticker in top rankings
                if current_rank < 50:  # Only care about top 50 newcomers
                    current_ticker_data = next((r for r in current_data if r['name'] == ticker), None)
                    if current_ticker_data:
                        change_pct = current_ticker_data.get('change|5', 0)

                        # ONLY ALERT IF PRICE IS ALSO GOING UP (long trades only)
                        if change_pct > 0:  # Must have positive price movement
                            volume_newcomers.append({
                                'ticker': ticker,
                                'current_rank': current_rank + 1,
                                'volume': current_ticker_data.get('volume', 0),
                                'price': current_ticker_data.get('close', 0),
                                'change_pct': change_pct,
                                'relative_volume': current_ticker_data.get('relative_volume_10d_calc', 0),
                                'sector': current_ticker_data.get('sector', 'Unknown'),
                                'change_from_open': current_ticker_data.get('change_from_open', 0)
                            })

        # Sort by rank improvement
        volume_climbers.sort(key=lambda x: x['rank_change'], reverse=True)
        volume_newcomers.sort(key=lambda x: x['current_rank'])

        # Add counters and re-sort by frequency
        volume_climbers = self._add_counter_to_alerts(volume_climbers, 'volume_climber')
        volume_newcomers = self._add_counter_to_alerts(volume_newcomers, 'volume_newcomer')

        return volume_climbers, volume_newcomers

    def _detect_flat_period(self, ticker, current_price, current_time):
        """
        Detect if a ticker was in a flat period before the current spike
        
        Args:
            ticker: Stock symbol
            current_price: Current stock price
            current_time: Current timestamp
            
        Returns:
            dict: {
                'is_flat': bool,
                'flat_duration_minutes': int,
                'flat_volatility': float,
                'flat_avg_price': float,
                'flat_price_range': tuple
            }
        """
        if ticker not in self.flat_period_history:
            self.flat_period_history[ticker] = []
        
        # Add current price data
        self.flat_period_history[ticker].append({
            'timestamp': current_time,
            'price': current_price
        })
        
        # Clean old data (keep only data within the flat detection window)
        cutoff_time = current_time - timedelta(seconds=self.flat_period_window)
        self.flat_period_history[ticker] = [
            entry for entry in self.flat_period_history[ticker]
            if entry['timestamp'] > cutoff_time
        ]
        
        # Need at least several data points to determine flatness
        price_history = self.flat_period_history[ticker]
        if len(price_history) < 3:
            return {
                'is_flat': False,
                'flat_duration_minutes': 0,
                'flat_volatility': 0,
                'flat_avg_price': current_price,
                'flat_price_range': (current_price, current_price),
                'reason': 'insufficient_data'
            }
        
        # Calculate price statistics over the window
        prices = [entry['price'] for entry in price_history]
        avg_price = sum(prices) / len(prices)
        min_price = min(prices)
        max_price = max(prices)
        
        # Calculate volatility as percentage range
        if avg_price > 0:
            volatility = ((max_price - min_price) / avg_price) * 100
        else:
            volatility = 0
        
        # Calculate duration of the period
        if len(price_history) >= 2:
            duration_seconds = (price_history[-1]['timestamp'] - price_history[0]['timestamp']).total_seconds()
            duration_minutes = duration_seconds / 60
        else:
            duration_minutes = 0
        
        # Determine if this constitutes a "flat" period
        is_flat = (
            volatility <= self.flat_volatility_threshold and
            duration_minutes >= (self.min_flat_duration / 60)  # Convert to minutes
        )
        
        return {
            'is_flat': is_flat,
            'flat_duration_minutes': duration_minutes,
            'flat_volatility': volatility,
            'flat_avg_price': avg_price,
            'flat_price_range': (min_price, max_price),
            'reason': 'flat_detected' if is_flat else f'volatility_{volatility:.1f}%_duration_{duration_minutes:.1f}min'
        }

    def analyze_price_spikes(self, current_data, time_window_minutes=10):
        """Analyze which tickers have the biggest POSITIVE price increases (long trades only)"""
        price_spikes = []

        # Track price changes
        current_time = datetime.now()

        for record in current_data:
            ticker = record.get('name')
            current_price = record.get('close', 0)
            change_pct = record.get('change|5', 0)

            # ONLY ALERT ON POSITIVE PRICE MOVEMENTS (for long trades)
            if ticker and current_price > 0 and change_pct > 0:  # Must be positive change
                # Update price history
                if ticker not in self.price_history:
                    self.price_history[ticker] = []

                self.price_history[ticker].append({
                    'timestamp': current_time,
                    'price': current_price,
                    'change_pct': change_pct
                })

                # Keep only recent data
                cutoff_time = current_time - timedelta(minutes=time_window_minutes)
                self.price_history[ticker] = [
                    entry for entry in self.price_history[ticker]
                    if entry['timestamp'] > cutoff_time
                ]

                # Detect flat period before potential spike
                flat_analysis = self._detect_flat_period(ticker, current_price, current_time)
                
                # Analyze price movement if we have enough history
                if len(self.price_history[ticker]) >= 2:
                    oldest_entry = self.price_history[ticker][0]
                    price_change = ((current_price - oldest_entry['price']) / oldest_entry['price']) * 100

                    # Significant POSITIVE price spike criteria (long trades only) - Enhanced flat-to-spike detection
                    change_from_open = record.get('change_from_open', 0)
                    if (change_pct > 10 or price_change > self.flat_to_spike_threshold) and current_price < 20 and change_pct > 0:
                        # Determine if this is a true flat-to-spike or just a regular spike
                        alert_type = 'flat_to_spike' if flat_analysis['is_flat'] else 'price_spike'
                        
                        spike_data = {
                            'ticker': ticker,
                            'current_price': current_price,
                            'change_pct': change_pct,
                            'price_change_window': price_change,
                            'volume': record.get('volume', 0),
                            'relative_volume': record.get('relative_volume_10d_calc', 0),
                            'sector': record.get('sector', 'Unknown'),
                            'time_window': time_window_minutes,
                            'alert_type': alert_type,
                            'flat_analysis': flat_analysis,
                            'change_from_open': record.get('change_from_open', 0)
                        }
                        
                        price_spikes.append(spike_data)
                        
                elif change_pct > 10:  # First time seeing this ticker but significant positive move
                    # For new tickers, we can't determine flat period, so mark as regular spike
                    spike_data = {
                        'ticker': ticker,
                        'current_price': current_price,
                        'change_pct': change_pct,
                        'price_change_window': change_pct,
                        'volume': record.get('volume', 0),
                        'relative_volume': record.get('relative_volume_10d_calc', 0),
                        'sector': record.get('sector', 'Unknown'),
                        'time_window': time_window_minutes,
                        'alert_type': 'price_spike',  # Can't confirm flat period for new ticker
                        'flat_analysis': flat_analysis,
                        'change_from_open': record.get('change_from_open', 0)
                    }
                    
                    price_spikes.append(spike_data)

        # Sort by biggest POSITIVE price increases
        price_spikes.sort(key=lambda x: x['change_pct'], reverse=True)

        # Add counters and re-sort by frequency
        price_spikes = self._add_counter_to_alerts(price_spikes, 'price_spike')

        return price_spikes

    def analyze_premarket_activity(self, current_data, previous_data):
        """Analyze pre-market volume and POSITIVE price changes (long trades only)"""
        premarket_volume_alerts = []
        premarket_price_alerts = []

        if not previous_data:
            # For first scan, just identify significant POSITIVE pre-market activity
            for record in current_data:
                ticker = record.get('name')
                premarket_change = record.get('premarket_change', 0)
                premarket_volume = record.get('premarket_volume', 0)

                # Alert on significant POSITIVE pre-market price changes only (long trades)
                if premarket_change > 5:  # ONLY positive moves > 5%
                    # Calculate actual current premarket price (not previous day's close)
                    close_price = record.get('close', 0)
                    current_premarket_price = close_price * (1 + premarket_change / 100)

                    # Check for after-hours flat to premarket spike pattern
                    ah_analysis = self._detect_afterhours_flat_period(ticker)
                    alert_type = 'significant_premarket_move'

                    # If after-hours was flat and we have a significant premarket spike, mark as special pattern
                    if ah_analysis['was_flat_afterhours'] and premarket_change > 10:
                        alert_type = 'afterhours_flat_to_premarket_spike'

                    premarket_price_alerts.append({
                        'ticker': ticker,
                        'premarket_change': premarket_change,
                        'current_price': current_premarket_price,
                        'volume': record.get('volume', 0),
                        'premarket_relative_volume': record.get('premarket_relative_volume', 0),
                        'sector': record.get('sector', 'Unknown'),
                        'alert_type': alert_type,
                        'change_from_open': record.get('change_from_open', 0),
                        'afterhours_analysis': ah_analysis
                    })

                # Alert on high pre-market volume (if available)
                if premarket_volume > 100000:  # > 100k pre-market volume
                    # Calculate actual current premarket price (not previous day's close)
                    close_price = record.get('close', 0)
                    current_premarket_price = close_price * (1 + premarket_change / 100)

                    premarket_volume_alerts.append({
                        'ticker': ticker,
                        'premarket_volume': premarket_volume,
                        'current_price': current_premarket_price,
                        'premarket_change': premarket_change,
                        'premarket_relative_volume': record.get('premarket_relative_volume', 0),
                        'sector': record.get('sector', 'Unknown'),
                        'alert_type': 'high_premarket_volume',
                        'change_from_open': record.get('change_from_open', 0)
                    })

            return premarket_volume_alerts, premarket_price_alerts

        # Compare with previous data for trends
        current_premarket = {record['name']: record for record in current_data}
        previous_premarket = {record['name']: record for record in previous_data}

        for ticker, current_record in current_premarket.items():
            current_pm_change = current_record.get('premarket_change', 0)
            current_pm_volume = current_record.get('premarket_volume', 0)

            if ticker in previous_premarket:
                previous_record = previous_premarket[ticker]
                previous_pm_change = previous_record.get('premarket_change', 0)
                previous_pm_volume = previous_record.get('premarket_volume', 0)

                # Pre-market price acceleration - ONLY POSITIVE moves (long trades)
                pm_change_acceleration = current_pm_change - previous_pm_change
                if pm_change_acceleration > 3 and current_pm_change > 0:  # Must be positive and accelerating up
                    # Calculate actual current premarket price (not previous day's close)
                    close_price = current_record.get('close', 0)
                    current_premarket_price = close_price * (1 + current_pm_change / 100)

                    premarket_price_alerts.append({
                        'ticker': ticker,
                        'premarket_change': current_pm_change,
                        'premarket_change_acceleration': pm_change_acceleration,
                        'current_price': current_premarket_price,
                        'volume': current_record.get('volume', 0),
                        'premarket_relative_volume': current_record.get('premarket_relative_volume', 0),
                        'sector': current_record.get('sector', 'Unknown'),
                        'alert_type': 'premarket_acceleration',
                        'change_from_open': current_record.get('change_from_open', 0)
                    })

                # Pre-market volume surge (regardless of price direction)
                if previous_pm_volume > 0:
                    pm_volume_change = ((current_pm_volume - previous_pm_volume) / previous_pm_volume) * 100
                    if pm_volume_change > 50:  # 50%+ increase in pre-market volume
                        # Calculate actual current premarket price (not previous day's close)
                        close_price = current_record.get('close', 0)
                        current_premarket_price = close_price * (1 + current_pm_change / 100)

                        premarket_volume_alerts.append({
                            'ticker': ticker,
                            'premarket_volume': current_pm_volume,
                            'premarket_volume_change': pm_volume_change,
                            'current_price': current_premarket_price,
                            'premarket_change': current_pm_change,
                            'premarket_relative_volume': current_record.get('premarket_relative_volume', 0),
                            'sector': current_record.get('sector', 'Unknown'),
                            'alert_type': 'premarket_volume_surge',
                            'change_from_open': current_record.get('change_from_open', 0)
                        })
            else:
                # New pre-market activity - ONLY POSITIVE moves (long trades)
                if current_pm_change > 3:  # New significant POSITIVE pre-market move
                    # Calculate actual current premarket price (not previous day's close)
                    close_price = current_record.get('close', 0)
                    current_premarket_price = close_price * (1 + current_pm_change / 100)

                    # Check for after-hours flat to premarket spike pattern
                    ah_analysis = self._detect_afterhours_flat_period(ticker)
                    alert_type = 'new_premarket_move'

                    # If after-hours was flat and we have a significant premarket spike, mark as special pattern
                    if ah_analysis['was_flat_afterhours'] and current_pm_change > 10:
                        alert_type = 'afterhours_flat_to_premarket_spike'

                    premarket_price_alerts.append({
                        'ticker': ticker,
                        'premarket_change': current_pm_change,
                        'current_price': current_premarket_price,
                        'volume': current_record.get('volume', 0),
                        'premarket_relative_volume': current_record.get('premarket_relative_volume', 0),
                        'sector': current_record.get('sector', 'Unknown'),
                        'alert_type': alert_type,
                        'change_from_open': current_record.get('change_from_open', 0),
                        'afterhours_analysis': ah_analysis
                    })

        # Sort alerts - price alerts by biggest POSITIVE moves
        premarket_price_alerts.sort(key=lambda x: x['premarket_change'], reverse=True)  # Only positive now
        premarket_volume_alerts.sort(key=lambda x: x.get('premarket_volume', 0), reverse=True)

        # Add counters and re-sort by frequency
        premarket_price_alerts = self._add_counter_to_alerts(premarket_price_alerts, 'premarket_price')
        premarket_volume_alerts = self._add_counter_to_alerts(premarket_volume_alerts, 'premarket_volume')

        return premarket_volume_alerts, premarket_price_alerts

    def analyze_sustained_positive(self, current_data):
        """Analyze tickers maintaining >10% gain from previous day's close (sustained positive momentum)"""
        sustained_positive_alerts = []

        for record in current_data:
            ticker = record.get('name')
            # Use change from previous close (includes after-market) instead of change from open
            change_from_prev_close = record.get('change_from_prev_close', 0)

            # Check if ticker is maintaining >10% gain from previous day's close
            if change_from_prev_close > 10:
                sustained_positive_alerts.append({
                    'ticker': ticker,
                    'change_from_prev_close': change_from_prev_close,
                    'current_price': record.get('close', 0),
                    'previous_close': record.get('previous_close', 0),
                    'change_pct': record.get('change|5', 0),
                    'volume': record.get('volume', 0),
                    'relative_volume': record.get('relative_volume_10d_calc', 0),
                    'sector': record.get('sector', 'Unknown'),
                    'alert_type': 'sustained_positive'
                })

        # Sort by biggest sustained gains
        sustained_positive_alerts.sort(key=lambda x: x['change_from_prev_close'], reverse=True)

        # Add counters and re-sort by frequency
        sustained_positive_alerts = self._add_counter_to_alerts(sustained_positive_alerts, 'sustained_positive')

        return sustained_positive_alerts

    def save_alerts(self, volume_climbers, volume_newcomers, price_spikes, premarket_volume_alerts, premarket_price_alerts, sustained_positive_alerts, timestamp):
        """Save movement alerts to files"""
        alerts_data = {
            'timestamp': timestamp.isoformat(),
            'volume_climbers': volume_climbers[:10],  # Top 10
            'volume_newcomers': volume_newcomers[:10],  # Top 10
            'price_spikes': price_spikes[:10],  # Top 10
            'premarket_volume_alerts': premarket_volume_alerts[:10],  # Top 10
            'premarket_price_alerts': premarket_price_alerts[:10],  # Top 10
            'sustained_positive_alerts': sustained_positive_alerts[:10],  # Top 10
            'summary': {
                'total_volume_climbers': len(volume_climbers),
                'total_newcomers': len(volume_newcomers),
                'total_price_spikes': len(price_spikes),
                'total_premarket_volume_alerts': len(premarket_volume_alerts),
                'total_premarket_price_alerts': len(premarket_price_alerts),
                'total_sustained_positive_alerts': len(sustained_positive_alerts)
            }
        }

        # Save detailed alerts
        alerts_file = self.output_dir / f"alerts_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
        with open(alerts_file, 'w') as f:
            json.dump(alerts_data, f, indent=2, default=str)

        # Save summary to latest file
        latest_file = self.output_dir / "latest_alerts.json"
        with open(latest_file, 'w') as f:
            json.dump(alerts_data, f, indent=2, default=str)

        logger.info(f"Alerts saved: {alerts_file}")
        return alerts_data

    def print_alerts(self, volume_climbers, volume_newcomers, price_spikes, premarket_volume_alerts, premarket_price_alerts, sustained_positive_alerts):
        """Print movement alerts to console"""
        print("\n" + "="*80)
        print(f"🚨 MOMENTUM ALERTS - {datetime.now().strftime('%H:%M:%S')}")
        print("="*80)

        # Show trending tickers summary first
        try:
            self._print_trending_summary()
        except Exception as e:
            logger.error(f"Error printing trending summary: {e}")

        if volume_climbers:
            print(f"\n📈 VOLUME CLIMBERS ({len(volume_climbers)} found) - Sorted by Frequency:")
            print("-" * 70)
            for climber in volume_climbers[:5]:  # Top 5
                try:
                    count = climber.get('appearance_count', 1)  # Default to 1 if missing
                    rel_vol = climber.get('relative_volume', 0)
                    rel_vol_str = f"{rel_vol:.1f}x" if rel_vol > 0 else "N/A"
                    change_pct = climber.get('change_pct', 0)
                    
                    # Mark immediate spikes
                    spike_marker = " 🚨" if change_pct >= self.immediate_spike_threshold else ""
                    
                    print(f"  {climber['ticker']:6} [{count:2d}x] | Rank: {climber['previous_rank']:3d} → {climber['current_rank']:3d} "
                          f"(+{climber['rank_change']:2d}) | Vol: {climber['volume']:>10,} ({rel_vol_str}) | "
                          f"${climber['price']:6.2f} ({change_pct:+5.1f}%{spike_marker}) | {climber.get('sector', 'Unknown')}")
                except Exception as e:
                    logger.error(f"Error printing volume climber {climber.get('ticker', 'Unknown')}: {e}")

        if volume_newcomers:
            print(f"\n🆕 NEW HIGH VOLUME ({len(volume_newcomers)} found) - Sorted by Frequency:")
            print("-" * 70)
            for newcomer in volume_newcomers[:5]:  # Top 5
                try:
                    count = newcomer.get('appearance_count', 1)
                    rel_vol = newcomer.get('relative_volume', 0)
                    rel_vol_str = f"{rel_vol:.1f}x" if rel_vol > 0 else "N/A"
                    change_pct = newcomer.get('change_pct', 0)
                    
                    # Mark immediate spikes
                    spike_marker = " 🚨" if change_pct >= self.immediate_spike_threshold else ""
                    
                    print(f"  {newcomer['ticker']:6} [{count:2d}x] | NEW → Rank {newcomer['current_rank']:3d} | "
                          f"Vol: {newcomer['volume']:>10,} ({rel_vol_str}) | ${newcomer['price']:6.2f} "
                          f"({change_pct:+5.1f}%{spike_marker}) | {newcomer.get('sector', 'Unknown')}")
                except Exception as e:
                    logger.error(f"Error printing volume newcomer {newcomer.get('ticker', 'Unknown')}: {e}")

        if price_spikes:
            print(f"\n🔥 PRICE SPIKES ({len(price_spikes)} found) - Sorted by Frequency:")
            print("-" * 70)
            for spike in price_spikes[:5]:  # Top 5
                try:
                    count = spike.get('appearance_count', 1)
                    rel_vol = spike.get('relative_volume', 0)
                    rel_vol_str = f"{rel_vol:.1f}x" if rel_vol > 0 else "N/A"
                    change_pct = spike.get('change_pct', 0)
                    alert_type = spike.get('alert_type', 'price_spike')
                    flat_analysis = spike.get('flat_analysis', {})
                    
                    # Mark immediate spikes
                    spike_marker = " 🚨" if change_pct >= self.immediate_spike_threshold else ""
                    
                    # Mark flat-to-spike pattern
                    pattern_marker = ""
                    if alert_type == 'flat_to_spike':
                        flat_duration = flat_analysis.get('flat_duration_minutes', 0)
                        flat_volatility = flat_analysis.get('flat_volatility', 0)
                        pattern_marker = f" 🎯FLAT→SPIKE({flat_duration:.0f}m,{flat_volatility:.1f}%)"
                    
                    print(f"  {spike['ticker']:6} [{count:2d}x] | ${spike['current_price']:6.2f} ({change_pct:+5.1f}%{spike_marker}) | "
                          f"Vol: {spike.get('volume', 0):>10,} ({rel_vol_str}) | {spike.get('sector', 'Unknown')}{pattern_marker}")
                except Exception as e:
                    logger.error(f"Error printing price spike {spike.get('ticker', 'Unknown')}: {e}")

        if premarket_volume_alerts:
            print(f"\n🌅 PRE-MARKET VOLUME ({len(premarket_volume_alerts)} found) - Sorted by Frequency:")
            print("-" * 70)
            for alert in premarket_volume_alerts[:5]:  # Top 5
                try:
                    count = alert.get('appearance_count', 1)
                    rel_vol = alert.get('premarket_relative_volume', 0)
                    rel_vol_str = f"{rel_vol:.1f}x" if rel_vol > 0 else "N/A"
                    pm_change = alert.get('premarket_change', 0)

                    # Mark immediate spikes
                    spike_marker = " 🚨" if pm_change >= self.immediate_spike_threshold else ""

                    if alert.get('alert_type') == 'premarket_volume_surge':
                        print(f"  {alert['ticker']:6} [{count:2d}x] | PM Vol: {alert.get('premarket_volume', 0):>8,} "
                              f"(+{alert.get('premarket_volume_change', 0):5.1f}%) PM RelVol: {rel_vol_str} | ${alert.get('current_price', 0):6.2f} "
                              f"PM: {pm_change:+5.1f}%{spike_marker} | {alert.get('sector', 'Unknown')}")
                    else:
                        print(f"  {alert['ticker']:6} [{count:2d}x] | PM Vol: {alert.get('premarket_volume', 0):>8,} PM RelVol: {rel_vol_str} | "
                              f"${alert.get('current_price', 0):6.2f} PM: {pm_change:+5.1f}%{spike_marker} | {alert.get('sector', 'Unknown')}")
                except Exception as e:
                    logger.error(f"Error printing premarket volume alert {alert.get('ticker', 'Unknown')}: {e}")

        if premarket_price_alerts:
            print(f"\n🌄 PRE-MARKET MOVERS ({len(premarket_price_alerts)} found) - Sorted by Frequency:")
            print("-" * 70)
            for alert in premarket_price_alerts[:5]:  # Top 5
                try:
                    count = alert.get('appearance_count', 1)
                    rel_vol = alert.get('premarket_relative_volume', 0)
                    rel_vol_str = f"{rel_vol:.1f}x" if rel_vol > 0 else "N/A"
                    pm_change = alert.get('premarket_change', 0)

                    # Mark immediate spikes
                    spike_marker = " 🚨" if pm_change >= self.immediate_spike_threshold else ""

                    if alert.get('alert_type') == 'premarket_acceleration':
                        print(f"  {alert['ticker']:6} [{count:2d}x] | PM: {pm_change:+6.1f}% "
                              f"(Δ{alert.get('premarket_change_acceleration', 0):+5.1f}%{spike_marker}) PM RelVol: {rel_vol_str} | ${alert.get('current_price', 0):6.2f} | "
                              f"Vol: {alert.get('volume', 0):>8,} | {alert.get('sector', 'Unknown')}")
                    else:
                        print(f"  {alert['ticker']:6} [{count:2d}x] | PM: {pm_change:+6.1f}%{spike_marker} PM RelVol: {rel_vol_str} | "
                              f"${alert.get('current_price', 0):6.2f} | Vol: {alert.get('volume', 0):>8,} | {alert.get('sector', 'Unknown')}")
                except Exception as e:
                    logger.error(f"Error printing premarket price alert {alert.get('ticker', 'Unknown')}: {e}")

        if sustained_positive_alerts:
            print(f"\n💪 SUSTAINED POSITIVE ({len(sustained_positive_alerts)} found) - Sorted by Frequency:")
            print("-" * 70)
            for alert in sustained_positive_alerts[:5]:  # Top 5
                try:
                    count = alert.get('appearance_count', 1)
                    rel_vol = alert.get('relative_volume', 0)
                    rel_vol_str = f"{rel_vol:.1f}x" if rel_vol > 0 else "N/A"
                    change_from_prev_close = alert.get('change_from_prev_close', 0)
                    change_pct = alert.get('change_pct', 0)
                    spike_marker = " 🔥" if change_from_prev_close >= 25 else ""
                    print(f"  {alert['ticker']:6} [{count:2d}x] | From Prev Close: +{change_from_prev_close:5.1f}%{spike_marker} | "
                          f"5min: {change_pct:+5.1f}% | RelVol: {rel_vol_str} | "
                          f"${alert.get('current_price', 0):6.2f} | Vol: {alert.get('volume', 0):>8,} | {alert.get('sector', 'Unknown')}")
                except Exception as e:
                    logger.error(f"Error printing sustained positive alert {alert.get('ticker', 'Unknown')}: {e}")

        if not any([volume_climbers, volume_newcomers, price_spikes, premarket_volume_alerts, premarket_price_alerts, sustained_positive_alerts]):
            print("\n😴 No significant momentum detected this cycle.")

        print("="*80)

    def _print_trending_summary(self):
        """Print summary of most frequently appearing tickers"""
        if not self.ticker_counters:
            return

        # Get top trending tickers
        sorted_tickers = sorted(self.ticker_counters.items(), key=lambda x: x[1], reverse=True)
        top_tickers = sorted_tickers[:10]  # Top 10

        print(f"\n🔥 TOP TRENDING TICKERS (Most Frequent Alerts):")
        print("-" * 70)

        for i, (ticker, count) in enumerate(top_tickers[:5], 1):
            history = self.ticker_alert_history.get(ticker, {})
            alert_types = list(history.get('alert_types', {}).keys())
            alert_types_str = ', '.join(alert_types[:3])  # Show first 3 types
            if len(alert_types) > 3:
                alert_types_str += f" +{len(alert_types)-3}"

            print(f"  #{i:1d}. {ticker:6} | {count:2d} alerts | Types: {alert_types_str}")

        if len(top_tickers) > 5:
            others = ', '.join([f"{ticker}({count})" for ticker, count in top_tickers[5:10]])
            print(f"  Also trending: {others}")

    def run_single_scan(self):
        """Run a single scan and compare with previous data"""
        timestamp = datetime.now()
        logger.info(f"Starting scan cycle at {timestamp.strftime('%H:%M:%S')}")

        try:
            # Get current data
            current_data = self.get_volume_screener_data()
            if not current_data:
                logger.error("Failed to get current data")
                return

            # NEW: Check for paper trading exits before analyzing new movements
            self.check_paper_trading_exits(current_data)

            # Analyze movements
            previous_data = self.historical_data[-1] if self.historical_data else None

            try:
                volume_climbers, volume_newcomers = self.analyze_volume_movement(current_data, previous_data)
            except Exception as e:
                logger.error(f"Error analyzing volume movement: {e}")
                volume_climbers, volume_newcomers = [], []

            try:
                price_spikes = self.analyze_price_spikes(current_data)
            except Exception as e:
                logger.error(f"Error analyzing price spikes: {e}")
                price_spikes = []

            try:
                premarket_volume_alerts, premarket_price_alerts = self.analyze_premarket_activity(current_data, previous_data)
            except Exception as e:
                logger.error(f"Error analyzing premarket activity: {e}")
                premarket_volume_alerts, premarket_price_alerts = [], []

            try:
                sustained_positive_alerts = self.analyze_sustained_positive(current_data)
            except Exception as e:
                logger.error(f"Error analyzing sustained positive: {e}")
                sustained_positive_alerts = []

            # Print alerts with error handling
            try:
                self.print_alerts(volume_climbers, volume_newcomers, price_spikes, premarket_volume_alerts, premarket_price_alerts, sustained_positive_alerts)
            except Exception as e:
                logger.error(f"Error printing alerts: {e}")
                print(f"⚠️  Error displaying alerts: {e}")
                print(f"Found: {len(volume_climbers)} climbers, {len(volume_newcomers)} newcomers, "
                      f"{len(price_spikes)} price spikes, {len(premarket_volume_alerts)} PM volume, "
                      f"{len(premarket_price_alerts)} PM price alerts, {len(sustained_positive_alerts)} sustained positive")

            # Save alerts
            try:
                alerts_data = self.save_alerts(volume_climbers, volume_newcomers, price_spikes,
                                             premarket_volume_alerts, premarket_price_alerts, sustained_positive_alerts, timestamp)
            except Exception as e:
                logger.error(f"Error saving alerts: {e}")

            # Save ticker tracking data
            try:
                self._save_ticker_data()
            except Exception as e:
                logger.error(f"Error saving ticker data: {e}")

            # Store current data for next comparison
            self.historical_data.append(current_data)
            if len(self.historical_data) > self.max_history:
                self.historical_data.pop(0)  # Keep only recent history

            # Save raw data
            try:
                raw_file = self.output_dir / f"raw_data_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
                with open(raw_file, 'w') as f:
                    json.dump(current_data, f, indent=2, default=str)
            except Exception as e:
                logger.error(f"Error saving raw data: {e}")

            logger.info(f"Scan cycle completed. Found: {len(volume_climbers)} climbers, "
                       f"{len(volume_newcomers)} newcomers, {len(price_spikes)} price spikes, "
                       f"{len(premarket_volume_alerts)} PM volume alerts, {len(premarket_price_alerts)} PM price alerts, "
                       f"{len(sustained_positive_alerts)} sustained positive alerts")

        except Exception as e:
            logger.error(f"Critical error in scan cycle: {e}")
            print(f"⚠️  Scan cycle failed: {e}")
            print("Will retry in next cycle...")

    def run_continuous_monitoring(self):
        """Run continuous monitoring every 2 minutes"""
        # Create PID file when starting continuous monitoring
        self._create_pid_file()

        logger.info("🚀 Starting continuous volume momentum monitoring...")
        logger.info(f"📊 Scanning every {self.monitor_interval} seconds (2 minutes)")
        logger.info(f"🎯 Tracking: Volume climbers, newcomers, and price spikes")
        logger.info(f"🚨 IMMEDIATE SPIKE THRESHOLD: {self.immediate_spike_threshold:.0f}% (bypasses 3-alert rule)")
        logger.info(f"💾 Data saved to: {self.output_dir}")
        logger.info(f"📰 News headlines: Recent news with timestamps included in Telegram alerts")
        
        if self.enable_paper_trading and self.paper_trader:
            logger.info("📈 Paper Trading: ✅ ENABLED")
            logger.info("   📊 Strategy: Buy on alert + price > 9 EMA, Sell on price < 25 EMA")
            logger.info(f"   💰 Position Size: ${self.paper_trader.position_size} per trade")
        else:
            logger.info("📈 Paper Trading: ❌ DISABLED")

        if self.telegram_bot and self.telegram_chat_id:
            logger.info("📱 Telegram notifications: ✅ ENABLED")
            logger.info(f"📱 Alert threshold: 3+ alerts per ticker")
            logger.info(f"🚨 Immediate alerts: ≥{self.immediate_spike_threshold:.0f}% price spikes (no waiting!)")
            logger.info(f"📱 Rate limiting: {self.telegram_notification_interval/60:.0f} minutes between notifications per ticker")
            logger.info("⏰ Hourly list_flat notifications: ✅ ENABLED")
            logger.info("📰 Recent headlines (last 3 days) with timestamps will be included in alerts")
            logger.info("📊 Relative volume information included in alerts")
            logger.info(f"📝 Notifications logged to: {self.hourly_notifications_log}")
        else:
            logger.info("📱 Telegram notifications: ❌ DISABLED")
            logger.info("📰 News headlines: ❌ DISABLED (requires Telegram)")
            logger.info("⏰ Timestamps: ❌ DISABLED (requires Telegram)")
            logger.info("📊 Relative volume: ✅ ENABLED (shown in console)")
            if True:  # Always show this tip
                logger.info("   💡 Use --bot-token and --chat-id for immediate spike alerts with timestamped news & relative volume")
        logger.info("=" * 85)

        try:
            while True:
                try:
                    self.run_single_scan()

                    # Wait for next cycle
                    logger.info(f"⏱️  Waiting {self.monitor_interval} seconds until next scan...")
                    time.sleep(self.monitor_interval)

                except KeyboardInterrupt:
                    logger.info("🛑 Monitoring stopped by user")
                    break
                except Exception as e:
                    logger.error(f"Error in scan cycle: {e}")
                    logger.info("Continuing in 30 seconds...")
                    time.sleep(30)

        except KeyboardInterrupt:
            logger.info("🛑 Volume momentum monitoring stopped")
        finally:
            # Clean up PID file when exiting
            self._cleanup_pid_file()

    def reset_ticker_counters(self):
        """Reset all ticker counters and history"""
        self.ticker_counters = {}
        self.ticker_alert_history = {}
        self.telegram_last_sent = {}  # Reset Telegram rate limiting too
        self.session_alert_count = {}  # Reset session alert counts too
        self.disregarded_tickers.clear()  # Reset disregarded tickers too
        self.news_cache = {}  # Reset news cache too
        self._save_ticker_data()
        logger.info("🔄 Ticker counters, history, news cache, session alert counts, disregarded tickers, and Telegram rate limiting reset")

    def print_ticker_stats(self):
        """Print detailed ticker statistics"""
        if not self.ticker_counters:
            print("No ticker data available yet.")
            return

        print(f"\n📊 TICKER STATISTICS")
        print("=" * 60)

        sorted_tickers = sorted(self.ticker_counters.items(), key=lambda x: x[1], reverse=True)

        print(f"Total tracked tickers: {len(sorted_tickers)}")
        print(f"Most active ticker: {sorted_tickers[0][0]} ({sorted_tickers[0][1]} alerts)")
        print(f"Immediate spike threshold: {self.immediate_spike_threshold:.0f}%")

        print(f"\nTop 10 Most Active Tickers:")
        print("-" * 60)

        for i, (ticker, count) in enumerate(sorted_tickers[:10], 1):
            history = self.ticker_alert_history.get(ticker, {})
            alert_types = history.get('alert_types', {})
            types_str = ', '.join([f"{k}({v})" for k, v in alert_types.items()])

            print(f"{i:2d}. {ticker:6} | {count:3d} total | {types_str}")

    async def _process_telegram_command(self, text, chat_id):
        """Process incoming telegram commands from users"""
        if not text or not text.startswith('/'):
            return
            
        try:
            # Only process commands from the configured chat ID
            if str(chat_id) != str(self.telegram_chat_id):
                logger.warning(f"Ignoring command from unauthorized chat ID: {chat_id}")
                return
                
            parts = text.strip().split()
            command = parts[0].lower()
            
            if command == '/disregard' and len(parts) >= 2:
                ticker = parts[1].upper()
                if ticker not in self.disregarded_tickers:
                    self.disregarded_tickers.add(ticker)
                    response = f"✅ {ticker} alerts disabled for this session. You will no longer receive alerts for {ticker} until the next session."
                    logger.info(f"📵 User disregarded ticker: {ticker}")
                else:
                    response = f"ℹ️ {ticker} alerts are already disabled for this session."
                
                # Send confirmation
                await self.telegram_bot.send_message(
                    chat_id=self.telegram_chat_id,
                    text=response,
                    disable_web_page_preview=True
                )
                
            elif command == '/list_disregarded':
                if self.disregarded_tickers:
                    tickers_list = ', '.join(sorted(self.disregarded_tickers))
                    response = f"📵 Currently disregarded tickers: {tickers_list}"
                else:
                    response = "ℹ️ No tickers are currently disregarded."
                    
                # Send list
                await self.telegram_bot.send_message(
                    chat_id=self.telegram_chat_id,
                    text=response,
                    disable_web_page_preview=True
                )
                
            elif command == '/list_flat':
                try:
                    # Send initial status message
                    await self.telegram_bot.send_message(
                        chat_id=self.telegram_chat_id,
                        text="🔄 Fetching stocks in play (1x+ volume) by intraday movement...",
                        disable_web_page_preview=True
                    )

                    # Use the reusable method to generate content
                    response, error, tickers_data = self._generate_list_flat_content()

                    if error:
                        response = error
                    else:
                        logger.info(f"📋 Sent list of {len(tickers_data)} stocks sorted by intraday movement to user")

                    # Send the list
                    await self.telegram_bot.send_message(
                        chat_id=self.telegram_chat_id,
                        text=response,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )

                except Exception as e:
                    error_msg = f"❌ Error generating flat stocks list: {str(e)}"
                    logger.error(error_msg)
                    await self.telegram_bot.send_message(
                        chat_id=self.telegram_chat_id,
                        text=error_msg,
                        disable_web_page_preview=True
                    )

            elif command == '/help':
                response = (
                    "📱 Volume Momentum Tracker Commands:\n\n"
                    "• /disregard TICKER - Disable alerts for a ticker this session\n"
                    "• /list_disregarded - Show currently disregarded tickers\n"
                    "• /list_flat - Show top 15 stocks in play\n"
                    "  (Vol≥1.5x, Move≥2%, sorted by intraday movement)\n"
                    "• /help - Show this help message\n\n"
                    "Hourly updates sent automatically with list_flat data.\n\n"
                    "Example: /disregard AAPL"
                )

                # Send help
                await self.telegram_bot.send_message(
                    chat_id=self.telegram_chat_id,
                    text=response,
                    disable_web_page_preview=True
                )
                
        except Exception as e:
            logger.error(f"❌ Error processing Telegram command '{text}': {e}")

    def _start_telegram_listener(self):
        """Start listening for telegram messages in a separate thread"""
        if not self.telegram_bot or not self.telegram_chat_id:
            return
            
        try:
            import threading
            from telegram.ext import Application, MessageHandler, CommandHandler, filters
            
            async def message_handler(update, context):
                """Handle incoming messages"""
                if update.message and update.message.text:
                    logger.info(f"📱 Received message: '{update.message.text}' from chat {update.message.chat_id}")
                    await self._process_telegram_command(
                        update.message.text, 
                        update.message.chat_id
                    )
            
            # Create application
            app = Application.builder().token(self.telegram_bot.token).build()
            
            # Add command handlers
            app.add_handler(CommandHandler("disregard", message_handler))
            app.add_handler(CommandHandler("list_disregarded", message_handler))
            app.add_handler(CommandHandler("list_flat", message_handler))
            app.add_handler(CommandHandler("help", message_handler))
            
            # Add a general message handler to catch all other messages
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

            # Add hourly job for list_flat notification
            job_queue = app.job_queue
            if job_queue:
                # Schedule hourly list_flat notification (runs every hour)
                job_queue.run_repeating(
                    self._send_hourly_list_flat,
                    interval=3600,  # 1 hour in seconds
                    first=60,  # Start first job after 1 minute
                    name='hourly_list_flat'
                )
                logger.info("⏰ Scheduled hourly list_flat notifications")
            else:
                logger.warning("⚠️ Job queue not available - hourly notifications disabled")

            # Start polling in a separate thread
            def run_bot():
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    # Disable signal handling to avoid thread issues
                    app.run_polling(allowed_updates=["message"], stop_signals=None)
                except Exception as e:
                    logger.error(f"❌ Telegram bot polling error: {e}")
                    
            bot_thread = threading.Thread(target=run_bot, daemon=True)
            bot_thread.start()
            logger.info("📱 Telegram message listener started")
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to start Telegram listener: {e}")

    def test_telegram_bot(self):
        """Test Telegram bot connectivity and news fetching with timestamps"""
        if not self.telegram_bot or not self.telegram_chat_id:
            print("❌ Telegram bot not configured. Provide --bot-token and --chat-id parameters.")
            return False

        try:
            import asyncio

            # Test basic message sending
            test_message = (
                "🧪 Test message from Volume Momentum Tracker\n\n"
                "📊 If you see this, Telegram notifications are working correctly!\n\n"
                "📱 Notifications will be sent for every alert of tickers with 3+ total alerts "
                "(rate limited to once per 30 minutes per ticker).\n\n"
                f"🚨 IMMEDIATE ALERTS: Price spikes ≥{self.immediate_spike_threshold:.0f}% bypass the 3-alert rule!\n\n"
                "📰 Recent headlines (last 3 days) with timestamps will be included automatically.\n\n"
                "📊 Relative volume information is now included in all alerts."
            )

            # Handle async send_message properly
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            loop.run_until_complete(
                self.telegram_bot.send_message(self.telegram_chat_id, test_message)
            )
            print("✅ Test message sent successfully!")

            # Test news fetching with timestamps using multiple tickers
            test_tickers = ["AAPL", "TSLA", "NVDA"]  # Use popular tickers for better news availability

            for ticker in test_tickers:
                print(f"\n🧪 Testing news headline fetching for {ticker}...")
                news_headlines = self._get_recent_news(ticker, max_headlines=2)

                if news_headlines:
                    print(f"✅ Successfully fetched {len(news_headlines)} headlines for {ticker}")

                    # Send a test news message with timestamps and relative volume
                    news_test_message = f"📰 News Test for {ticker} (with enhanced timestamps and relative volume):\n\n"
                    for i, news_item in enumerate(news_headlines, 1):
                        time_info = news_item.get('time_ago', 'Unknown time')
                        source = news_item.get('source', 'Unknown source')
                        escaped_title = self._escape_markdown(news_item['title'])
                        news_test_message += f"{i}. ({time_info}) [{escaped_title}]({news_item['url']})\n"
                        news_test_message += f"   Source: {source}\n"

                    # Add sample relative volume info
                    news_test_message += f"\n📊 Sample Relative Volume: 2.5x (this would show actual data in real alerts)"
                    news_test_message += f"\n🚨 Immediate spike threshold: {self.immediate_spike_threshold:.0f}%"

                    loop.run_until_complete(
                        self.telegram_bot.send_message(
                            self.telegram_chat_id,
                            news_test_message,
                            parse_mode='Markdown',
                            disable_web_page_preview=True
                        )
                    )
                    print(f"✅ News headlines with timestamps test sent for {ticker}!")

                    # Print detailed debugging information
                    print(f"\n📰 Headlines found for {ticker} with detailed timestamp info:")
                    for i, news_item in enumerate(news_headlines, 1):
                        time_info = news_item.get('time_ago', 'Unknown time')
                        source = news_item.get('source', 'Unknown source')
                        pub_date = news_item.get('published_date', 'No date')
                        print(f"  {i}. ({time_info}) from {source}")
                        print(f"     Published: {pub_date}")
                        print(f"     Title: {news_item['title'][:80]}...")
                        print(f"     URL: {news_item['url'][:80]}...")
                        print()

                    # Test the first ticker only to avoid spamming
                    break
                else:
                    print(f"⚠️  No headlines found for {ticker}")
                    continue

            # Send a summary message
            summary_message = (
                "✅ Enhanced Features Testing Complete!\n\n"
                "🔧 New features:\n"
                "• Alert threshold lowered to 3+ alerts (from 5)\n"
                f"• 🚨 IMMEDIATE alerts for spikes ≥{self.immediate_spike_threshold:.0f}% (no waiting!)\n"
                "• Relative volume included in all alerts\n"
                "• Multiple news source fallbacks\n"
                "• Robust timestamp parsing\n"
                "• Graduated fallback times when timestamps fail\n"
                "• Detailed source attribution\n"
                "• Improved error handling\n\n"
                "📰 All news alerts will now show article age and relative volume!\n"
                f"🚨 Big spikes (≥{self.immediate_spike_threshold:.0f}%) get instant alerts!"
            )

            loop.run_until_complete(
                self.telegram_bot.send_message(self.telegram_chat_id, summary_message)
            )
            print("✅ Summary message sent!")

            return True

        except Exception as e:
            print(f"❌ Failed to send test message: {e}")
            import traceback
            print(f"Full error details: {traceback.format_exc()}")
            return False

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Volume Momentum Tracker - Real-time Small Caps Monitor with News Headlines, Timestamps, Relative Volume & IMMEDIATE BIG SPIKE ALERTS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Single scan:
    python volume_momentum_tracker.py --single

  Continuous monitoring with Telegram (immediate alerts for 25%+ spikes):
    python volume_momentum_tracker.py --continuous --bot-token "YOUR_TOKEN" --chat-id "YOUR_CHAT_ID"

  Set immediate alert threshold to 20%:
    python volume_momentum_tracker.py --continuous --immediate-threshold 20 --bot-token "YOUR_TOKEN" --chat-id "YOUR_CHAT_ID"

  Reset counters:
    python volume_momentum_tracker.py --reset

  Show statistics:
    python volume_momentum_tracker.py --stats

  Test Telegram bot and news fetching with immediate spike alerts:
    python volume_momentum_tracker.py --test-bot --bot-token "YOUR_TOKEN" --chat-id "YOUR_CHAT_ID"

  Kill running process:
    kill $(cat /tmp/screener.pid)
        """
    )

    # Action arguments (mutually exclusive)
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument('--single', action='store_true',
                            help='Run single scan and exit')
    action_group.add_argument('--continuous', action='store_true',
                            help='Start continuous monitoring (resets counters first)')
    action_group.add_argument('--reset', action='store_true',
                            help='Reset ticker counters and exit')
    action_group.add_argument('--stats', action='store_true',
                            help='Show ticker statistics and exit')
    action_group.add_argument('--test-bot', action='store_true',
                            help='Test Telegram bot connectivity and news fetching with immediate spike alerts, then exit')
    action_group.add_argument('--paper-report', action='store_true',
                            help='Generate paper trading performance report and exit')

    # Telegram configuration
    parser.add_argument('--bot-token', type=str,
                       help='Telegram bot token for notifications')
    parser.add_argument('--chat-id', type=str,
                       help='Telegram chat ID for notifications')

    # Immediate spike threshold
    parser.add_argument('--immediate-threshold', type=float, default=15.0,
                       help='Price change percentage that triggers immediate alerts (default: 15.0)')
    
    # Paper trading
    parser.add_argument('--paper-trading', action='store_true',
                       help='Enable paper trading simulation to test alert-based strategy')

    # Optional configuration
    parser.add_argument('--output-dir', type=str, default='premarket_momentum_data',
                       help='Directory to save data files (default: premarket_momentum_data)')
    parser.add_argument('--browser', type=str, default='firefox',
                       choices=['firefox', 'chrome', 'edge', 'safari'],
                       help='Browser to extract cookies from (default: firefox)')

    return parser.parse_args()

def main():
    """Main function to run the volume momentum tracker"""

    # Parse command line arguments
    args = parse_arguments()

    try:
        # Initialize the tracker
        tracker = VolumeMomentumTracker(
            output_dir=args.output_dir,
            browser=args.browser,
            telegram_bot_token=args.bot_token,
            telegram_chat_id=args.chat_id,
            immediate_spike_threshold=args.immediate_threshold,
            enable_paper_trading=args.paper_trading
        )

        # Print header
        print("🎯 Volume Momentum Tracker with News Headlines, Timestamps, Relative Volume & IMMEDIATE BIG SPIKE ALERTS (LONG TRADES)")
        print("=" * 110)
        print("Tracks small cap stocks (price < $20) for BULLISH momentum:")
        print("  📈 Volume ranking improvements (with positive price movement)")
        print("  🆕 New high-volume entries (with positive price movement)")
        print("  🔥 POSITIVE price spikes only")
        print("  🌅 Pre-market volume surges")
        print("  🌄 POSITIVE pre-market price movements only")
        print("  📊 Tracks frequency of alerts per ticker")
        print("  🔥 Shows trending tickers (most frequent)")
        print("  📱 Sends Telegram alerts for EVERY alert of tickers with 3+ alerts")
        print(f"  🚨 IMMEDIATE ALERTS: Price spikes ≥{args.immediate_threshold:.0f}% bypass the 3-alert rule!")
        print("  📰 Includes recent news headlines (last 3 days) with timestamps")
        print("  ⏰ Shows how old each news article is (e.g., '2h ago', '1d ago')")
        print("  📊 Shows relative volume (e.g., '3.2x' = 3.2x normal volume)")
        print("  📱 Rate limiting: 30 minutes between notifications per ticker")
        print("  ⏱️  Updates every 2 minutes")
        print("  🚀 LONG TRADES ONLY - No bearish alerts")
        print("=" * 110)

        # Show Telegram status
        if tracker.telegram_bot and tracker.telegram_chat_id:
            print("📱 Telegram notifications: ✅ ENABLED")
            print("📰 News headlines: ✅ ENABLED (last 3 days with timestamps)")
            print("⏰ Timestamps: ✅ ENABLED (shows article age)")
            print("📊 Relative volume: ✅ ENABLED (shows volume vs average)")
            print(f"📱 Alert threshold: 3+ alerts per ticker")
            print(f"🚨 IMMEDIATE alerts: ≥{args.immediate_threshold:.0f}% price spikes (no waiting required!)")
            print(f"📱 Rate limiting: {tracker.telegram_notification_interval/60:.0f} minutes between notifications per ticker")
        else:
            print("📱 Telegram notifications: ❌ DISABLED")
            print("📰 News headlines: ❌ DISABLED (requires Telegram)")
            print("⏰ Timestamps: ❌ DISABLED (requires Telegram)")
            print(f"🚨 IMMEDIATE alerts: ❌ DISABLED (requires Telegram for ≥{args.immediate_threshold:.0f}% spikes)")
            print("📊 Relative volume: ✅ ENABLED (shown in console)")
            if args.continuous:
                print("   💡 Use --bot-token and --chat-id for immediate spike alerts with timestamped news & relative volume")
        print("=" * 110)

        # Execute the requested action
        if args.single:
            print("\n🔍 Running single scan...")
            tracker.run_single_scan()
            print("\n✅ Single scan completed. Check output files for detailed data.")

        elif args.continuous:
            print("\n🔄 Resetting ticker counters before continuous monitoring...")
            tracker.reset_ticker_counters()
            print("✅ Counters reset. Starting continuous monitoring...")
            print(f"🚨 IMMEDIATE SPIKE THRESHOLD: {args.immediate_threshold:.0f}% (bypasses 3-alert rule)")
            print("Press Ctrl+C to stop")
            tracker.run_continuous_monitoring()

        elif args.reset:
            print("\n🔄 Resetting ticker counters and news cache...")
            tracker.reset_ticker_counters()
            print("✅ Ticker counters and news cache reset.")

        elif args.stats:
            print("\n📊 Ticker Statistics:")
            tracker.print_ticker_stats()

        elif args.test_bot:
            print(f"\n🧪 Testing Telegram bot and news fetching with immediate spike alerts (threshold: {args.immediate_threshold:.0f}%)...")
            if not args.bot_token or not args.chat_id:
                print("❌ Bot token and chat ID are required for testing.")
                print("Usage: --test-bot --bot-token 'YOUR_TOKEN' --chat-id 'YOUR_CHAT_ID'")
                sys.exit(1)

            if tracker.test_telegram_bot():
                print("✅ Telegram bot and immediate spike alert test successful!")
                print(f"🚨 Big price spikes (≥{args.immediate_threshold:.0f}%) will trigger instant alerts!")
            else:
                print("❌ Telegram bot test failed!")
                sys.exit(1)
                
        elif args.paper_report:
            print("\n📊 Paper Trading Performance Report:")
            print(tracker.get_paper_trading_summary())

    except KeyboardInterrupt:
        logger.info("🛑 Operation stopped by user")
    except Exception as e:
        logger.error(f"Error in main: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
