#!/usr/bin/env python3
"""
Premarket Top 20 Volume Monitor
Monitors the top 20 tickers by premarket volume every 2 minutes.
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
from datetime import datetime
from pathlib import Path
import logging
from telegram import Bot

from tradingview_screener import Query

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

    def _get_tradingview_link(self, symbol):
        """Generate TradingView chart link for the symbol"""
        return f"https://www.tradingview.com/chart/?symbol={symbol}"

    def get_top20_by_premarket_volume(self):
        """Get top 20 tickers sorted by premarket volume descending"""
        try:
            query = (Query()
                    .select(
                        'name',                # Symbol/Name
                        'premarket_volume',    # Pre-market volume
                        'premarket_change',    # Pre-market change %
                        'close',               # Previous close price
                        'sector',              # Sector
                        'exchange'             # Exchange
                    )
                    .order_by('premarket_volume', ascending=False)
                    .limit(100))  # Get more to filter manually

            logger.info("📊 Fetching premarket volume data from TradingView...")
            data = query.get_scanner_data(cookies=self.cookies)

            # Process the data - handle different response formats
            df_data = None
            if isinstance(data, tuple) and len(data) == 2:
                total_count, df_data = data
            else:
                df_data = data

            if df_data is None:
                logger.error("❌ No data returned from query")
                return None

            # Convert to records list
            all_records = []
            if hasattr(df_data, 'to_dict'):
                all_records = df_data.to_dict('records')
            elif isinstance(df_data, list):
                all_records = df_data
            elif isinstance(df_data, dict):
                # If it's already a dict, wrap it in a list
                all_records = [df_data]
            else:
                logger.error(f"❌ Unexpected data format: {type(df_data)}")
                return None

            logger.info(f"✅ Retrieved {len(all_records)} records")

            # Filter for valid records and get top 20
            valid_records = []
            for record in all_records:
                try:
                    # Ensure record is a dict
                    if not isinstance(record, dict):
                        logger.warning(f"⚠️  Skipping non-dict record: {type(record)}")
                        continue

                    # Filter out records with no premarket volume
                    pm_volume = record.get('premarket_volume')
                    if pm_volume and pm_volume > 0:
                        valid_records.append(record)

                    # Stop when we have enough
                    if len(valid_records) >= 20:
                        break
                except Exception as e:
                    logger.warning(f"⚠️  Error processing record: {e}")
                    continue

            logger.info(f"✅ Found {len(valid_records)} tickers with premarket volume")

            # Log the screener data to file
            if valid_records:
                self._log_screener_data(valid_records)

            return valid_records if valid_records else None

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
        # Create position dictionary from current data
        current_positions = {}
        for idx, record in enumerate(current_top20, 1):
            symbol = record.get('name')
            if symbol:
                current_positions[symbol] = idx

        # If this is the first run, consider it a change
        if not self.previous_positions:
            logger.info("📌 First run - will send notification")
            return True, current_positions

        # Check if any positions changed
        has_changed = False

        # Check if order changed
        prev_list = sorted(self.previous_positions.items(), key=lambda x: x[1])
        curr_list = sorted(current_positions.items(), key=lambda x: x[1])

        if [x[0] for x in prev_list] != [x[0] for x in curr_list]:
            has_changed = True
            logger.info("🔄 Ticker positions have changed!")
        else:
            logger.info("✅ No position changes detected")

        return has_changed, current_positions

    def _format_telegram_message(self, top20_data):
        """Format the top 20 list as a Telegram message"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        message = f"🌅 PREMARKET TOP 20 BY VOLUME\n"
        message += f"📅 {timestamp}\n"
        message += f"{'='*40}\n\n"

        for idx, record in enumerate(top20_data, 1):
            symbol = record.get('name', 'N/A')
            pm_volume = record.get('premarket_volume', 0)
            pm_change = record.get('premarket_change', 0)

            # Format volume with commas
            volume_str = f"{pm_volume:,.0f}" if pm_volume else "N/A"

            # Format change with + or - sign
            change_str = f"{pm_change:+.2f}%" if pm_change is not None else "N/A"

            # Create TradingView link
            tv_link = self._get_tradingview_link(symbol)

            # Add emoji based on change
            emoji = "🟢" if pm_change and pm_change > 0 else "🔴" if pm_change and pm_change < 0 else "⚪"

            # Format line with clickable link (Markdown format)
            message += f"{idx}. {emoji} [{symbol}]({tv_link})\n"
            message += f"   📊 Volume: {volume_str}\n"
            message += f"   📈 Change: {change_str}\n\n"

        message += f"{'='*40}\n"
        message += f"💡 Positions tracked every 2 minutes"

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

    def run_single_scan(self):
        """Run a single scan and send notification if positions changed"""
        logger.info("🔍 Running single scan...")

        # Get top 20 by premarket volume
        top20_data = self.get_top20_by_premarket_volume()

        if not top20_data:
            logger.error("❌ Failed to get data")
            return False

        # Detect position changes
        has_changed, current_positions = self._detect_position_changes(top20_data)

        # Send notification if positions changed
        if has_changed:
            logger.info("📱 Sending notification due to position changes...")
            message = self._format_telegram_message(top20_data)

            # Print to console
            print("\n" + "="*50)
            print(message.replace('[', '').replace(']', '').replace('(', ' ('))
            print("="*50 + "\n")

            # Send to Telegram
            if self.telegram_bot:
                loop = asyncio.get_event_loop()
                loop.run_until_complete(self._send_telegram_message(message))

            # Save current positions
            self._save_positions(current_positions)
            self.previous_positions = current_positions
        else:
            logger.info("✅ No changes - skipping notification")

        return True

    def run_continuous(self):
        """Run continuous monitoring every 2 minutes"""
        logger.info("🚀 Starting continuous monitoring (every 2 minutes)...")
        logger.info("Press Ctrl+C to stop")

        scan_count = 0

        try:
            while True:
                scan_count += 1
                logger.info(f"\n{'='*60}")
                logger.info(f"📊 SCAN #{scan_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"{'='*60}")

                self.run_single_scan()

                # Wait 2 minutes
                logger.info("⏳ Waiting 2 minutes until next scan...")
                time.sleep(120)  # 2 minutes = 120 seconds

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
