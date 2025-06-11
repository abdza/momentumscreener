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

Command Line Usage:
    python volume_momentum_tracker.py [options]
    
    Options:
        --bot-token TOKEN           Telegram bot token for notifications
        --chat-id ID               Telegram chat ID for notifications
        --continuous              Start continuous monitoring (resets counters first)
        --reset                   Reset ticker counters and exit
        --stats                   Show ticker statistics and exit
        --single                  Run single scan and exit
        --help                    Show this help message
        
    Examples:
        # Single scan
        python volume_momentum_tracker.py --single
        
        # Continuous monitoring with Telegram alerts
        python volume_momentum_tracker.py --continuous --bot-token "YOUR_TOKEN" --chat-id "YOUR_CHAT_ID"
        
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
from datetime import datetime, timedelta
from pathlib import Path
import logging
import pandas as pd
from collections import defaultdict

from tradingview_screener import Query

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('volume_momentum_tracker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# PID file path
PID_FILE = "/tmp/screener.pid"

class VolumeMomentumTracker:
    def __init__(self, output_dir="momentum_data", browser="firefox", telegram_bot_token=None, telegram_chat_id=None):
        """
        Initialize the Volume Momentum Tracker
        
        Args:
            output_dir (str): Directory to save data files
            browser (str): Browser to extract cookies from
            telegram_bot_token (str): Telegram bot token for notifications
            telegram_chat_id (str): Telegram chat ID for notifications
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.browser = browser
        self.cookies = self._get_cookies()
        
        # Initialize Telegram bot if credentials provided
        self.telegram_bot = None
        self.telegram_chat_id = telegram_chat_id
        self.telegram_last_sent = {}  # Track last notification time per ticker for rate limiting
        self.telegram_notification_interval = 30 * 60  # 30 minutes between notifications for same ticker
        
        # News cache to avoid repeated API calls
        self.news_cache = {}
        self.news_cache_duration = 60 * 60  # Cache news for 1 hour
        
        if telegram_bot_token and telegram_chat_id:
            try:
                import telegram
                self.telegram_bot = telegram.Bot(token=telegram_bot_token)
                self.telegram_last_sent = self._load_telegram_last_sent()
                logger.info("✅ Telegram bot initialized successfully")
            except ImportError:
                logger.warning("📱 python-telegram-bot not installed. Run: pip install python-telegram-bot")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Telegram bot: {e}")
        
        # Historical data storage
        self.historical_data = []
        self.previous_rankings = {}
        self.price_history = {}
        self.premarket_history = {}  # Track pre-market data
        
        # Ticker frequency tracking
        self.ticker_counters = self._load_ticker_counters()
        self.ticker_alert_history = self._load_ticker_alert_history()
        
        # Tracking settings
        self.monitor_interval = 120  # 2 minutes in seconds
        self.max_history = 50  # Keep last 50 data points
    
    def _get_recent_news(self, ticker, max_headlines=3):
        """
        Get recent news headlines for a ticker (within last 3 days)
        
        Args:
            ticker (str): Stock ticker symbol
            max_headlines (int): Maximum number of headlines to return
            
        Returns:
            list: List of dictionaries with 'title' and 'url' keys
        """
        # Check cache first
        cache_key = ticker.upper()
        current_time = datetime.now()
        
        if cache_key in self.news_cache:
            cached_data = self.news_cache[cache_key]
            cache_time = datetime.fromisoformat(cached_data['timestamp'])
            if (current_time - cache_time).total_seconds() < self.news_cache_duration:
                logger.debug(f"Using cached news for {ticker}")
                return cached_data['headlines']
        
        headlines = []
        
        try:
            # Method 1: Try Google News search
            headlines = self._search_google_news(ticker, max_headlines)
            
            # Method 2: If Google News fails, try Bing News
            if not headlines:
                headlines = self._search_bing_news(ticker, max_headlines)
            
            # Method 3: If both fail, try Yahoo Finance
            if not headlines:
                headlines = self._search_yahoo_finance_news(ticker, max_headlines)
            
            # Cache the results
            self.news_cache[cache_key] = {
                'timestamp': current_time.isoformat(),
                'headlines': headlines
            }
            
            logger.debug(f"Found {len(headlines)} news headlines for {ticker}")
            
        except Exception as e:
            logger.error(f"Error fetching news for {ticker}: {e}")
            headlines = []
        
        return headlines
    
    def _search_google_news(self, ticker, max_headlines=3):
        """Search Google News for recent ticker news"""
        headlines = []
        
        try:
            # Google News RSS feed
            three_days_ago = datetime.now() - timedelta(days=3)
            
            # Use Google News RSS with search query
            search_query = f"{ticker} stock"
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
                        
                        # Check if published within last 3 days
                        if pub_date_elem is not None:
                            try:
                                # Parse RFC 2822 date format
                                from email.utils import parsedate_to_datetime
                                pub_date = parsedate_to_datetime(pub_date_elem.text)
                                if pub_date < three_days_ago:
                                    continue
                            except:
                                pass  # If date parsing fails, include the article
                        
                        # Filter out obviously unrelated news
                        if any(keyword in title.lower() for keyword in [ticker.lower(), 'stock', 'shares', 'trading']):
                            headlines.append({
                                'title': title[:100] + '...' if len(title) > 100 else title,
                                'url': link
                            })
                            
                            if len(headlines) >= max_headlines:
                                break
                                
                except Exception as e:
                    logger.debug(f"Error parsing news item: {e}")
                    continue
            
        except Exception as e:
            logger.debug(f"Google News search failed for {ticker}: {e}")
        
        return headlines
    
    def _search_bing_news(self, ticker, max_headlines=3):
        """Search Bing News for recent ticker news"""
        headlines = []
        
        try:
            # Bing News search
            search_query = f"{ticker} stock news"
            url = f"https://www.bing.com/news/search?q={search_query}&qft=interval%3d%227%22"  # Last week
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Basic HTML parsing to extract news links and titles
            content = response.text
            
            # Look for news article patterns
            news_pattern = r'<a[^>]*href="([^"]*)"[^>]*aria-label="([^"]*)"'
            matches = re.findall(news_pattern, content)
            
            three_days_ago = datetime.now() - timedelta(days=3)
            
            for url, title in matches[:max_headlines * 2]:
                if len(headlines) >= max_headlines:
                    break
                    
                # Filter relevant news
                if any(keyword in title.lower() for keyword in [ticker.lower(), 'stock', 'shares']):
                    # Clean up the URL
                    if url.startswith('/'):
                        url = 'https://www.bing.com' + url
                    
                    headlines.append({
                        'title': title[:100] + '...' if len(title) > 100 else title,
                        'url': url
                    })
            
        except Exception as e:
            logger.debug(f"Bing News search failed for {ticker}: {e}")
        
        return headlines
    
    def _search_yahoo_finance_news(self, ticker, max_headlines=3):
        """Search Yahoo Finance for recent ticker news"""
        headlines = []
        
        try:
            # Yahoo Finance news URL
            url = f"https://finance.yahoo.com/quote/{ticker}/news"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            content = response.text
            
            # Look for news article patterns in Yahoo Finance
            # This is a simplified approach - you might need to adjust based on Yahoo's current HTML structure
            news_pattern = r'<h3[^>]*><a[^>]*href="([^"]*)"[^>]*>([^<]*)</a></h3>'
            matches = re.findall(news_pattern, content)
            
            for url, title in matches[:max_headlines]:
                # Make sure URL is absolute
                if url.startswith('/'):
                    url = 'https://finance.yahoo.com' + url
                elif not url.startswith('http'):
                    continue
                
                headlines.append({
                    'title': title[:100] + '...' if len(title) > 100 else title,
                    'url': url
                })
            
        except Exception as e:
            logger.debug(f"Yahoo Finance search failed for {ticker}: {e}")
        
        return headlines
    
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
    
    def _send_telegram_alert(self, ticker, alert_count, current_price, change_pct, volume, sector, alert_types):
        """Send Telegram alert for high-frequency ticker with rate limiting and news headlines"""
        if not self.telegram_bot or not self.telegram_chat_id:
            return
        
        # Check rate limiting - don't send if we sent a notification for this ticker recently
        current_time = datetime.now()
        last_sent_time = self.telegram_last_sent.get(ticker)
        
        if last_sent_time:
            time_since_last = (current_time - datetime.fromisoformat(last_sent_time)).total_seconds()
            if time_since_last < self.telegram_notification_interval:
                logger.debug(f"Rate limiting: Skipping Telegram alert for {ticker} (sent {time_since_last:.0f}s ago)")
                return
        
        try:
            import asyncio
            
            # Get recent news headlines
            logger.info(f"Fetching recent news for {ticker}...")
            recent_news = self._get_recent_news(ticker, max_headlines=3)
            
            tradingview_link = self._get_tradingview_link(ticker)
            alert_types_str = ', '.join(alert_types[:3])  # First 3 alert types
            if len(alert_types) > 3:
                alert_types_str += f" +{len(alert_types)-3}"
            
            message = (
                f"🔥 HIGH FREQUENCY MOMENTUM ALERT 🔥\n\n"
                f"📊 Ticker: {ticker}\n"
                f"⚡ Alert Count: {alert_count} times\n"
                f"💰 Current Price: ${current_price:.2f} ({change_pct:+.1f}%)\n"
                f"📈 Volume: {volume:,}\n"
                f"🏭 Sector: {sector}\n"
                f"🎯 Alert Types: {alert_types_str}\n\n"
                f"📋 This ticker has triggered {alert_count} momentum alerts, "
                f"indicating sustained bullish activity!\n\n"
                f"📊 View Chart: {tradingview_link}"
            )
            
            # Add recent news headlines if available
            if recent_news:
                message += f"\n\n📰 Recent Headlines (last 3 days):"
                for i, news_item in enumerate(recent_news, 1):
                    # Telegram supports markdown links: [text](url)
                    message += f"\n{i}. [{news_item['title']}]({news_item['url']})"
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
            logger.info(f"📱 Telegram alert sent for {ticker} ({alert_count} alerts) with {len(recent_news)} news headlines")
            
        except Exception as e:
            logger.error(f"❌ Failed to send Telegram alert for {ticker}: {e}")
            # Try sending without markdown if it fails
            try:
                simple_message = (
                    f"🔥 HIGH FREQUENCY MOMENTUM ALERT 🔥\n\n"
                    f"📊 Ticker: {ticker}\n"
                    f"⚡ Alert Count: {alert_count} times\n"
                    f"💰 Current Price: ${current_price:.2f} ({change_pct:+.1f}%)\n"
                    f"📈 Volume: {volume:,}\n"
                    f"🏭 Sector: {sector}\n"
                    f"🎯 Alert Types: {alert_types_str}\n\n"
                    f"📊 Chart: {tradingview_link}"
                )
                
                loop.run_until_complete(
                    self.telegram_bot.send_message(self.telegram_chat_id, simple_message)
                )
                logger.info(f"📱 Sent simplified Telegram alert for {ticker}")
                
            except Exception as e2:
                logger.error(f"❌ Failed to send even simplified alert: {e2}")
    
    def _check_high_frequency_alerts(self, ticker, alert_data):
        """Check if ticker qualifies for Telegram notification (sends every time for 5+ alerts with rate limiting)"""
        if not self.telegram_bot or not self.telegram_chat_id:
            return
        
        alert_count = self.ticker_counters.get(ticker, 0)
        
        # Send Telegram alert every time for tickers with 5+ alerts (with rate limiting)
        if alert_count >= 5:
            history = self.ticker_alert_history.get(ticker, {})
            alert_types = list(history.get('alert_types', {}).keys())
            
            # Get current data from the alert
            current_price = alert_data.get('current_price', alert_data.get('price', 0))
            change_pct = alert_data.get('change_pct', alert_data.get('premarket_change', 0))
            volume = alert_data.get('volume', 0)
            sector = alert_data.get('sector', 'Unknown')
            
            self._send_telegram_alert(ticker, alert_count, current_price, change_pct, volume, sector, alert_types)
    
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
        
        # Check if this ticker qualifies for Telegram notification
        if alert_data:
            self._check_high_frequency_alerts(ticker, alert_data)
    
    def _add_counter_to_alerts(self, alerts, alert_type):
        """Add appearance counter to alert data and sort by frequency"""
        # First pass: Update counters and add appearance_count to all alerts
        for alert in alerts:
            ticker = alert['ticker']
            
            # Update counter
            self._update_ticker_counter(ticker, alert_type, alert)
            
            # Add counter to alert data
            alert['appearance_count'] = self.ticker_counters.get(ticker, 0)
            alert['alert_types_count'] = len(self.ticker_alert_history.get(ticker, {}).get('alert_types', {}))
        
        # Second pass: Sort by appearance count (highest first), then by the original metric
        try:
            if alert_type == 'volume_climber':
                alerts.sort(key=lambda x: (x.get('appearance_count', 0), x.get('rank_change', 0)), reverse=True)
            elif alert_type == 'volume_newcomer':
                alerts.sort(key=lambda x: (x.get('appearance_count', 0), -x.get('current_rank', 999)), reverse=True)
            elif alert_type in ['price_spike', 'premarket_price']:
                alerts.sort(key=lambda x: (x.get('appearance_count', 0), abs(x.get('change_pct', x.get('premarket_change', 0)))), reverse=True)
            elif alert_type == 'premarket_volume':
                alerts.sort(key=lambda x: (x.get('appearance_count', 0), x.get('premarket_volume', 0)), reverse=True)
        except Exception as e:
            logger.error(f"Error sorting alerts for {alert_type}: {e}")
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
                    .order_by('volume', ascending=False)  # Sort by VOLUME descending
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
                              .select('name', 'volume', 'close', 'change|5', 'premarket_change', 'sector', 'exchange')
                              .order_by('volume', ascending=False)
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
                                'sector': current_ticker_data.get('sector', 'Unknown')
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
                                'sector': current_ticker_data.get('sector', 'Unknown')
                            })
        
        # Sort by rank improvement
        volume_climbers.sort(key=lambda x: x['rank_change'], reverse=True)
        volume_newcomers.sort(key=lambda x: x['current_rank'])
        
        # Add counters and re-sort by frequency
        volume_climbers = self._add_counter_to_alerts(volume_climbers, 'volume_climber')
        volume_newcomers = self._add_counter_to_alerts(volume_newcomers, 'volume_newcomer')
        
        return volume_climbers, volume_newcomers
    
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
                
                # Analyze price movement if we have enough history
                if len(self.price_history[ticker]) >= 2:
                    oldest_entry = self.price_history[ticker][0]
                    price_change = ((current_price - oldest_entry['price']) / oldest_entry['price']) * 100
                    
                    # Significant POSITIVE price spike criteria (long trades only)
                    if (change_pct > 10 or price_change > 15) and current_price < 20 and change_pct > 0:
                        price_spikes.append({
                            'ticker': ticker,
                            'current_price': current_price,
                            'change_pct': change_pct,
                            'price_change_window': price_change,
                            'volume': record.get('volume', 0),
                            'relative_volume': record.get('relative_volume_10d_calc', 0),
                            'sector': record.get('sector', 'Unknown'),
                            'time_window': time_window_minutes
                        })
                elif change_pct > 10:  # First time seeing this ticker but significant positive move
                    price_spikes.append({
                        'ticker': ticker,
                        'current_price': current_price,
                        'change_pct': change_pct,
                        'price_change_window': change_pct,
                        'volume': record.get('volume', 0),
                        'relative_volume': record.get('relative_volume_10d_calc', 0),
                        'sector': record.get('sector', 'Unknown'),
                        'time_window': time_window_minutes
                    })
        
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
                    premarket_price_alerts.append({
                        'ticker': ticker,
                        'premarket_change': premarket_change,
                        'current_price': record.get('close', 0),
                        'volume': record.get('volume', 0),
                        'sector': record.get('sector', 'Unknown'),
                        'alert_type': 'significant_premarket_move'
                    })
                
                # Alert on high pre-market volume (if available)
                if premarket_volume > 100000:  # > 100k pre-market volume
                    premarket_volume_alerts.append({
                        'ticker': ticker,
                        'premarket_volume': premarket_volume,
                        'current_price': record.get('close', 0),
                        'premarket_change': premarket_change,
                        'sector': record.get('sector', 'Unknown'),
                        'alert_type': 'high_premarket_volume'
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
                    premarket_price_alerts.append({
                        'ticker': ticker,
                        'premarket_change': current_pm_change,
                        'premarket_change_acceleration': pm_change_acceleration,
                        'current_price': current_record.get('close', 0),
                        'volume': current_record.get('volume', 0),
                        'sector': current_record.get('sector', 'Unknown'),
                        'alert_type': 'premarket_acceleration'
                    })
                
                # Pre-market volume surge (regardless of price direction)
                if previous_pm_volume > 0:
                    pm_volume_change = ((current_pm_volume - previous_pm_volume) / previous_pm_volume) * 100
                    if pm_volume_change > 50:  # 50%+ increase in pre-market volume
                        premarket_volume_alerts.append({
                            'ticker': ticker,
                            'premarket_volume': current_pm_volume,
                            'premarket_volume_change': pm_volume_change,
                            'current_price': current_record.get('close', 0),
                            'premarket_change': current_pm_change,
                            'sector': current_record.get('sector', 'Unknown'),
                            'alert_type': 'premarket_volume_surge'
                        })
            else:
                # New pre-market activity - ONLY POSITIVE moves (long trades)
                if current_pm_change > 3:  # New significant POSITIVE pre-market move
                    premarket_price_alerts.append({
                        'ticker': ticker,
                        'premarket_change': current_pm_change,
                        'current_price': current_record.get('close', 0),
                        'volume': current_record.get('volume', 0),
                        'sector': current_record.get('sector', 'Unknown'),
                        'alert_type': 'new_premarket_move'
                    })
        
        # Sort alerts - price alerts by biggest POSITIVE moves
        premarket_price_alerts.sort(key=lambda x: x['premarket_change'], reverse=True)  # Only positive now
        premarket_volume_alerts.sort(key=lambda x: x.get('premarket_volume', 0), reverse=True)
        
        # Add counters and re-sort by frequency
        premarket_price_alerts = self._add_counter_to_alerts(premarket_price_alerts, 'premarket_price')
        premarket_volume_alerts = self._add_counter_to_alerts(premarket_volume_alerts, 'premarket_volume')
        
        return premarket_volume_alerts, premarket_price_alerts
    
    def save_alerts(self, volume_climbers, volume_newcomers, price_spikes, premarket_volume_alerts, premarket_price_alerts, timestamp):
        """Save movement alerts to files"""
        alerts_data = {
            'timestamp': timestamp.isoformat(),
            'volume_climbers': volume_climbers[:10],  # Top 10
            'volume_newcomers': volume_newcomers[:10],  # Top 10
            'price_spikes': price_spikes[:10],  # Top 10
            'premarket_volume_alerts': premarket_volume_alerts[:10],  # Top 10
            'premarket_price_alerts': premarket_price_alerts[:10],  # Top 10
            'summary': {
                'total_volume_climbers': len(volume_climbers),
                'total_newcomers': len(volume_newcomers),
                'total_price_spikes': len(price_spikes),
                'total_premarket_volume_alerts': len(premarket_volume_alerts),
                'total_premarket_price_alerts': len(premarket_price_alerts)
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
    
    def print_alerts(self, volume_climbers, volume_newcomers, price_spikes, premarket_volume_alerts, premarket_price_alerts):
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
                    print(f"  {climber['ticker']:6} [{count:2d}x] | Rank: {climber['previous_rank']:3d} → {climber['current_rank']:3d} "
                          f"(+{climber['rank_change']:2d}) | Vol: {climber['volume']:>10,} | "
                          f"${climber['price']:6.2f} ({climber.get('change_pct', 0):+5.1f}%) | {climber.get('sector', 'Unknown')}")
                except Exception as e:
                    logger.error(f"Error printing volume climber {climber.get('ticker', 'Unknown')}: {e}")
        
        if volume_newcomers:
            print(f"\n🆕 NEW HIGH VOLUME ({len(volume_newcomers)} found) - Sorted by Frequency:")
            print("-" * 70)
            for newcomer in volume_newcomers[:5]:  # Top 5
                try:
                    count = newcomer.get('appearance_count', 1)
                    print(f"  {newcomer['ticker']:6} [{count:2d}x] | NEW → Rank {newcomer['current_rank']:3d} | "
                          f"Vol: {newcomer['volume']:>10,} | ${newcomer['price']:6.2f} "
                          f"({newcomer.get('change_pct', 0):+5.1f}%) | {newcomer.get('sector', 'Unknown')}")
                except Exception as e:
                    logger.error(f"Error printing volume newcomer {newcomer.get('ticker', 'Unknown')}: {e}")
        
        if price_spikes:
            print(f"\n🔥 PRICE SPIKES ({len(price_spikes)} found) - Sorted by Frequency:")
            print("-" * 70)
            for spike in price_spikes[:5]:  # Top 5
                try:
                    count = spike.get('appearance_count', 1)
                    print(f"  {spike['ticker']:6} [{count:2d}x] | ${spike['current_price']:6.2f} ({spike.get('change_pct', 0):+5.1f}%) | "
                          f"Vol: {spike.get('volume', 0):>10,} | RelVol: {spike.get('relative_volume', 0):4.1f}x | {spike.get('sector', 'Unknown')}")
                except Exception as e:
                    logger.error(f"Error printing price spike {spike.get('ticker', 'Unknown')}: {e}")
        
        if premarket_volume_alerts:
            print(f"\n🌅 PRE-MARKET VOLUME ({len(premarket_volume_alerts)} found) - Sorted by Frequency:")
            print("-" * 70)
            for alert in premarket_volume_alerts[:5]:  # Top 5
                try:
                    count = alert.get('appearance_count', 1)
                    if alert.get('alert_type') == 'premarket_volume_surge':
                        print(f"  {alert['ticker']:6} [{count:2d}x] | PM Vol: {alert.get('premarket_volume', 0):>8,} "
                              f"(+{alert.get('premarket_volume_change', 0):5.1f}%) | ${alert.get('current_price', 0):6.2f} "
                              f"PM: {alert.get('premarket_change', 0):+5.1f}% | {alert.get('sector', 'Unknown')}")
                    else:
                        print(f"  {alert['ticker']:6} [{count:2d}x] | PM Vol: {alert.get('premarket_volume', 0):>8,} | "
                              f"${alert.get('current_price', 0):6.2f} PM: {alert.get('premarket_change', 0):+5.1f}% | {alert.get('sector', 'Unknown')}")
                except Exception as e:
                    logger.error(f"Error printing premarket volume alert {alert.get('ticker', 'Unknown')}: {e}")
        
        if premarket_price_alerts:
            print(f"\n🌄 PRE-MARKET MOVERS ({len(premarket_price_alerts)} found) - Sorted by Frequency:")
            print("-" * 70)
            for alert in premarket_price_alerts[:5]:  # Top 5
                try:
                    count = alert.get('appearance_count', 1)
                    if alert.get('alert_type') == 'premarket_acceleration':
                        print(f"  {alert['ticker']:6} [{count:2d}x] | PM: {alert.get('premarket_change', 0):+6.1f}% "
                              f"(Δ{alert.get('premarket_change_acceleration', 0):+5.1f}%) | ${alert.get('current_price', 0):6.2f} | "
                              f"Vol: {alert.get('volume', 0):>8,} | {alert.get('sector', 'Unknown')}")
                    else:
                        print(f"  {alert['ticker']:6} [{count:2d}x] | PM: {alert.get('premarket_change', 0):+6.1f}% | "
                              f"${alert.get('current_price', 0):6.2f} | Vol: {alert.get('volume', 0):>8,} | {alert.get('sector', 'Unknown')}")
                except Exception as e:
                    logger.error(f"Error printing premarket price alert {alert.get('ticker', 'Unknown')}: {e}")
        
        if not any([volume_climbers, volume_newcomers, price_spikes, premarket_volume_alerts, premarket_price_alerts]):
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
            
            # Print alerts with error handling
            try:
                self.print_alerts(volume_climbers, volume_newcomers, price_spikes, premarket_volume_alerts, premarket_price_alerts)
            except Exception as e:
                logger.error(f"Error printing alerts: {e}")
                print(f"⚠️  Error displaying alerts: {e}")
                print(f"Found: {len(volume_climbers)} climbers, {len(volume_newcomers)} newcomers, "
                      f"{len(price_spikes)} price spikes, {len(premarket_volume_alerts)} PM volume, "
                      f"{len(premarket_price_alerts)} PM price alerts")
            
            # Save alerts
            try:
                alerts_data = self.save_alerts(volume_climbers, volume_newcomers, price_spikes, 
                                             premarket_volume_alerts, premarket_price_alerts, timestamp)
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
                       f"{len(premarket_volume_alerts)} PM volume alerts, {len(premarket_price_alerts)} PM price alerts")
                       
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
        logger.info(f"💾 Data saved to: {self.output_dir}")
        logger.info(f"📰 News headlines: Recent news included in Telegram alerts")
        
        if self.telegram_bot and self.telegram_chat_id:
            logger.info("📱 Telegram notifications: ✅ ENABLED")
            logger.info(f"📱 Rate limiting: {self.telegram_notification_interval/60:.0f} minutes between notifications per ticker")
            logger.info("📰 Recent headlines (last 3 days) will be included in alerts")
        else:
            logger.info("📱 Telegram notifications: ❌ DISABLED")
        
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
        self.news_cache = {}  # Reset news cache too
        self._save_ticker_data()
        logger.info("🔄 Ticker counters, history, news cache, and Telegram rate limiting reset")
    
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
        
        print(f"\nTop 10 Most Active Tickers:")
        print("-" * 60)
        
        for i, (ticker, count) in enumerate(sorted_tickers[:10], 1):
            history = self.ticker_alert_history.get(ticker, {})
            alert_types = history.get('alert_types', {})
            types_str = ', '.join([f"{k}({v})" for k, v in alert_types.items()])
            
            print(f"{i:2d}. {ticker:6} | {count:3d} total | {types_str}")

    def test_telegram_bot(self):
        """Test Telegram bot connectivity and news fetching"""
        if not self.telegram_bot or not self.telegram_chat_id:
            print("❌ Telegram bot not configured. Provide --bot-token and --chat-id parameters.")
            return False
        
        try:
            import asyncio
            
            # Test basic message sending
            test_message = (
                "🧪 Test message from Volume Momentum Tracker\n\n"
                "📊 If you see this, Telegram notifications are working correctly!\n\n"
                "📱 Notifications will be sent for every alert of tickers with 5+ total alerts "
                "(rate limited to once per 30 minutes per ticker).\n\n"
                "📰 Recent headlines (last 3 days) will be included automatically."
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
            
            # Test news fetching
            print("\n🧪 Testing news headline fetching...")
            test_ticker = "AAPL"  # Use Apple as test ticker
            news_headlines = self._get_recent_news(test_ticker, max_headlines=2)
            
            if news_headlines:
                print(f"✅ Successfully fetched {len(news_headlines)} headlines for {test_ticker}")
                
                # Send a test news message
                news_test_message = f"📰 News Test for {test_ticker}:\n\n"
                for i, news_item in enumerate(news_headlines, 1):
                    news_test_message += f"{i}. [{news_item['title']}]({news_item['url']})\n"
                
                loop.run_until_complete(
                    self.telegram_bot.send_message(
                        self.telegram_chat_id, 
                        news_test_message,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
                )
                print("✅ News headlines test sent successfully!")
            else:
                print(f"⚠️  No headlines found for {test_ticker} - this is normal if there's no recent news")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to send test message: {e}")
            return False

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Volume Momentum Tracker - Real-time Small Caps Monitor with News Headlines",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Single scan:
    python volume_momentum_tracker.py --single
    
  Continuous monitoring with Telegram:
    python volume_momentum_tracker.py --continuous --bot-token "YOUR_TOKEN" --chat-id "YOUR_CHAT_ID"
    
  Reset counters:
    python volume_momentum_tracker.py --reset
    
  Show statistics:
    python volume_momentum_tracker.py --stats
    
  Test Telegram bot and news fetching:
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
                            help='Test Telegram bot connectivity and news fetching, then exit')
    
    # Telegram configuration
    parser.add_argument('--bot-token', type=str, 
                       help='Telegram bot token for notifications')
    parser.add_argument('--chat-id', type=str, 
                       help='Telegram chat ID for notifications')
    
    # Optional configuration
    parser.add_argument('--output-dir', type=str, default='momentum_data',
                       help='Directory to save data files (default: momentum_data)')
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
            telegram_chat_id=args.chat_id
        )
        
        # Print header
        print("🎯 Volume Momentum Tracker with News Headlines (LONG TRADES)")
        print("=" * 70)
        print("Tracks small cap stocks (price < $20) for BULLISH momentum:")
        print("  📈 Volume ranking improvements (with positive price movement)") 
        print("  🆕 New high-volume entries (with positive price movement)")
        print("  🔥 POSITIVE price spikes only")
        print("  🌅 Pre-market volume surges")
        print("  🌄 POSITIVE pre-market price movements only")
        print("  📊 Tracks frequency of alerts per ticker")
        print("  🔥 Shows trending tickers (most frequent)")
        print("  📱 Sends Telegram alerts for EVERY alert of tickers with 5+ alerts")
        print("  📰 Includes recent news headlines (last 3 days) in Telegram alerts")
        print("  📱 Rate limiting: 30 minutes between notifications per ticker")
        print("  ⏱️  Updates every 2 minutes")
        print("  🚀 LONG TRADES ONLY - No bearish alerts")
        print("=" * 70)
        
        # Show Telegram status
        if tracker.telegram_bot and tracker.telegram_chat_id:
            print("📱 Telegram notifications: ✅ ENABLED")
            print("📰 News headlines: ✅ ENABLED (last 3 days)")
            print(f"📱 Rate limiting: {tracker.telegram_notification_interval/60:.0f} minutes between notifications per ticker")
        else:
            print("📱 Telegram notifications: ❌ DISABLED")
            print("📰 News headlines: ❌ DISABLED (requires Telegram)")
            if args.continuous:
                print("   💡 Use --bot-token and --chat-id for Telegram alerts with news")
        print("=" * 70)
        
        # Execute the requested action
        if args.single:
            print("\n🔍 Running single scan...")
            tracker.run_single_scan()
            print("\n✅ Single scan completed. Check output files for detailed data.")
            
        elif args.continuous:
            print("\n🔄 Resetting ticker counters before continuous monitoring...")
            tracker.reset_ticker_counters()
            print("✅ Counters reset. Starting continuous monitoring...")
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
            print("\n🧪 Testing Telegram bot and news fetching...")
            if not args.bot_token or not args.chat_id:
                print("❌ Bot token and chat ID are required for testing.")
                print("Usage: --test-bot --bot-token 'YOUR_TOKEN' --chat-id 'YOUR_CHAT_ID'")
                sys.exit(1)
            
            if tracker.test_telegram_bot():
                print("✅ Telegram bot and news fetching test successful!")
            else:
                print("❌ Telegram bot test failed!")
                sys.exit(1)
        
    except KeyboardInterrupt:
        logger.info("🛑 Operation stopped by user")
    except Exception as e:
        logger.error(f"Error in main: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()