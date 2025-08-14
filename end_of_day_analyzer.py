#!/usr/bin/env python3
"""
End-of-Day Alert Success Analyzer
Analyzes the success rate of alerts sent during the trading session.

Features:
- Tracks which alerts achieved 30%+ gains
- Calculates maximum drawdown before success
- Provides detailed statistics by alert type and pattern
- Sends summary via Telegram

Usage:
    python end_of_day_analyzer.py [options]

    Options:
        --date YYYY-MM-DD          Analyze alerts for specific date (default: today)
        --bot-token TOKEN          Telegram bot token for notifications
        --chat-id ID              Telegram chat ID for notifications
        --success-threshold PCT   Success threshold percentage (default: 30%)
        --data-dir DIR           Directory containing alert data (default: momentum_data)
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

# For market data fetching
try:
    import yfinance as yf
    import pytz
    YFINANCE_AVAILABLE = True
except ImportError:
    print("⚠️  yfinance not available. Install with: pip install yfinance")
    YFINANCE_AVAILABLE = False

# For Telegram notifications
try:
    import telegram
    TELEGRAM_AVAILABLE = True
except ImportError:
    print("⚠️  python-telegram-bot not available. Install with: pip install python-telegram-bot")
    TELEGRAM_AVAILABLE = False

class EndOfDayAnalyzer:
    def __init__(self, data_dir="momentum_data", success_threshold=30.0, 
                 telegram_bot_token=None, telegram_chat_id=None):
        """
        Initialize the End-of-Day Analyzer
        
        Args:
            data_dir (str): Directory containing alert data
            success_threshold (float): Success threshold percentage (default: 30%)
            telegram_bot_token (str): Telegram bot token for notifications
            telegram_chat_id (str): Telegram chat ID for notifications
        """
        self.data_dir = Path(data_dir)
        self.success_threshold = success_threshold
        
        # Initialize Telegram bot if credentials provided
        self.telegram_bot = None
        self.telegram_chat_id = telegram_chat_id
        
        if telegram_bot_token and telegram_chat_id and TELEGRAM_AVAILABLE:
            try:
                self.telegram_bot = telegram.Bot(token=telegram_bot_token)
                print("✅ Telegram bot initialized successfully")
            except Exception as e:
                print(f"❌ Failed to initialize Telegram bot: {e}")
    
    def get_telegram_alerts_for_date(self, target_date):
        """Get all Telegram alerts sent for a specific date from the log file"""
        telegram_log_file = self.data_dir / "telegram_alerts_sent.jsonl"
        
        if not telegram_log_file.exists():
            print(f"❌ Telegram alerts log file not found: {telegram_log_file}")
            return []
        
        alerts_for_date = []
        target_date_str = target_date.strftime('%Y-%m-%d')
        
        try:
            with open(telegram_log_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        alert_data = json.loads(line)
                        alert_timestamp = alert_data.get('timestamp', '')
                        
                        # Check if this alert is from the target date
                        if alert_timestamp.startswith(target_date_str):
                            alerts_for_date.append(alert_data)
                    
                    except json.JSONDecodeError as e:
                        print(f"⚠️  Skipping malformed JSON on line {line_num}: {e}")
                        continue
        
        except Exception as e:
            print(f"❌ Error reading Telegram alerts log: {e}")
            return []
        
        print(f"📱 Found {len(alerts_for_date)} Telegram alerts sent for {target_date}")
        return alerts_for_date
    
    def extract_alerts_from_telegram_log(self, telegram_alerts):
        """Extract and organize Telegram alerts by ticker"""
        all_alerts = []
        ticker_first_alerts = {}  # Track first alert time per ticker
        
        for alert_data in telegram_alerts:
            try:
                ticker = alert_data.get('ticker')
                if not ticker:
                    continue
                
                timestamp = datetime.fromisoformat(alert_data['timestamp'])
                alert_price = alert_data.get('alert_price', 0)
                alert_type = alert_data.get('alert_type', 'price_spike')
                
                # For Telegram alerts, we only keep the first one per ticker
                # since these are the actual alerts the user received
                if ticker not in ticker_first_alerts:
                    alert_info = {
                        'ticker': ticker,
                        'timestamp': timestamp,
                        'alert_type': alert_type,
                        'alert_price': alert_price,
                        'change_pct': alert_data.get('change_pct', 0),
                        'volume': alert_data.get('volume', 0),
                        'relative_volume': alert_data.get('relative_volume', 0),
                        'sector': alert_data.get('sector', 'Unknown'),
                        'alert_count': alert_data.get('alert_count', 1),
                        'is_immediate_spike': alert_data.get('is_immediate_spike', False),
                        'alert_types': alert_data.get('alert_types', [alert_type]),
                        'original_alert': alert_data
                    }
                    
                    ticker_first_alerts[ticker] = alert_info
                    all_alerts.append(alert_info)
                    
                    print(f"📱 {ticker}: ${alert_price:.2f} ({alert_data.get('change_pct', 0):+.1f}%) - {alert_type}")
            
            except Exception as e:
                print(f"⚠️  Error processing Telegram alert: {e}")
                continue
        
        print(f"📊 Extracted {len(all_alerts)} unique Telegram alerts")
        return all_alerts
    
    def fetch_price_data(self, ticker, start_date, end_date):
        """Fetch price data for a ticker between dates"""
        if not YFINANCE_AVAILABLE:
            return None
            
        try:
            # Add buffer days to ensure we get data
            start_with_buffer = start_date - timedelta(days=5)
            end_with_buffer = end_date + timedelta(days=2)
            
            stock = yf.Ticker(ticker)
            
            # Try different data fetching strategies
            strategies = [
                # Strategy 1: 5-minute intraday data
                {'interval': '5m', 'start': start_with_buffer, 'end': end_with_buffer},
                # Strategy 2: 15-minute data (more reliable)
                {'interval': '15m', 'start': start_with_buffer, 'end': end_with_buffer},
                # Strategy 3: 1-hour data
                {'interval': '1h', 'start': start_with_buffer, 'end': end_with_buffer},
                # Strategy 4: Daily data with date range
                {'interval': '1d', 'start': start_with_buffer, 'end': end_with_buffer},
                # Strategy 5: Recent period-based fetch
                {'period': '5d', 'interval': '1d'},
                # Strategy 6: Longer period as fallback
                {'period': '1mo', 'interval': '1d'}
            ]
            
            for i, strategy in enumerate(strategies, 1):
                try:
                    if 'period' in strategy:
                        data = stock.history(period=strategy['period'], interval=strategy['interval'])
                    else:
                        data = stock.history(start=strategy['start'], end=strategy['end'], interval=strategy['interval'])
                    
                    if not data.empty:
                        return data
                        
                except Exception as strategy_error:
                    continue
            
            # If all strategies fail, return None
            return None
            
        except Exception as e:
            # More specific error handling
            error_msg = str(e).lower()
            if "delisted" in error_msg or "not found" in error_msg:
                print(f"⚠️  {ticker}: Possibly delisted or invalid ticker")
            elif "no data" in error_msg or "data not available" in error_msg:
                print(f"⚠️  {ticker}: No market data available")
            else:
                print(f"⚠️  {ticker}: {str(e)[:100]}...")
            return None
    
    def analyze_ticker_performance(self, alert_info, target_date):
        """Analyze a single ticker's performance after alert"""
        ticker = alert_info['ticker']
        alert_time = alert_info['timestamp']
        alert_price = alert_info['alert_price']
        
        # Fetch price data from alert time to market close (4:00 PM ET)
        # Note: Alert timestamp might be in local time, so we fetch broader range
        market_close = datetime.combine(target_date, datetime.min.time().replace(hour=20))  # 8 PM ET for buffer
        
        price_data = self.fetch_price_data(ticker, alert_time.date(), market_close.date())
        
        if price_data is None or price_data.empty:
            return {
                'success': False,
                'max_gain': 0,
                'max_drawdown': 0,
                'end_price': alert_price,
                'data_available': False,
                'reason': 'no_data'
            }
        
        # Filter data to after alert time (handle timezone issues)
        try:
            # Convert alert_time to timezone-aware if needed
            if price_data.index.tz is not None and alert_time.tzinfo is None:
                # Assume alert time is in Eastern Time (market time)
                et_tz = pytz.timezone('America/New_York')
                alert_time = et_tz.localize(alert_time)
            elif price_data.index.tz is None and alert_time.tzinfo is not None:
                alert_time = alert_time.replace(tzinfo=None)
            
            original_len = len(price_data)
            
            # Filter to after alert time (only if alert_time is reasonable)
            # Skip time filtering if alert timestamp seems to be in wrong timezone
            alert_hour = alert_time.hour
            if 6 <= alert_hour <= 20:  # Reasonable trading day hours
                price_data = price_data[price_data.index >= alert_time]
            else:
                print(f"Note: {ticker} skipping time filter (alert at {alert_hour}:xx may be wrong timezone)")
            
            # Filter to regular trading hours only (9:30 AM - 4:00 PM ET)
            # This removes premarket and aftermarket data
            if hasattr(price_data.index, 'tz') and price_data.index.tz:
                # Data is timezone-aware, filter by time
                trading_hours_mask = (
                    (price_data.index.time >= datetime.strptime('09:30', '%H:%M').time()) &
                    (price_data.index.time <= datetime.strptime('16:00', '%H:%M').time())
                )
                trading_hours_data = price_data[trading_hours_mask]
                
                # If no trading hours data, use all data (might be timezone issue)
                if not trading_hours_data.empty:
                    price_data = trading_hours_data
                else:
                    print(f"Note: {ticker} using all available data (no trading hours data found)")
            
            filtered_len = len(price_data)
            
            # Debug info for problematic tickers
            if filtered_len == 0 and original_len > 0:
                print(f"Warning: {ticker} had {original_len} records but 0 after time/trading hours filter")
                
        except Exception as e:
            print(f"Timezone error for {ticker}: {e}")
            # Fallback: use data as-is without time filtering
            print(f"Using all available data for {ticker}")
            pass
        
        if price_data.empty:
            return {
                'success': False,
                'max_gain': 0,
                'max_drawdown': 0,
                'end_price': alert_price,
                'data_available': False,
                'reason': 'no_data_after_alert'
            }
        
        # Filter price data to target date only (ignore data from other days)
        target_date_only = price_data[price_data.index.date == target_date]
        
        if target_date_only.empty:
            # If no data for target date, fall back to all data but log warning
            print(f"Warning: {ticker} no data for {target_date}, using all available data")
            final_data = price_data
        else:
            final_data = target_date_only
        
        # Calculate performance metrics using ALERT PRICE as baseline
        # This measures actual gain from when the first alert was sent
        high_prices = final_data['High'].values
        low_prices = final_data['Low'].values
        close_prices = final_data['Close'].values
        
        # Maximum gain calculation FROM ALERT PRICE (not previous day close)
        max_high = max(high_prices)
        max_gain_pct = ((max_high - alert_price) / alert_price) * 100
        
        # Maximum drawdown calculation (worst drop from alert price before achieving success)
        max_drawdown_pct = 0
        success_achieved = False
        success_price = alert_price * (1 + self.success_threshold / 100)
        
        current_min = alert_price
        for i, (high, low, close) in enumerate(zip(high_prices, low_prices, close_prices)):
            # Check if success threshold was hit
            if high >= success_price:
                success_achieved = True
                break
            
            # Track the lowest point so far
            current_min = min(current_min, low)
            
            # Calculate drawdown from alert price
            drawdown = ((current_min - alert_price) / alert_price) * 100
            max_drawdown_pct = min(max_drawdown_pct, drawdown)  # More negative = larger drawdown
        
        # If success was achieved after some drawdown, continue tracking until success
        if success_achieved:
            # Find the exact point where success was achieved
            for i, (high, low, close) in enumerate(zip(high_prices, low_prices, close_prices)):
                if high >= success_price:
                    break
                current_min = min(current_min, low)
                drawdown = ((current_min - alert_price) / alert_price) * 100
                max_drawdown_pct = min(max_drawdown_pct, drawdown)
        
        # Final price at end of analysis period
        end_price = close_prices[-1]
        
        # Debug info for verification
        if len(final_data) != len(price_data):
            print(f"Note: {ticker} filtered to {len(final_data)} samples for {target_date} (was {len(price_data)})")
        
        return {
            'success': max_gain_pct >= self.success_threshold,
            'max_gain': max_gain_pct,
            'max_drawdown': abs(max_drawdown_pct),  # Return as positive percentage
            'end_price': end_price,
            'data_available': True,
            'success_achieved_before_eod': success_achieved,
            'samples': len(price_data)
        }
    
    def analyze_day_performance(self, target_date):
        """Analyze performance for all Telegram alerts sent on a given date"""
        print(f"\n🔍 ANALYZING TELEGRAM ALERTS FOR {target_date}")
        print("=" * 60)
        
        # Get Telegram alerts for the date
        telegram_alerts = self.get_telegram_alerts_for_date(target_date)
        
        if not telegram_alerts:
            print(f"❌ No Telegram alerts found for {target_date}")
            print("💡 Note: Telegram alerts are only logged when volume_momentum_tracker.py actually sends them.")
            print("   Make sure you've run the tracker with Telegram enabled and it has sent alerts.")
            return None
        
        # Extract all alerts
        all_alerts = self.extract_alerts_from_telegram_log(telegram_alerts)
        
        if not all_alerts:
            print(f"❌ No valid Telegram alerts found for {target_date}")
            return None
        
        # Analyze each alert
        results = []
        
        print(f"\\n📈 ANALYZING {len(all_alerts)} TICKERS...")
        print("-" * 60)
        
        for i, alert_info in enumerate(all_alerts, 1):
            ticker = alert_info['ticker']
            alert_type = alert_info['alert_type']
            
            print(f"[{i:2d}/{len(all_alerts)}] Analyzing {ticker} ({alert_type})...", end=' ')
            
            performance = self.analyze_ticker_performance(alert_info, target_date)
            
            result = {
                **alert_info,
                **performance
            }
            results.append(result)
            
            if performance['data_available']:
                success_marker = "✅" if performance['success'] else "❌"
                print(f"{success_marker} Max: {performance['max_gain']:+5.1f}% | DD: {performance['max_drawdown']:4.1f}%")
            else:
                print(f"⚠️  No data available")
        
        return results
    
    def generate_analysis_report(self, results, target_date):
        """Generate comprehensive analysis report"""
        if not results:
            return "❌ No results to analyze"
        
        # Filter results with available data
        valid_results = [r for r in results if r['data_available']]
        
        if not valid_results:
            return "❌ No valid data available for analysis"
        
        # Calculate overall statistics
        total_alerts = len(valid_results)
        successful_alerts = [r for r in valid_results if r['success']]
        success_count = len(successful_alerts)
        success_rate = (success_count / total_alerts) * 100
        
        # Performance statistics
        all_gains = [r['max_gain'] for r in valid_results]
        successful_gains = [r['max_gain'] for r in successful_alerts]
        all_drawdowns = [r['max_drawdown'] for r in valid_results]
        successful_drawdowns = [r['max_drawdown'] for r in successful_alerts]
        
        avg_gain = statistics.mean(all_gains)
        avg_successful_gain = statistics.mean(successful_gains) if successful_gains else 0
        avg_drawdown = statistics.mean(all_drawdowns)
        avg_successful_drawdown = statistics.mean(successful_drawdowns) if successful_drawdowns else 0
        max_drawdown = max(all_drawdowns) if all_drawdowns else 0
        
        # Alert type breakdown
        type_stats = defaultdict(lambda: {'total': 0, 'successful': 0, 'gains': [], 'drawdowns': []})
        
        for result in valid_results:
            alert_type = result['alert_type']
            type_stats[alert_type]['total'] += 1
            type_stats[alert_type]['gains'].append(result['max_gain'])
            type_stats[alert_type]['drawdowns'].append(result['max_drawdown'])
            
            if result['success']:
                type_stats[alert_type]['successful'] += 1
        
        # Flat-to-spike analysis (if available)
        flat_to_spike_results = [r for r in valid_results if r['alert_type'] == 'flat_to_spike']
        regular_spike_results = [r for r in valid_results if r['alert_type'] == 'price_spike']
        premarket_results = [r for r in valid_results if r['alert_type'].startswith('premarket')]
        
        # Generate report
        report = f"""
📊 END-OF-DAY TELEGRAM ALERT ANALYSIS - {target_date}
{'='*60}
📍 BASELINE: All gains measured from ACTUAL TELEGRAM ALERT PRICE (regular trading hours only)
📱 SOURCE: Actual Telegram alerts sent to user (not all JSON alerts)

🎯 OVERALL PERFORMANCE
{'─'*30}
Total Alerts Analyzed: {total_alerts}
Successful (≥{self.success_threshold}%): {success_count}
Success Rate: {success_rate:.1f}%

📈 PERFORMANCE METRICS (from Alert Price)
{'─'*30}
Average Max Gain: {avg_gain:+5.1f}%
Average Successful Gain: {avg_successful_gain:+5.1f}%
Average Drawdown: {avg_drawdown:4.1f}%
Average Successful Drawdown: {avg_successful_drawdown:4.1f}%
Maximum Drawdown: {max_drawdown:4.1f}%

🏷️  ALERT TYPE BREAKDOWN
{'─'*30}"""

        for alert_type, stats in sorted(type_stats.items()):
            if stats['total'] > 0:
                type_success_rate = (stats['successful'] / stats['total']) * 100
                type_avg_gain = statistics.mean(stats['gains'])
                type_avg_drawdown = statistics.mean(stats['drawdowns'])
                
                report += f"""
{alert_type.replace('_', ' ').title():20} | {stats['successful']:2d}/{stats['total']:2d} ({type_success_rate:4.1f}%) | Gain: {type_avg_gain:+5.1f}% | DD: {type_avg_drawdown:4.1f}%"""

        # Enhanced flat-to-spike analysis
        if flat_to_spike_results or regular_spike_results:
            report += f"""

🎯 FLAT-TO-SPIKE ANALYSIS
{'─'*30}"""
            
            if flat_to_spike_results:
                flat_success = len([r for r in flat_to_spike_results if r['success']])
                flat_rate = (flat_success / len(flat_to_spike_results)) * 100 if flat_to_spike_results else 0
                flat_avg_gain = statistics.mean([r['max_gain'] for r in flat_to_spike_results])
                flat_avg_dd = statistics.mean([r['max_drawdown'] for r in flat_to_spike_results])
                
                report += f"""
Verified Flat-to-Spike: {flat_success}/{len(flat_to_spike_results)} ({flat_rate:.1f}%) | Gain: {flat_avg_gain:+5.1f}% | DD: {flat_avg_dd:4.1f}%"""
            
            if regular_spike_results:
                reg_success = len([r for r in regular_spike_results if r['success']])
                reg_rate = (reg_success / len(regular_spike_results)) * 100 if regular_spike_results else 0
                reg_avg_gain = statistics.mean([r['max_gain'] for r in regular_spike_results])
                reg_avg_dd = statistics.mean([r['max_drawdown'] for r in regular_spike_results])
                
                report += f"""
Regular Price Spikes:   {reg_success}/{len(regular_spike_results)} ({reg_rate:.1f}%) | Gain: {reg_avg_gain:+5.1f}% | DD: {reg_avg_dd:4.1f}%"""
            
            if premarket_results:
                pm_success = len([r for r in premarket_results if r['success']])
                pm_rate = (pm_success / len(premarket_results)) * 100 if premarket_results else 0
                pm_avg_gain = statistics.mean([r['max_gain'] for r in premarket_results])
                pm_avg_dd = statistics.mean([r['max_drawdown'] for r in premarket_results])
                
                report += f"""
Premarket Alerts:       {pm_success}/{len(premarket_results)} ({pm_rate:.1f}%) | Gain: {pm_avg_gain:+5.1f}% | DD: {pm_avg_dd:4.1f}%"""

        # Top performers
        top_performers = sorted([r for r in valid_results if r['success']], 
                              key=lambda x: x['max_gain'], reverse=True)[:5]
        
        if top_performers:
            report += f"""

🏆 TOP PERFORMERS
{'─'*30}"""
            for i, result in enumerate(top_performers, 1):
                report += f"""
{i}. {result['ticker']:6} | {result['max_gain']:+6.1f}% | DD: {result['max_drawdown']:4.1f}% | {result['alert_type'].replace('_', ' ').title()}"""

        # Worst drawdowns
        worst_drawdowns = sorted(valid_results, key=lambda x: x['max_drawdown'], reverse=True)[:5]
        
        if worst_drawdowns:
            report += f"""

📉 LARGEST DRAWDOWNS
{'─'*30}"""
            for i, result in enumerate(worst_drawdowns, 1):
                success_marker = "✅" if result['success'] else "❌"
                report += f"""
{i}. {result['ticker']:6} | DD: {result['max_drawdown']:4.1f}% | Gain: {result['max_gain']:+5.1f}% {success_marker} | {result['alert_type'].replace('_', ' ').title()}"""

        report += f"""

📊 ANALYSIS COMPLETE
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return report
    
    async def send_telegram_report(self, report):
        """Send analysis report via Telegram"""
        if not self.telegram_bot or not self.telegram_chat_id:
            print("📱 Telegram not configured, skipping notification")
            return
        
        try:
            # Split report into chunks if too long
            max_length = 4000  # Telegram message limit
            
            if len(report) <= max_length:
                await self.telegram_bot.send_message(self.telegram_chat_id, f"```\\n{report}\\n```", parse_mode='Markdown')
            else:
                # Split into chunks
                lines = report.split('\\n')
                current_chunk = ""
                
                for line in lines:
                    if len(current_chunk + line + "\\n") <= max_length:
                        current_chunk += line + "\\n"
                    else:
                        if current_chunk:
                            await self.telegram_bot.send_message(self.telegram_chat_id, f"```\\n{current_chunk}```", parse_mode='Markdown')
                        current_chunk = line + "\\n"
                
                # Send remaining chunk
                if current_chunk:
                    await self.telegram_bot.send_message(self.telegram_chat_id, f"```\\n{current_chunk}```", parse_mode='Markdown')
            
            print("📱 Telegram report sent successfully")
            
        except Exception as e:
            print(f"❌ Failed to send Telegram report: {e}")


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='End-of-Day Alert Success Analyzer')
    
    parser.add_argument('--date', type=str, 
                       help='Analyze alerts for specific date (YYYY-MM-DD, default: today)')
    parser.add_argument('--bot-token', type=str, 
                       help='Telegram bot token for notifications')
    parser.add_argument('--chat-id', type=str, 
                       help='Telegram chat ID for notifications')
    parser.add_argument('--success-threshold', type=float, default=30.0,
                       help='Success threshold percentage (default: 30.0)')
    parser.add_argument('--data-dir', type=str, default='momentum_data',
                       help='Directory containing alert data (default: momentum_data)')
    
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
        # Use New York timezone for default date (market time)
        if YFINANCE_AVAILABLE:  # pytz is imported with yfinance
            ny_tz = pytz.timezone('America/New_York')
            ny_now = datetime.now(ny_tz)
            target_date = ny_now.date()
            print(f"🕐 Using New York time: {ny_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        else:
            # Fallback to local time if pytz not available
            target_date = date.today()
            print(f"⚠️  Using local time (pytz not available): {target_date}")
    
    print(f"🚀 END-OF-DAY ALERT ANALYZER")
    print(f"📅 Target Date: {target_date}")
    print(f"🎯 Success Threshold: {args.success_threshold}%")
    print(f"📁 Data Directory: {args.data_dir}")
    
    # Initialize analyzer
    analyzer = EndOfDayAnalyzer(
        data_dir=args.data_dir,
        success_threshold=args.success_threshold,
        telegram_bot_token=args.bot_token,
        telegram_chat_id=args.chat_id
    )
    
    # Analyze performance
    results = analyzer.analyze_day_performance(target_date)
    
    if not results:
        print("❌ No analysis results available")
        sys.exit(1)
    
    # Generate report
    report = analyzer.generate_analysis_report(results, target_date)
    
    print(report)
    
    # Send Telegram notification if configured
    if args.bot_token and args.chat_id:
        await analyzer.send_telegram_report(report)
    
    print("\\n✅ Analysis complete!")


if __name__ == "__main__":
    asyncio.run(main())