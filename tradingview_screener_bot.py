#!/usr/bin/env python3
"""
TradingView Screener Data Collector using rookiepy for cookie authentication
Automatically collects screener data using your existing Firefox session cookies

CURRENT CONFIGURATION: Small Caps Screener Only - CONFIRMED WORKING FIELDS
- Uses field names confirmed to work via field discovery script
- Gets all 9 requested columns: relative volume, volume, price*vol, change from open %, 
  change %, price, float, pre-market change %, sector
- Sorted by relative volume (descending)
- Filters: Price < $20, Excludes OTC exchanges
- All other screeners are disabled but code is preserved for future use
"""

import json
import schedule
import rookiepy
from datetime import datetime
from pathlib import Path
import logging
import pandas as pd

from tradingview_screener import Query, Column

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('tradingview_data.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class TradingViewDataCollector:
    def __init__(self, output_dir="screener_data", browser="firefox"):
        """
        Initialize the TradingView data collector
        
        Args:
            output_dir (str): Directory to save data files
            browser (str): Browser to extract cookies from ("firefox", "chrome", "edge", etc.)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.browser = browser
        self.cookies = self._get_cookies()
        
    def _get_cookies(self):
        """Get cookies from browser using rookiepy"""
        try:
            # rookiepy API: load(browser_name, domain_name)
            cookies_list = rookiepy.load(self.browser)
            
            # Filter for tradingview.com and convert to dictionary format
            cookies = {}
            for cookie in cookies_list:
                if 'tradingview.com' in cookie.get('domain', ''):
                    cookies[cookie['name']] = cookie['value']
                    
            logger.info(f"Successfully extracted {len(cookies)} cookies from {self.browser}")
            return cookies
        except Exception as e:
            logger.error(f"Failed to extract cookies from {self.browser}: {e}")
            logger.info("Trying to get cookies from all browsers...")
            try:
                # Try to get cookies from any available browser
                cookies_list = rookiepy.load()
                
                # Filter for tradingview.com and convert to dictionary format
                cookies = {}
                for cookie in cookies_list:
                    if 'tradingview.com' in cookie.get('domain', ''):
                        cookies[cookie['name']] = cookie['value']
                    
                logger.info(f"Successfully extracted {len(cookies)} cookies from available browser")
                return cookies
            except Exception as e2:
                logger.error(f"Failed to extract cookies from any browser: {e2}")
                return {}
    
    def get_market_overview(self, limit=50):
        """Get general market overview data"""
        try:
            query = (Query()
                    .select('name', 'close', 'change', 'volume', 'market_cap_basic')
                    .limit(limit))
            
            data = query.get_scanner_data(cookies=self.cookies)
            logger.info(f"Retrieved {len(data)} market overview records")
            return data
            
        except Exception as e:
            logger.error(f"Error getting market overview: {e}")
            return None
    
    def get_custom_screener(self, query_builder):
        """Get data with custom query"""
        try:
            data = query_builder.get_scanner_data(cookies=self.cookies)
            logger.info(f"Retrieved {len(data)} custom screener records")
            return data
            
        except Exception as e:
            logger.error(f"Error getting custom screener data: {e}")
            return None
    
    def get_top_gainers(self, limit=50):
        """Get top gaining stocks"""
        try:
            query = (Query()
                    .select('name', 'close', 'change', 'volume', 'market_cap_basic')
                    .order_by('change', ascending=False)
                    .limit(limit))
            
            data = query.get_scanner_data(cookies=self.cookies)
            logger.info(f"Retrieved {len(data)} top gainers")
            return data
            
        except Exception as e:
            logger.error(f"Error getting top gainers: {e}")
            return None
    
    def get_top_losers(self, limit=50):
        """Get top losing stocks"""
        try:
            query = (Query()
                    .select('name', 'close', 'change', 'volume', 'market_cap_basic')
                    .order_by('change', ascending=True)
                    .limit(limit))
            
            data = query.get_scanner_data(cookies=self.cookies)
            logger.info(f"Retrieved {len(data)} top losers")
            return data
            
        except Exception as e:
            logger.error(f"Error getting top losers: {e}")
            return None
    
    def get_high_volume_stocks(self, limit=50):
        """Get stocks with high volume"""
        try:
            query = (Query()
                    .select('name', 'close', 'volume', 'change', 'market_cap_basic')
                    .order_by('volume', ascending=False)
                    .limit(limit))
            
            data = query.get_scanner_data(cookies=self.cookies)
            logger.info(f"Retrieved {len(data)} high volume stocks")
            return data
            
        except Exception as e:
            logger.error(f"Error getting high volume stocks: {e}")
            return None
    
    def get_value_stocks(self, limit=50):
        """Get value stocks with good fundamentals"""
        try:
            query = (Query()
                    .select('name', 'close', 'price_earnings_ttm', 'market_cap_basic')
                    .order_by('price_earnings_ttm', ascending=True)
                    .limit(limit))
            
            data = query.get_scanner_data(cookies=self.cookies)
            logger.info(f"Retrieved {len(data)} value stocks")
            return data
            
        except Exception as e:
            logger.error(f"Error getting value stocks: {e}")
            return None
    
    def get_growth_stocks(self, limit=50):
        """Get growth stocks"""
        try:
            query = (Query()
                    .select('name', 'close', 'market_cap_basic')
                    .order_by('market_cap_basic', ascending=False)
                    .limit(limit))
            
            data = query.get_scanner_data(cookies=self.cookies)
            logger.info(f"Retrieved {len(data)} growth stocks")
            return data
            
        except Exception as e:
            logger.error(f"Error getting growth stocks: {e}")
            return None
    
    def get_oversold_stocks(self, limit=50):
        """Get oversold stocks (low change)"""
        try:
            query = (Query()
                    .select('name', 'close', 'change', 'volume', 'market_cap_basic')
                    .order_by('change', ascending=True)
                    .limit(limit))
            
            data = query.get_scanner_data(cookies=self.cookies)
            logger.info(f"Retrieved {len(data)} oversold stocks")
            return data
            
        except Exception as e:
            logger.error(f"Error getting oversold stocks: {e}")
            return None
    
    def get_small_caps_screener(self, limit=100):
        """Get small cap stocks screener with custom columns sorted by relative volume, excluding OTC, price < $20"""
        
        try:
            # Use the CONFIRMED WORKING field names from discovery
            query = (Query()
                    .select(
                        'name',                      # Symbol/Name
                        'relative_volume_10d_calc',  # 1. Relative volume ✅
                        'volume',                    # 2. Volume ✅
                        'Value.Traded',             # 3. Price * vol ✅
                        'change_from_open',         # 4. Change from open % ✅
                        'change|5',                 # 5. Change % ✅
                        'close',                    # 6. Price ✅
                        'float_shares_outstanding', # 7. Float ✅
                        'premarket_change',         # 8. Pre-market change % ✅
                        'sector',                   # 9. Sector ✅
                        'exchange'                  # For OTC filtering ✅
                    )
                    .where('exchange', '!=', 'OTC')  # Exclude OTC exchanges
                    .where('close', '<', 20)         # Price less than $20
                    .order_by('relative_volume_10d_calc', ascending=False)  # Sort by relative volume descending
                    .limit(limit))
            
            logger.info("Executing query with CONFIRMED working field names (price < $20, no OTC)...")
            data = query.get_scanner_data(cookies=self.cookies)
            
            return self._process_scanner_data(data, "confirmed working fields query with price filter")
            
        except Exception as e:
            logger.error(f"Error with confirmed field names and filters: {e}")
            # Fallback without exchange filter if that's causing issues
            try:
                logger.info("Trying without exchange filter but keeping price filter...")
                no_exchange_filter_query = (Query()
                                          .select(
                                              'name',
                                              'relative_volume_10d_calc',
                                              'volume',
                                              'Value.Traded',
                                              'change_from_open',
                                              'change|5',
                                              'close',
                                              'float_shares_outstanding',
                                              'premarket_change',
                                              'sector',
                                              'exchange'
                                          )
                                          .where('close', '<', 20)  # Keep price filter
                                          .order_by('relative_volume_10d_calc', ascending=False)
                                          .limit(limit * 2))  # Get more to filter OTC manually
                
                data = no_exchange_filter_query.get_scanner_data(cookies=self.cookies)
                
                # Manual OTC filtering
                processed_data = self._process_scanner_data(data, "no exchange filter query with price filter")
                if processed_data and isinstance(processed_data, list):
                    filtered_data = [
                        record for record in processed_data 
                        if record.get('exchange', '').upper() != 'OTC'
                    ][:limit]
                    logger.info(f"Manually filtered out OTC: {len(filtered_data)} records remaining")
                    return filtered_data
                
                return processed_data
                
            except Exception as e2:
                logger.error(f"Fallback also failed: {e2}")
                # Last resort - no filters, then filter manually
                try:
                    logger.info("Last resort - no API filters, manual filtering...")
                    basic_query = (Query()
                                 .select(
                                     'name',
                                     'relative_volume_10d_calc',
                                     'volume',
                                     'Value.Traded',
                                     'change_from_open',
                                     'change|5',
                                     'close',
                                     'float_shares_outstanding',
                                     'premarket_change',
                                     'sector',
                                     'exchange'
                                 )
                                 .order_by('relative_volume_10d_calc', ascending=False)
                                 .limit(limit * 3))  # Get more to filter manually
                    
                    data = basic_query.get_scanner_data(cookies=self.cookies)
                    
                    # Manual filtering for both price and exchange
                    processed_data = self._process_scanner_data(data, "basic query - manual filtering")
                    if processed_data and isinstance(processed_data, list):
                        filtered_data = [
                            record for record in processed_data 
                            if (record.get('exchange', '').upper() != 'OTC' and 
                                record.get('close', 999) < 20)  # Price < $20 and no OTC
                        ][:limit]
                        logger.info(f"Manually filtered: {len(filtered_data)} records (price < $20, no OTC)")
                        return filtered_data
                    
                    return processed_data
                    
                except Exception as e3:
                    logger.error(f"All queries failed: {e3}")
                    return None
    
    def _process_scanner_data(self, data, query_type):
        """Helper method to process scanner data regardless of format"""
        logger.info(f"Processing data from {query_type}")
        logger.info(f"Received data type: {type(data)}")
        logger.info(f"Data length: {len(data) if hasattr(data, '__len__') else 'Unknown'}")
        
        # Handle different data formats
        if isinstance(data, tuple) and len(data) == 2:
            logger.info("Data is a tuple with 2 elements")
            total_count, df_data = data
            logger.info(f"Total records available: {total_count}")
            logger.info(f"DataFrame type: {type(df_data)}")
            
            # Check if the second element is a DataFrame
            if hasattr(df_data, 'to_dict'):
                logger.info("Second element is a pandas DataFrame")
                logger.info(f"DataFrame shape: {df_data.shape}")
                logger.info(f"DataFrame columns: {df_data.columns.tolist()}")
                logger.info("Sample data:")
                logger.info(str(df_data.head(3)))
                
                # Convert to proper format
                data_records = df_data.to_dict('records')
                logger.info(f"Converted to {len(data_records)} records")
                return data_records
            else:
                logger.warning(f"Second element is not a DataFrame: {type(df_data)}")
                return data
        
        # Check if it's a DataFrame directly
        elif hasattr(data, 'to_dict'):
            logger.info("Data is a pandas DataFrame")
            logger.info(f"DataFrame shape: {data.shape}")
            logger.info(f"DataFrame columns: {data.columns.tolist()}")
            
            # Convert to proper format
            data_records = data.to_dict('records')
            logger.info(f"Converted to {len(data_records)} records")
            return data_records
        
        # Check if it's a list
        elif isinstance(data, list):
            logger.info(f"Data is a list with {len(data)} items")
            if len(data) > 0:
                logger.info(f"First item type: {type(data[0])}")
            return data
        
        else:
            logger.warning(f"Unexpected data format: {type(data)}")
            return data
    
    # === DISABLED SCREENER METHODS (keeping code for future use) ===
    
    def get_crypto_data(self, limit=50):
        """Get cryptocurrency data - DISABLED"""
        try:
            # Basic crypto query with minimal fields
            query = (Query()
                    .select('name', 'close', 'change', 'volume')
                    .limit(limit))
            
            data = query.get_scanner_data(cookies=self.cookies)
            logger.info(f"Retrieved {len(data)} crypto records")
            return data
            
        except Exception as e:
            logger.error(f"Error getting crypto data: {e}")
            return None
    
    def save_data(self, data, filename_prefix):
        """Save data to both JSON and CSV formats"""
        if not data:
            logger.warning(f"No data to save for {filename_prefix}")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Check if data is a pandas DataFrame or similar object
        try:
            # If it's a DataFrame, convert to list of dictionaries
            if hasattr(data, 'to_dict'):
                logger.info("Converting DataFrame to dictionary format")
                data_dict = data.to_dict('records')  # Convert DataFrame to list of dicts
                logger.info(f"Converted DataFrame with {len(data_dict)} records")
            elif isinstance(data, list) and len(data) > 0:
                # Check if the first item is not a dict (might be DataFrame string representation)
                if not isinstance(data[0], dict):
                    logger.warning(f"Data appears to be in unexpected format: {type(data[0])}")
                    logger.info(f"First item preview: {str(data[0])[:200]}...")
                    # Try to extract the actual data if it's a string representation
                    if len(data) >= 2 and isinstance(data[1], str):
                        logger.info("Attempting to parse DataFrame string representation")
                        # This means we have [count, dataframe_string] format
                        count = data[0]
                        df_string = data[1]
                        logger.info(f"Total records available: {count}")
                        logger.info("DataFrame string preview:")
                        logger.info(df_string[:500] + "..." if len(df_string) > 500 else df_string)
                        
                        # Save the raw string data for inspection
                        raw_file = self.output_dir / f"{filename_prefix}_raw_{timestamp}.txt"
                        with open(raw_file, 'w') as f:
                            f.write(f"Total records: {count}\n\n")
                            f.write("DataFrame representation:\n")
                            f.write(df_string)
                        logger.info(f"Raw data saved to: {raw_file}")
                        return
                    else:
                        data_dict = data
                else:
                    data_dict = data
            else:
                logger.warning(f"Unexpected data format: {type(data)}")
                data_dict = data
                
        except Exception as e:
            logger.error(f"Error processing data format: {e}")
            data_dict = data
        
        # Save as JSON
        json_file = self.output_dir / f"{filename_prefix}_{timestamp}.json"
        try:
            with open(json_file, 'w') as f:
                json.dump(data_dict, f, indent=2, default=str)
            logger.info(f"JSON saved: {json_file}")
        except Exception as e:
            logger.error(f"Failed to save JSON: {e}")
        
        # Save as CSV
        try:
            if isinstance(data_dict, list) and len(data_dict) > 0 and isinstance(data_dict[0], dict):
                df = pd.DataFrame(data_dict)
                csv_file = self.output_dir / f"{filename_prefix}_{timestamp}.csv"
                df.to_csv(csv_file, index=False)
                logger.info(f"CSV saved: {csv_file}")
                logger.info(f"Data summary: {len(data_dict)} records with columns: {list(data_dict[0].keys())}")
            else:
                logger.warning("Cannot save CSV - data is not in proper list of dictionaries format")
        except Exception as e:
            logger.warning(f"Could not save CSV: {e}")
    
    def collect_all_data(self):
        """Collect data from all screeners"""
        logger.info("Starting data collection cycle...")
        
        # === ACTIVE SCREENER ===
        # Small Caps Screener (replicating TradingView small caps view)
        small_caps_data = self.get_small_caps_screener()
        if small_caps_data:
            self.save_data(small_caps_data, "small_caps_screener")
        
        # === DISABLED SCREENERS (keeping code for future use) ===
        """
        # Market Overview
        market_data = self.get_market_overview()
        if market_data:
            self.save_data(market_data, "market_overview")
        
        # Top Gainers
        gainers_data = self.get_top_gainers()
        if gainers_data:
            self.save_data(gainers_data, "top_gainers")
        
        # Top Losers
        losers_data = self.get_top_losers()
        if losers_data:
            self.save_data(losers_data, "top_losers")
        
        # High Volume
        volume_data = self.get_high_volume_stocks()
        if volume_data:
            self.save_data(volume_data, "high_volume")
        
        # Value Stocks
        value_data = self.get_value_stocks()
        if value_data:
            self.save_data(value_data, "value_stocks")
        
        # Growth Stocks
        growth_data = self.get_growth_stocks()
        if growth_data:
            self.save_data(growth_data, "growth_stocks")
        
        # Oversold Stocks
        oversold_data = self.get_oversold_stocks()
        if oversold_data:
            self.save_data(oversold_data, "oversold_stocks")
        
        # Cryptocurrency data
        crypto_data = self.get_crypto_data()
        if crypto_data:
            self.save_data(crypto_data, "crypto_overview")
        """
        
        logger.info("Data collection cycle completed")
    
    def run_continuous(self, interval_minutes=5):
        """Run the data collection continuously at specified intervals"""
        def job():
            try:
                self.collect_all_data()
            except Exception as e:
                logger.error(f"Error in scheduled job: {e}")
        
        logger.info(f"Starting continuous data collection every {interval_minutes} minutes")
        schedule.every(interval_minutes).minutes.do(job)
        
        try:
            # Run once immediately
            job()
            
            while True:
                schedule.run_pending()
                import time
                time.sleep(60)  # Check every minute
                
        except KeyboardInterrupt:
            logger.info("Stopping continuous data collection...")

def create_custom_screener_examples():
    """Examples of creating custom screeners - DISABLED"""
    """
    collector = TradingViewDataCollector()
    
    # Example 1: Large cap stocks (sorted by market cap)
    large_cap_query = (Query()
                      .select('name', 'close', 'market_cap_basic')
                      .order_by('market_cap_basic', ascending=False)
                      .limit(20))
    
    large_cap_data = collector.get_custom_screener(large_cap_query)
    if large_cap_data:
        collector.save_data(large_cap_data, "large_cap_stocks")
    
    # Example 2: High volume stocks
    volume_query = (Query()
                   .select('name', 'close', 'volume', 'change')
                   .order_by('volume', ascending=False)
                   .limit(25))
    
    volume_data = collector.get_custom_screener(volume_query)
    if volume_data:
        collector.save_data(volume_data, "high_volume_stocks")
    
    # Example 3: Biggest movers (by absolute change)
    movers_query = (Query()
                   .select('name', 'close', 'change', 'volume')
                   .order_by('change', ascending=False)
                   .limit(30))
    
    movers_data = collector.get_custom_screener(movers_query)
    if movers_data:
        collector.save_data(movers_data, "biggest_movers")
    """
    logger.info("Custom screener examples are disabled - only running small caps screener")

def main():
    """Main function to run the data collector - SMALL CAPS SCREENER ONLY"""
    
    # Configuration
    OUTPUT_DIR = "tradingview_data"
    INTERVAL_MINUTES = 5  # Collect data every 5 minutes
    BROWSER = "firefox"  # Can be "firefox", "chrome", "edge", etc.
    
    try:
        # Initialize the data collector
        collector = TradingViewDataCollector(
            output_dir=OUTPUT_DIR,
            browser=BROWSER
        )
        
        # Run ONLY the small caps screener
        logger.info("Running small caps screener only...")
        collector.collect_all_data()
        
        # DISABLED: Custom screener examples
        # logger.info("Running custom screener examples...")
        # create_custom_screener_examples()
        
        # Uncomment to start continuous collection
        # logger.info("Starting continuous data collection...")
        # collector.run_continuous(interval_minutes=INTERVAL_MINUTES)
        
    except Exception as e:
        logger.error(f"Error in main: {e}")

if __name__ == "__main__":
    main()