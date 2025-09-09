#!/usr/bin/env python3
"""
Paper Trading Daily Report Analyzer
Analyzes and reports all paper trades executed during a specific trading day.

Features:
- Lists all trades executed on a specific date
- Calculates daily P&L and performance metrics
- Shows entry/exit conditions and timing
- Sends detailed report via Telegram

Usage:
    python paper_trading_analyzer.py [options]

    Options:
        --date YYYY-MM-DD          Analyze trades for specific date (default: yesterday)
        --bot-token TOKEN          Telegram bot token for notifications
        --chat-id ID              Telegram chat ID for notifications
        --data-dir DIR           Directory containing paper trading data (default: momentum_data/paper_trades)
        --help                   Show this help message
"""

import json
import argparse
import sys
import asyncio
from datetime import datetime, timedelta, date
from pathlib import Path
from collections import defaultdict
import statistics
import re

# For timezone handling
try:
    import pytz
    PYTZ_AVAILABLE = True
except ImportError:
    print("⚠️  pytz not available. Install with: pip install pytz")
    PYTZ_AVAILABLE = False

# For Telegram notifications
try:
    import telegram
    TELEGRAM_AVAILABLE = True
except ImportError:
    print("⚠️  python-telegram-bot not available. Install with: pip install python-telegram-bot")
    TELEGRAM_AVAILABLE = False

