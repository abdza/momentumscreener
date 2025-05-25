#!/usr/bin/env python3
"""
Volume Momentum Tracker - Real-time Small Caps Monitor
Continuously monitors small cap stocks to detect:
1. Tickers moving up in volume rankings (volume momentum)
2. Tickers with price spikes (price momentum)

Runs every 2 minutes and compares with previous results to spot emerging momentum plays.
"""

import json
import time
import rookiepy
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

class VolumeMomentumTracker:
    def __init__(self, output_dir="momentum_data", browser="firefox"):
        """
        Initialize the Volume Momentum Tracker
        
        Args:
            output_dir (str): Directory to save data files
            browser (str): Browser to extract cookies from
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.browser = browser
        self.cookies = self._get_cookies()
        
        # Historical data storage
        self.historical_data = []
        self.previous_rankings = {}
        self.price_history = {}
        
        # Tracking settings
        self.monitor_interval = 120  # 2 minutes in seconds
        self.max_history = 50  # Keep last 50 data points
        
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
                              .select('name', 'volume', 'close', 'change|5', 'sector', 'exchange')
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
                
                if rank_change > 0:  # Moved up at least 1 positions
                    # Get current data for this ticker
                    current_ticker_data = next((r for r in current_data if r['name'] == ticker), None)
                    if current_ticker_data:
                        volume_climbers.append({
                            'ticker': ticker,
                            'rank_change': rank_change,
                            'current_rank': current_rank + 1,  # 1-based ranking
                            'previous_rank': previous_rank + 1,
                            'volume': current_ticker_data.get('volume', 0),
                            'price': current_ticker_data.get('close', 0),
                            'change_pct': current_ticker_data.get('change|5', 0),
                            'sector': current_ticker_data.get('sector', 'Unknown')
                        })
            else:
                # New ticker in top rankings
                if current_rank < 50:  # Only care about top 50 newcomers
                    current_ticker_data = next((r for r in current_data if r['name'] == ticker), None)
                    if current_ticker_data:
                        volume_newcomers.append({
                            'ticker': ticker,
                            'current_rank': current_rank + 1,
                            'volume': current_ticker_data.get('volume', 0),
                            'price': current_ticker_data.get('close', 0),
                            'change_pct': current_ticker_data.get('change|5', 0),
                            'sector': current_ticker_data.get('sector', 'Unknown')
                        })
        
        # Sort by rank improvement
        volume_climbers.sort(key=lambda x: x['rank_change'], reverse=True)
        volume_newcomers.sort(key=lambda x: x['current_rank'])
        
        return volume_climbers, volume_newcomers
    
    def analyze_price_spikes(self, current_data, time_window_minutes=10):
        """Analyze which tickers have the biggest price increases"""
        price_spikes = []
        
        # Track price changes
        current_time = datetime.now()
        
        for record in current_data:
            ticker = record.get('name')
            current_price = record.get('close', 0)
            change_pct = record.get('change|5', 0)
            
            if ticker and current_price > 0:
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
                    
                    # Significant price spike criteria
                    if (change_pct > 5 or price_change > 5) and current_price < 20:
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
        
        # Sort by biggest price increases
        price_spikes.sort(key=lambda x: x['change_pct'], reverse=True)
        return price_spikes
    
    def save_alerts(self, volume_climbers, volume_newcomers, price_spikes, timestamp):
        """Save movement alerts to files"""
        alerts_data = {
            'timestamp': timestamp.isoformat(),
            'volume_climbers': volume_climbers[:10],  # Top 10
            'volume_newcomers': volume_newcomers[:10],  # Top 10
            'price_spikes': price_spikes[:10],  # Top 10
            'summary': {
                'total_volume_climbers': len(volume_climbers),
                'total_newcomers': len(volume_newcomers),
                'total_price_spikes': len(price_spikes)
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
    
    def print_alerts(self, volume_climbers, volume_newcomers, price_spikes):
        """Print movement alerts to console"""
        print("\n" + "="*80)
        print(f"🚨 MOMENTUM ALERTS - {datetime.now().strftime('%H:%M:%S')}")
        print("="*80)
        
        if volume_climbers:
            print(f"\n📈 VOLUME CLIMBERS ({len(volume_climbers)} found):")
            print("-" * 60)
            for climber in volume_climbers[:5]:  # Top 5
                print(f"  {climber['ticker']:6} | Rank: {climber['previous_rank']:3d} → {climber['current_rank']:3d} "
                      f"(+{climber['rank_change']:2d}) | Vol: {climber['volume']:>10,} | "
                      f"${climber['price']:6.2f} ({climber['change_pct']:+5.1f}%) | {climber['sector']}")
        
        if volume_newcomers:
            print(f"\n🆕 NEW HIGH VOLUME ({len(volume_newcomers)} found):")
            print("-" * 60)
            for newcomer in volume_newcomers[:5]:  # Top 5
                print(f"  {newcomer['ticker']:6} | NEW → Rank {newcomer['current_rank']:3d} | "
                      f"Vol: {newcomer['volume']:>10,} | ${newcomer['price']:6.2f} "
                      f"({newcomer['change_pct']:+5.1f}%) | {newcomer['sector']}")
        
        if price_spikes:
            print(f"\n🔥 PRICE SPIKES ({len(price_spikes)} found):")
            print("-" * 60)
            for spike in price_spikes[:5]:  # Top 5
                print(f"  {spike['ticker']:6} | ${spike['current_price']:6.2f} ({spike['change_pct']:+5.1f}%) | "
                      f"Vol: {spike['volume']:>10,} | RelVol: {spike['relative_volume']:4.1f}x | {spike['sector']}")
        
        if not volume_climbers and not volume_newcomers and not price_spikes:
            print("\n😴 No significant momentum detected this cycle.")
        
        print("="*80)
    
    def run_single_scan(self):
        """Run a single scan and compare with previous data"""
        timestamp = datetime.now()
        logger.info(f"Starting scan cycle at {timestamp.strftime('%H:%M:%S')}")
        
        # Get current data
        current_data = self.get_volume_screener_data()
        if not current_data:
            logger.error("Failed to get current data")
            return
        
        # Analyze movements
        previous_data = self.historical_data[-1] if self.historical_data else None
        
        volume_climbers, volume_newcomers = self.analyze_volume_movement(current_data, previous_data)
        price_spikes = self.analyze_price_spikes(current_data)
        
        # Print alerts
        self.print_alerts(volume_climbers, volume_newcomers, price_spikes)
        
        # Save alerts
        alerts_data = self.save_alerts(volume_climbers, volume_newcomers, price_spikes, timestamp)
        
        # Store current data for next comparison
        self.historical_data.append(current_data)
        if len(self.historical_data) > self.max_history:
            self.historical_data.pop(0)  # Keep only recent history
        
        # Save raw data
        raw_file = self.output_dir / f"raw_data_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
        with open(raw_file, 'w') as f:
            json.dump(current_data, f, indent=2, default=str)
        
        logger.info(f"Scan cycle completed. Found: {len(volume_climbers)} climbers, "
                   f"{len(volume_newcomers)} newcomers, {len(price_spikes)} price spikes")
    
    def run_continuous_monitoring(self):
        """Run continuous monitoring every 2 minutes"""
        logger.info("🚀 Starting continuous volume momentum monitoring...")
        logger.info(f"📊 Scanning every {self.monitor_interval} seconds (2 minutes)")
        logger.info(f"🎯 Tracking: Volume climbers, newcomers, and price spikes")
        logger.info(f"💾 Data saved to: {self.output_dir}")
        
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

def main():
    """Main function to run the volume momentum tracker"""
    
    # Configuration
    OUTPUT_DIR = "momentum_tracking"
    BROWSER = "firefox"  # or "chrome", "edge", etc.
    
    try:
        # Initialize the tracker
        tracker = VolumeMomentumTracker(
            output_dir=OUTPUT_DIR,
            browser=BROWSER
        )
        
        print("🎯 Volume Momentum Tracker")
        print("=" * 40)
        print("Tracks small cap stocks (price < $20) for:")
        print("  📈 Volume ranking improvements") 
        print("  🆕 New high-volume entries")
        print("  🔥 Price spikes")
        print("  ⏱️  Updates every 2 minutes")
        print("=" * 40)
        
        # Ask user what to do
        choice = input("\n[S]ingle scan or [C]ontinuous monitoring? (s/c): ").lower().strip()
        
        if choice == 's':
            print("\n🔍 Running single scan...")
            tracker.run_single_scan()
            print("\n✅ Single scan completed. Check output files for detailed data.")
        else:
            print("\n🚀 Starting continuous monitoring...")
            print("Press Ctrl+C to stop")
            tracker.run_continuous_monitoring()
        
    except Exception as e:
        logger.error(f"Error in main: {e}")

if __name__ == "__main__":
    main()
