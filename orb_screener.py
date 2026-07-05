#!/usr/bin/env python3
"""
ORB (Opening Range Breakout) Screener
Finds tickers priced below $20 with a change from open between 1% and 5%,
sorted by volume, and sends the top 20 via Telegram with TradingView links.

Intended to be run as a single scan shortly after the open (e.g. 9:30 and 10:00).

Usage:
    python orb_screener.py --bot-token YOUR_TOKEN --chat-id YOUR_CHAT_ID
"""

import json
import argparse
import asyncio
import os
import sys
import logging
from datetime import datetime
from pathlib import Path

try:
    import rookiepy
except ImportError:
    rookiepy = None

from telegram import Bot
from tradingview_screener import Query, Column

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('orb_screener.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Log directory for screener data and notifications
LOG_DIR = Path("orb_data")
LOG_DIR.mkdir(exist_ok=True)

# Screener parameters
MAX_PRICE = 20
MIN_CHANGE_FROM_OPEN = 1
MAX_CHANGE_FROM_OPEN = 5
TOP_N = 20


class ORBScreener:
    def __init__(self, telegram_bot_token=None, telegram_chat_id=None):
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.telegram_bot = None

        if telegram_bot_token and telegram_chat_id:
            self.telegram_bot = Bot(token=telegram_bot_token)
            logger.info("✅ Telegram bot initialized")
        else:
            logger.warning("⚠️  No Telegram credentials provided - notifications disabled")

        self.cookies = self._get_tradingview_cookies()

    def _get_tradingview_cookies(self):
        """Get TradingView cookies for API access"""
        if rookiepy is None:
            logger.warning("⚠️  rookiepy not installed - using without cookies")
            return {}
        try:
            cookies_list = rookiepy.firefox(['.tradingview.com'])

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

    def _get_tradingview_link(self, symbol):
        """Generate TradingView chart link for the symbol"""
        return f"https://www.tradingview.com/chart/?symbol={symbol}"

    def get_orb_candidates(self):
        """Screen for stocks below $20 with 1-5% change from open, sorted by volume"""
        try:
            query = (Query()
                     .select('name', 'close', 'change_from_open', 'change',
                             'volume', 'relative_volume_10d_calc', 'sector', 'exchange')
                     .where(
                         Column('close') < MAX_PRICE,
                         Column('close') > 0,
                         Column('change_from_open').between(MIN_CHANGE_FROM_OPEN, MAX_CHANGE_FROM_OPEN),
                         Column('exchange') != 'OTC',
                         Column('volume') > 0,
                     )
                     .order_by('volume', ascending=False)
                     .limit(TOP_N))

            logger.info("📊 Fetching ORB candidates from TradingView...")
            data = query.get_scanner_data(cookies=self.cookies)

            df_data = None
            if isinstance(data, tuple) and len(data) == 2:
                _, df_data = data
            else:
                df_data = data

            if df_data is None:
                logger.error("❌ No data returned from ORB query")
                return []

            if hasattr(df_data, 'to_dict'):
                records = df_data.to_dict('records')
            elif isinstance(df_data, list):
                records = df_data
            elif isinstance(df_data, dict):
                records = [df_data]
            else:
                logger.error(f"❌ Unexpected data format: {type(df_data)}")
                return []

            records = [r for r in records if isinstance(r, dict) and r.get('name')]
            logger.info(f"✅ Found {len(records)} ORB candidates")

            if records:
                self._log_screener_data(records)

            return records

        except Exception as e:
            logger.error(f"❌ Error getting screener data: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []

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

    def _format_telegram_message(self, records):
        """Format the ORB candidates as a Telegram message"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        message = f"🎯 ORB TOP {len(records)} (<${MAX_PRICE}, +{MIN_CHANGE_FROM_OPEN}% to +{MAX_CHANGE_FROM_OPEN}% from open)\n"
        message += f"📅 {timestamp}\n"
        message += f"{'='*40}\n\n"

        for idx, record in enumerate(records, 1):
            symbol = record.get('name', 'N/A')
            close = record.get('close')
            change_open = record.get('change_from_open')
            change_day = record.get('change')
            volume = record.get('volume', 0)
            rel_vol = record.get('relative_volume_10d_calc')

            price_str = f"${close:.2f}" if close is not None else "N/A"
            change_open_str = f"{change_open:+.2f}%" if change_open is not None else "N/A"
            change_day_str = f"{change_day:+.2f}%" if change_day is not None else "N/A"
            volume_str = f"{volume:,.0f}" if volume else "N/A"
            rel_vol_str = f"{rel_vol:.1f}x" if rel_vol is not None else "N/A"

            tv_link = self._get_tradingview_link(symbol)

            message += f"{idx}. 🟢 [{symbol}]({tv_link})\n"
            message += f"   💵 Price: {price_str}\n"
            message += f"   📈 From Open: {change_open_str} (Day: {change_day_str})\n"
            message += f"   📊 Volume: {volume_str} (RVol: {rel_vol_str})\n\n"

        message += f"{'='*40}\n"
        message += f"💡 Sorted by volume"

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

    def run(self):
        """Run a single scan and send the notification"""
        logger.info("🔍 Running ORB scan...")

        records = self.get_orb_candidates()

        if not records:
            logger.warning("⚠️  No ORB candidates found - nothing to send")
            return False

        message = self._format_telegram_message(records)

        print("\n" + "="*50)
        print(message.replace('[', '').replace(']', '').replace('(', ' ('))
        print("="*50 + "\n")

        if self.telegram_bot:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._send_telegram_message(message))
            finally:
                loop.close()

        return True


def main():
    parser = argparse.ArgumentParser(
        description='ORB Screener - top 20 tickers <$20 with 1-5% change from open, by volume',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single scan with Telegram notification
  python orb_screener.py --bot-token "YOUR_TOKEN" --chat-id "YOUR_CHAT_ID"

  # Scan without notification (prints to console only)
  python orb_screener.py
        """
    )

    parser.add_argument('--bot-token', type=str, help='Telegram bot token')
    parser.add_argument('--chat-id', type=str, help='Telegram chat ID')

    args = parser.parse_args()

    screener = ORBScreener(
        telegram_bot_token=args.bot_token,
        telegram_chat_id=args.chat_id
    )

    success = screener.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