class PaperTradingAnalyzer:
    def __init__(self, data_dir="momentum_data/paper_trades", 
                 telegram_bot_token=None, telegram_chat_id=None):
        """
        Initialize the Paper Trading Analyzer
        
        Args:
            data_dir (str): Directory containing paper trading data
            telegram_bot_token (str): Telegram bot token for notifications
            telegram_chat_id (str): Telegram chat ID for notifications
        """
        self.data_dir = Path(data_dir)
        
        # Initialize Telegram bot if credentials provided
        self.telegram_bot = None
        self.telegram_chat_id = telegram_chat_id
        
        if telegram_bot_token and telegram_chat_id and TELEGRAM_AVAILABLE:
            try:
                self.telegram_bot = telegram.Bot(token=telegram_bot_token)
                print("✅ Telegram bot initialized successfully")
            except Exception as e:
                print(f"❌ Failed to initialize Telegram bot: {e}")
    
    def format_ticker_link(self, ticker):
        """
        Format ticker as a clickable TradingView link for Telegram
        
        Args:
            ticker (str): Stock ticker symbol
            
        Returns:
            str: Formatted ticker with TradingView link
        """
        tradingview_url = f"https://www.tradingview.com/chart/?symbol={ticker}"
        return f"<a href=\"{tradingview_url}\">{ticker}</a>"
    
    def load_trade_history(self):
        """Load trade history from JSON file"""
        trade_history_file = self.data_dir / "trade_history.json"
        
        if not trade_history_file.exists():
            print(f"❌ Trade history file not found: {trade_history_file}")
            return []
        
        try:
            with open(trade_history_file, 'r', encoding='utf-8') as f:
                trades = json.load(f)
                print(f"📊 Loaded {len(trades)} trades from history")
                return trades
        except Exception as e:
            print(f"❌ Error reading trade history: {e}")
            return []
    
    def filter_trades_by_date(self, trades, target_date):
        """Filter trades that were executed on the target date"""
        trades_for_date = []
        target_date_str = target_date.strftime('%Y-%m-%d')
        
        for trade in trades:
            try:
                # Parse entry timestamp
                entry_dt = datetime.fromisoformat(trade['entry_timestamp'])
                entry_date = entry_dt.date()
                
                # Check if trade was entered on target date
                if entry_date == target_date:
                    trades_for_date.append(trade)
                    
            except Exception as e:
                print(f"⚠️  Error processing trade timestamp: {e}")
                continue
        
        print(f"📱 Found {len(trades_for_date)} trades executed on {target_date}")
        return trades_for_date
    
    def analyze_daily_performance(self, target_date):
        """Analyze performance for all paper trades on a given date"""
        print(f"\n🔍 ANALYZING PAPER TRADES FOR {target_date}")
        print("=" * 60)
        
        # Load all trades
        all_trades = self.load_trade_history()
        
        if not all_trades:
            print(f"❌ No trade history found")
            return None
        
        # Filter trades for the target date
        daily_trades = self.filter_trades_by_date(all_trades, target_date)
        
        if not daily_trades:
            print(f"❌ No paper trades found for {target_date}")
            return None
        
        return daily_trades
    
    def generate_daily_report(self, trades, target_date):
        """Generate comprehensive daily paper trading report"""
        if not trades:
            return "❌ No trades to analyze"
        
        # Calculate statistics
        total_trades = len(trades)
        profitable_trades = [t for t in trades if t['profit_loss'] > 0]
        losing_trades = [t for t in trades if t['profit_loss'] < 0]
        breakeven_trades = [t for t in trades if t['profit_loss'] == 0]
        
        profitable_count = len(profitable_trades)
        losing_count = len(losing_trades)
        breakeven_count = len(breakeven_trades)
        
        win_rate = (profitable_count / total_trades) * 100 if total_trades > 0 else 0
        
        # P&L calculations
        total_pnl = sum(t['profit_loss'] for t in trades)
        total_pnl_pct = sum(t['profit_pct'] for t in trades)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
        avg_pnl_pct = total_pnl_pct / total_trades if total_trades > 0 else 0
        
        best_trade = max(trades, key=lambda x: x['profit_loss']) if trades else None
        worst_trade = min(trades, key=lambda x: x['profit_loss']) if trades else None
        
        # Timing statistics
        holding_times = []
        for trade in trades:
            try:
                if 'holding_time_minutes' in trade:
                    holding_times.append(trade['holding_time_minutes'])
            except:
                continue
        
        avg_holding_time = statistics.mean(holding_times) if holding_times else 0
        
        # Group trades by ticker
        ticker_stats = defaultdict(lambda: {'trades': [], 'pnl': 0, 'count': 0})
        for trade in trades:
            ticker = trade['ticker']
            ticker_stats[ticker]['trades'].append(trade)
            ticker_stats[ticker]['pnl'] += trade['profit_loss']
            ticker_stats[ticker]['count'] += 1
        
        # Generate report
        report = f"""<b>📊 DAILY PAPER TRADING REPORT - {target_date}</b>
================================================
📍 PAPER TRADING STRATEGY: Buy on Alert + Price > 9 EMA, Sell on Price < 25 EMA
💵 Position Size: $100 per trade

<b>🎯 DAILY SUMMARY</b>
------------------------
Total Trades: {total_trades}
Profitable: {profitable_count} ({win_rate:.1f}%)
Breakeven: {breakeven_count}
Losing: {losing_count}

<b>💵 PROFIT & LOSS</b>
------------------------
Total P&amp;L: ${total_pnl:+.2f}
Total P&amp;L %: {total_pnl_pct:+.2f}%
Average P&amp;L: ${avg_pnl:+.2f}
Average P&amp;L %: {avg_pnl_pct:+.2f}%
Best Trade: ${best_trade['profit_loss']:+.2f} ({best_trade['ticker']})
Worst Trade: ${worst_trade['profit_loss']:+.2f} ({worst_trade['ticker']})

<b>⏰ TIMING STATISTICS</b>
------------------------
Average Holding Time: {avg_holding_time:.1f} minutes"""

        # Ticker breakdown
        if len(ticker_stats) > 1:
            report += f"""

<b>🏷️  TICKER BREAKDOWN</b>
------------------------"""
            for ticker, stats in sorted(ticker_stats.items(), key=lambda x: x[1]['pnl'], reverse=True):
                ticker_link = self.format_ticker_link(ticker)
                ticker_win_rate = len([t for t in stats['trades'] if t['profit_loss'] > 0]) / stats['count'] * 100
                report += f"""
{ticker_link}: {stats['count']} trades | P&amp;L: ${stats['pnl']:+.2f} | Win Rate: {ticker_win_rate:.1f}%"""

        # All trades detail
        report += f"""

<b>📋 ALL TRADES ({len(trades)} total)</b>
------------------------"""
        
        # Sort trades by entry time
        sorted_trades = sorted(trades, key=lambda x: x['entry_timestamp'])
        
        for i, trade in enumerate(sorted_trades, 1):
            ticker_link = self.format_ticker_link(trade['ticker'])
            entry_time = datetime.fromisoformat(trade['entry_timestamp']).strftime('%H:%M:%S')
            exit_time = datetime.fromisoformat(trade['exit_timestamp']).strftime('%H:%M:%S')
            
            # Profit/loss indicator
            if trade['profit_loss'] > 0:
                pnl_indicator = "✅"
            elif trade['profit_loss'] < 0:
                pnl_indicator = "❌"
            else:
                pnl_indicator = "➖"
            
            # Exit reason display
            exit_reason = trade.get('exit_reason', 'UNKNOWN')
            if exit_reason == 'EOD_CUTOFF_3:45PM_ET':
                exit_reason_display = "EOD"
            elif exit_reason == 'PRICE_BELOW_25_EMA':
                exit_reason_display = "25 EMA"
            else:
                exit_reason_display = exit_reason[:8]
            
            report += f"""
{i:2d}. {ticker_link} | ${trade['entry_price']:.2f} → ${trade['exit_price']:.2f} | P&amp;L: ${trade['profit_loss']:+.2f} ({trade['profit_pct']:+.1f}%) {pnl_indicator}
    Entry: {entry_time} | Exit: {exit_time} ({trade['holding_time_minutes']:.1f}m) | Reason: {exit_reason_display} | Alert: {trade.get('alert_type', 'N/A').replace('_', ' ').title()}"""

        report += f"""

<b>📊 ANALYSIS COMPLETE</b>
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return report
    
    def generate_telegram_report(self, trades, target_date):
        """Generate a Telegram-friendly version of the report with clickable ticker links"""
        if not trades:
            return "❌ No trades to analyze"
        
        # Calculate statistics
        total_trades = len(trades)
        profitable_trades = [t for t in trades if t['profit_loss'] > 0]
        profitable_count = len(profitable_trades)
        win_rate = (profitable_count / total_trades) * 100 if total_trades > 0 else 0
        
        total_pnl = sum(t['profit_loss'] for t in trades)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
        
        # Use a simple, proven-working format
        report = f"""<b>📊 PAPER TRADING REPORT - {target_date}</b>

Total Trades: {total_trades} | Profitable: {profitable_count} ({win_rate:.1f}%) | Total P&amp;L: +${total_pnl:.2f}
Average P&amp;L: ${avg_pnl:+.2f} per trade | Strategy: Buy on Alert + Price > 9 EMA"""
        
        # Show successful trades first
        if profitable_trades:
            report += f"""

<b>SUCCESSFUL TRADES ({len(profitable_trades)} total)</b>"""
            for trade in sorted(profitable_trades, key=lambda x: x['profit_loss'], reverse=True):
                ticker_link = self.format_ticker_link(trade['ticker'])
                entry_time = datetime.fromisoformat(trade['entry_timestamp']).strftime('%H:%M:%S')
                report += f"""
 {ticker_link} | ${trade['entry_price']:.2f}→${trade['exit_price']:.2f} | +{trade['profit_pct']:.1f}% | {entry_time} ✅"""
        
        # Show all trades summary
        report += f"""

<b>ALL TRADES SUMMARY</b>"""
        
        # Group by ticker
        ticker_summary = {}
        for trade in trades:
            ticker = trade['ticker']
            if ticker not in ticker_summary:
                ticker_summary[ticker] = {'count': 0, 'profitable': 0, 'total_pnl': 0}
            ticker_summary[ticker]['count'] += 1
            ticker_summary[ticker]['total_pnl'] += trade['profit_loss']
            if trade['profit_loss'] > 0:
                ticker_summary[ticker]['profitable'] += 1
        
        for ticker, stats in ticker_summary.items():
            ticker_link = self.format_ticker_link(ticker)
            report += f"""
{ticker_link}: {stats['count']} trades, {stats['profitable']} profitable, ${stats['total_pnl']:+.2f} total"""
        
        # Entry times summary
        first_trade = min(trades, key=lambda x: x['entry_timestamp'])
        last_trade = max(trades, key=lambda x: x['entry_timestamp'])
        first_time = datetime.fromisoformat(first_trade['entry_timestamp']).strftime('%H:%M')
        last_time = datetime.fromisoformat(last_trade['entry_timestamp']).strftime('%H:%M')
        
        report += f"""

Trading window: {first_time}-{last_time} | Position size: $100 each
Paper trading simulation - Click ticker names to view charts"""
        
        return report
    
    async def send_telegram_report(self, trades, target_date):
        """Send paper trading report via Telegram - plain text first to test"""
        if not self.telegram_bot or not self.telegram_chat_id:
            print("📱 Telegram not configured, skipping notification")
            return
        
        try:
            # Start with completely plain text - no HTML at all
            sorted_trades = sorted(trades, key=lambda x: x['entry_timestamp'])
            trades_per_message = 3
            
            import asyncio
            
            for i in range(0, len(sorted_trades), trades_per_message):
                chunk = sorted_trades[i:i + trades_per_message]
                start_num = i + 1
                end_num = min(i + trades_per_message, len(sorted_trades))
                
                # Plain text only - no HTML
                trades_msg = f"Trades {start_num}-{end_num} of {len(sorted_trades)}:\n\n"
                
                for j, trade in enumerate(chunk):
                    trade_num = i + j + 1
                    entry_time = datetime.fromisoformat(trade['entry_timestamp']).strftime('%H:%M:%S')
                    exit_time = datetime.fromisoformat(trade['exit_timestamp']).strftime('%H:%M:%S')
                    
                    # Use simple ticker link - just the essential HTML
                    ticker_link = f'<a href="https://www.tradingview.com/chart/?symbol={trade["ticker"]}">{trade["ticker"]}</a>'
                    
                    trades_msg += f"{trade_num}. {ticker_link}\n"
                    trades_msg += f"${trade['entry_price']:.2f} to ${trade['exit_price']:.2f}\n"
                    trades_msg += f"P&L: ${trade['profit_loss']:+.2f} ({trade['profit_pct']:+.1f}%)\n"
                    trades_msg += f"{entry_time} to {exit_time} ({trade['holding_time_minutes']:.1f}m)\n\n"
                
                # Send with HTML parse mode for clickable links
                await self.telegram_bot.send_message(self.telegram_chat_id, trades_msg, parse_mode='HTML')
                await asyncio.sleep(1)
            
            print(f"📱 Plain text trade details sent in {((len(sorted_trades) - 1) // trades_per_message + 1)} messages")
            
        except Exception as e:
            print(f"❌ Failed to send plain text: {e}")


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Paper Trading Daily Report Analyzer')
    
    parser.add_argument('--date', type=str, 
                       help='Analyze trades for specific date (YYYY-MM-DD, default: yesterday)')
    parser.add_argument('--bot-token', type=str, 
                       help='Telegram bot token for notifications')
    parser.add_argument('--chat-id', type=str, 
                       help='Telegram chat ID for notifications')
    parser.add_argument('--data-dir', type=str, default='momentum_data/paper_trades',
                       help='Directory containing paper trading data (default: momentum_data/paper_trades)')
    
    return parser.parse_args()


async def main():
    """Main function"""
    args = parse_arguments()
    
    # Parse target date
    if args.date:
        try:
            target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        except ValueError:
            print(f"❌ Invalid date format: {args.date}. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        # Default to most recent date with trades (look back up to 7 days)
        if PYTZ_AVAILABLE:
            ny_tz = pytz.timezone('America/New_York')
            ny_now = datetime.now(ny_tz)
            base_date = ny_now.date()
        else:
            base_date = date.today()
        
        # Look for the most recent date with trades
        target_date = None
        
        # Create a temporary analyzer to check for trades (without printing messages)
        temp_data_dir = Path(args.data_dir)
        trade_history_file = temp_data_dir / "trade_history.json"
        if trade_history_file.exists():
            try:
                with open(trade_history_file, 'r', encoding='utf-8') as f:
                    all_trades = json.load(f)
                
                for days_back in range(0, 8):  # Check today and last 7 days
                    check_date = base_date - timedelta(days=days_back)
                    trades_for_date = []
                    
                    for trade in all_trades:
                        try:
                            entry_dt = datetime.fromisoformat(trade['entry_timestamp'])
                            if entry_dt.date() == check_date:
                                trades_for_date.append(trade)
                        except:
                            continue
                    
                    if trades_for_date:
                        target_date = check_date
                        if days_back == 0:
                            print(f"🕐 Using today's trades: {target_date}")
                        else:
                            print(f"🕐 Using most recent trading day: {target_date} ({days_back} day{'s' if days_back > 1 else ''} ago)")
                        break
            except Exception as e:
                print(f"⚠️  Error loading trade history: {e}")
        
        if not target_date:
            # Fallback to yesterday if no trades found in last 7 days
            target_date = base_date - timedelta(days=1)
            print(f"⚠️  No recent trades found, defaulting to yesterday: {target_date}")
    
    print(f"🚀 PAPER TRADING DAILY ANALYZER")
    print(f"📅 Target Date: {target_date}")
    print(f"📁 Data Directory: {args.data_dir}")
    
    # Initialize analyzer
    analyzer = PaperTradingAnalyzer(
        data_dir=args.data_dir,
        telegram_bot_token=args.bot_token,
        telegram_chat_id=args.chat_id
    )
    
    # Analyze daily performance
    trades = analyzer.analyze_daily_performance(target_date)
    
    if not trades:
        print("❌ No trades found for analysis")
        sys.exit(1)
    
    # Generate report
    report = analyzer.generate_daily_report(trades, target_date)
    
    print(report)
    
    # Send Telegram notification if configured
    if args.bot_token and args.chat_id:
        # Send detailed report in multiple messages with clickable links
        await analyzer.send_telegram_report(trades, target_date)
    
    print("\n✅ Analysis complete!")


if __name__ == "__main__":
    asyncio.run(main())