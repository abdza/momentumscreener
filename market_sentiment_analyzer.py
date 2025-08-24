#!/usr/bin/env python3
"""
Market Sentiment Analyzer for Momentum Trading
Analyzes market conditions on days with winners vs losers to identify patterns

Tests various market indicators:
- VIX (fear/greed index)
- SPY (S&P 500 performance) 
- QQQ (NASDAQ performance)
- Sector ETFs (XLV health, XLK tech, etc.)
- Volume patterns in major indices
- Market breadth indicators
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import statistics
from collections import defaultdict
import json

class MarketSentimentAnalyzer:
    def __init__(self):
        # Market indicators to track
        self.market_symbols = {
            'SPY': 'S&P 500 ETF',
            'QQQ': 'NASDAQ ETF', 
            'IWM': 'Russell 2000 (Small Cap)',
            'VIX': 'Volatility Index',
            'DIA': 'Dow Jones ETF'
        }
        
        # Sector ETFs - important for our biotech/health focus
        self.sector_etfs = {
            'XLV': 'Health Care',      # Many of our winners were health
            'XLK': 'Technology',       # Tech stocks 
            'XLB': 'Materials',        # Basic materials
            'XLE': 'Energy',           # Energy sector
            'XLF': 'Financial',        # Financial sector
            'XLI': 'Industrial',       # Industrial
            'XLP': 'Consumer Staples', # Consumer staples
            'XLY': 'Consumer Discretionary', # Consumer discretionary
            'XLU': 'Utilities',        # Utilities
            'XLRE': 'Real Estate',     # Real estate
            'IBB': 'Biotech ETF',      # Biotech specific - very relevant!
        }
        
        # Our known winners and losers from analysis
        self.trading_days_results = {
            '2025-08-15': {
                'winners': ['SRXH', 'PGEN'],  # 2/8 = 25% success rate
                'losers': ['PMNT', 'PPSI', 'DFLI', 'TIVC', 'CODX', 'MCRP'],
                'success_rate': 25.0
            },
            '2025-08-18': {
                'winners': ['SNGX', 'ASBP', 'PPCB'],  # 3/6 = 50% success rate  
                'losers': ['VTAK', 'ADAP', 'WGRX'],
                'success_rate': 50.0
            },
            '2025-08-19': {
                'winners': ['LASE', 'TZUP', 'GXAI'],  # 3/14 = 21.4% success rate
                'losers': ['MB', 'ILLR', 'BNR', 'SNGX', 'APUS', 'PRFX', 'ADD', 'VCIG', 'TLPH', 'VELO', 'PSIG'],
                'success_rate': 21.4
            },
            '2025-08-23': {
                'winners': [],  # 0/3 = 0% success rate
                'losers': ['SHMD', 'HTCR', 'OCG'], 
                'success_rate': 0.0
            }
        }
    
    def fetch_market_data(self, start_date, end_date):
        """Fetch market data for analysis period"""
        print(f"📈 Fetching market data from {start_date} to {end_date}")
        
        market_data = {}
        
        # Fetch major market indicators
        all_symbols = {**self.market_symbols, **self.sector_etfs}
        
        for symbol, name in all_symbols.items():
            try:
                print(f"  Fetching {symbol} ({name})...")
                ticker = yf.Ticker(symbol)
                hist = ticker.history(start=start_date, end=end_date, interval='1d')
                
                if not hist.empty:
                    # Calculate daily returns, volume ratios, etc.
                    hist['Daily_Return'] = hist['Close'].pct_change() * 100
                    hist['Volume_MA'] = hist['Volume'].rolling(window=10).mean()
                    hist['Volume_Ratio'] = hist['Volume'] / hist['Volume_MA']
                    
                    market_data[symbol] = hist
                else:
                    print(f"    ⚠️  No data for {symbol}")
                    
            except Exception as e:
                print(f"    ❌ Error fetching {symbol}: {e}")
        
        return market_data
    
    def analyze_day_conditions(self, date_str, market_data):
        """Analyze market conditions for a specific day"""
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        conditions = {
            'date': date_str,
            'market_indicators': {},
            'sector_performance': {},
            'volatility': {},
            'volume_patterns': {}
        }
        
        # Analyze major market performance
        for symbol in self.market_symbols.keys():
            if symbol in market_data:
                df = market_data[symbol]
                day_data = df[df.index.date == date]
                
                if not day_data.empty:
                    row = day_data.iloc[0]
                    conditions['market_indicators'][symbol] = {
                        'daily_return': row.get('Daily_Return', 0),
                        'volume_ratio': row.get('Volume_Ratio', 1),
                        'close': row['Close'],
                        'volume': row['Volume']
                    }
        
        # Analyze sector ETF performance
        for symbol in self.sector_etfs.keys():
            if symbol in market_data:
                df = market_data[symbol]
                day_data = df[df.index.date == date]
                
                if not day_data.empty:
                    row = day_data.iloc[0]
                    conditions['sector_performance'][symbol] = {
                        'daily_return': row.get('Daily_Return', 0),
                        'volume_ratio': row.get('Volume_Ratio', 1),
                        'close': row['Close']
                    }
        
        # Special analysis for VIX (fear/greed)
        if 'VIX' in conditions['market_indicators']:
            vix_level = conditions['market_indicators']['VIX']['close']
            if vix_level < 15:
                conditions['volatility']['regime'] = 'Low Volatility (Complacent)'
            elif vix_level < 20:
                conditions['volatility']['regime'] = 'Normal Volatility'
            elif vix_level < 30:
                conditions['volatility']['regime'] = 'Elevated Volatility'
            else:
                conditions['volatility']['regime'] = 'High Volatility (Fear)'
            
            conditions['volatility']['vix_level'] = vix_level
        
        return conditions
    
    def compare_winning_vs_losing_days(self):
        """Compare market conditions on winning days vs losing days"""
        # Fetch market data for our analysis period
        start_date = '2025-08-10'  # A few days before our first data
        end_date = '2025-08-25'    # A few days after our last data
        
        market_data = self.fetch_market_data(start_date, end_date)
        
        print(f"\n📊 ANALYZING MARKET CONDITIONS ON ALERT DAYS")
        print("=" * 60)
        
        # Analyze each day
        day_conditions = {}
        for date_str in self.trading_days_results.keys():
            conditions = self.analyze_day_conditions(date_str, market_data)
            day_conditions[date_str] = conditions
            
            result = self.trading_days_results[date_str]
            success_rate = result['success_rate']
            
            print(f"\n📅 {date_str} - Success Rate: {success_rate}%")
            print("-" * 40)
            
            # Market performance
            if conditions['market_indicators']:
                print("🏛️  MARKET PERFORMANCE:")
                for symbol, data in conditions['market_indicators'].items():
                    name = self.market_symbols.get(symbol, symbol)
                    return_pct = data.get('daily_return', 0)
                    vol_ratio = data.get('volume_ratio', 1)
                    print(f"  {symbol:4} ({name}): {return_pct:+5.2f}% | Vol: {vol_ratio:.1f}x")
            
            # Sector performance  
            if conditions['sector_performance']:
                print("🏭 SECTOR PERFORMANCE:")
                sector_items = list(conditions['sector_performance'].items())[:5]  # Top 5
                for symbol, data in sector_items:
                    name = self.sector_etfs.get(symbol, symbol)
                    return_pct = data.get('daily_return', 0)
                    print(f"  {symbol:4} ({name}): {return_pct:+5.2f}%")
            
            # Volatility regime
            if conditions['volatility']:
                print(f"📈 VOLATILITY: {conditions['volatility'].get('regime', 'Unknown')}")
                if 'vix_level' in conditions['volatility']:
                    print(f"  VIX Level: {conditions['volatility']['vix_level']:.1f}")
        
        return day_conditions
    
    def find_patterns(self, day_conditions):
        """Find patterns that correlate with successful days"""
        print(f"\n🔍 PATTERN ANALYSIS")
        print("=" * 60)
        
        # Separate good days (>25% success) from bad days (≤25% success)
        good_days = []  # 50%, 25%
        bad_days = []   # 21.4%, 0%
        
        for date_str, result in self.trading_days_results.items():
            conditions = day_conditions.get(date_str, {})
            if result['success_rate'] >= 25:
                good_days.append((date_str, conditions, result['success_rate']))
            else:
                bad_days.append((date_str, conditions, result['success_rate']))
        
        print(f"📈 Good Days (≥25% success): {len(good_days)}")
        print(f"📉 Bad Days (<25% success): {len(bad_days)}")
        
        # Analyze patterns
        patterns = self.analyze_market_patterns(good_days, bad_days)
        
        return patterns
    
    def analyze_market_patterns(self, good_days, bad_days):
        """Analyze patterns between good and bad days"""
        patterns = {
            'market_indicators': {},
            'sector_patterns': {},
            'volatility_patterns': {},
            'recommendations': []
        }
        
        # Analyze major market indicators
        print(f"\n🏛️  MARKET INDICATOR PATTERNS:")
        print("-" * 40)
        
        for symbol in self.market_symbols.keys():
            good_returns = []
            bad_returns = []
            good_volumes = []
            bad_volumes = []
            
            # Collect data from good days
            for date_str, conditions, success_rate in good_days:
                if symbol in conditions.get('market_indicators', {}):
                    data = conditions['market_indicators'][symbol]
                    good_returns.append(data.get('daily_return', 0))
                    good_volumes.append(data.get('volume_ratio', 1))
            
            # Collect data from bad days  
            for date_str, conditions, success_rate in bad_days:
                if symbol in conditions.get('market_indicators', {}):
                    data = conditions['market_indicators'][symbol]
                    bad_returns.append(data.get('daily_return', 0))
                    bad_volumes.append(data.get('volume_ratio', 1))
            
            # Calculate averages and compare
            if good_returns and bad_returns:
                good_avg = statistics.mean(good_returns)
                bad_avg = statistics.mean(bad_returns)
                name = self.market_symbols[symbol]
                
                print(f"{symbol:4} ({name[:20]:20}): Good days: {good_avg:+5.2f}% | Bad days: {bad_avg:+5.2f}%")
                
                patterns['market_indicators'][symbol] = {
                    'good_day_avg': good_avg,
                    'bad_day_avg': bad_avg,
                    'difference': good_avg - bad_avg,
                    'name': name
                }
        
        # Analyze sector patterns
        print(f"\n🏭 SECTOR ETF PATTERNS:")
        print("-" * 40)
        
        sector_analysis = {}
        for symbol in self.sector_etfs.keys():
            good_returns = []
            bad_returns = []
            
            # Collect data
            for date_str, conditions, success_rate in good_days:
                if symbol in conditions.get('sector_performance', {}):
                    data = conditions['sector_performance'][symbol]
                    good_returns.append(data.get('daily_return', 0))
            
            for date_str, conditions, success_rate in bad_days:
                if symbol in conditions.get('sector_performance', {}):
                    data = conditions['sector_performance'][symbol]
                    bad_returns.append(data.get('daily_return', 0))
            
            if good_returns and bad_returns:
                good_avg = statistics.mean(good_returns)
                bad_avg = statistics.mean(bad_returns)
                difference = good_avg - bad_avg
                name = self.sector_etfs[symbol]
                
                sector_analysis[symbol] = {
                    'good_day_avg': good_avg,
                    'bad_day_avg': bad_avg, 
                    'difference': difference,
                    'name': name
                }
        
        # Sort sectors by biggest positive difference (good days vs bad days)
        sorted_sectors = sorted(sector_analysis.items(), key=lambda x: x[1]['difference'], reverse=True)
        
        for symbol, data in sorted_sectors[:8]:  # Top 8 sectors
            print(f"{symbol:4} ({data['name'][:20]:20}): Good: {data['good_day_avg']:+5.2f}% | Bad: {data['bad_day_avg']:+5.2f}% | Diff: {data['difference']:+5.2f}%")
        
        patterns['sector_patterns'] = dict(sorted_sectors)
        
        # Volatility analysis
        print(f"\n📈 VOLATILITY PATTERNS:")
        print("-" * 40)
        
        good_vix_levels = []
        bad_vix_levels = []
        
        for date_str, conditions, success_rate in good_days:
            if 'vix_level' in conditions.get('volatility', {}):
                good_vix_levels.append(conditions['volatility']['vix_level'])
        
        for date_str, conditions, success_rate in bad_days:
            if 'vix_level' in conditions.get('volatility', {}):
                bad_vix_levels.append(conditions['volatility']['vix_level'])
        
        if good_vix_levels and bad_vix_levels:
            good_vix_avg = statistics.mean(good_vix_levels)
            bad_vix_avg = statistics.mean(bad_vix_levels)
            
            print(f"VIX on Good Days: {good_vix_avg:.1f}")
            print(f"VIX on Bad Days: {bad_vix_avg:.1f}")
            print(f"Difference: {good_vix_avg - bad_vix_avg:+.1f}")
            
            patterns['volatility_patterns'] = {
                'good_day_vix': good_vix_avg,
                'bad_day_vix': bad_vix_avg,
                'difference': good_vix_avg - bad_vix_avg
            }
        
        # Generate recommendations
        self.generate_recommendations(patterns)
        
        return patterns
    
    def generate_recommendations(self, patterns):
        """Generate trading recommendations based on patterns"""
        print(f"\n💡 TRADING RECOMMENDATIONS:")
        print("=" * 60)
        
        recommendations = []
        
        # Market indicator recommendations
        if patterns['market_indicators']:
            best_market_indicator = max(patterns['market_indicators'].items(), 
                                      key=lambda x: x[1]['difference'])
            symbol, data = best_market_indicator
            
            if data['difference'] > 1.0:  # >1% difference
                rec = f"✅ Trade when {symbol} is positive: Good days avg {data['good_day_avg']:+.1f}% vs bad days {data['bad_day_avg']:+.1f}%"
                recommendations.append(rec)
                print(rec)
        
        # Sector recommendations
        if patterns['sector_patterns']:
            top_sectors = list(patterns['sector_patterns'].items())[:3]
            for symbol, data in top_sectors:
                if data['difference'] > 1.5:  # >1.5% difference
                    rec = f"✅ Monitor {symbol} ({data['name']}): {data['difference']:+.1f}% better on winning days"
                    recommendations.append(rec) 
                    print(rec)
        
        # VIX recommendations
        if patterns['volatility_patterns']:
            vix_diff = patterns['volatility_patterns']['difference']
            good_vix = patterns['volatility_patterns']['good_day_vix']
            
            if abs(vix_diff) > 2.0:
                if vix_diff > 0:
                    rec = f"✅ Trade when VIX is elevated (>{good_vix:.0f}): Higher success on volatile days"
                else:
                    rec = f"✅ Trade when VIX is low (<{good_vix:.0f}): Higher success on calm days"
                recommendations.append(rec)
                print(rec)
        
        if not recommendations:
            print("❌ No strong patterns found with current data")
            print("💡 Need more trading days for statistical significance")
        
        return recommendations
    
    def save_analysis(self, day_conditions, patterns, filename='market_sentiment_analysis.json'):
        """Save analysis results to JSON file"""
        analysis_data = {
            'analysis_date': datetime.now().isoformat(),
            'trading_days_analyzed': len(self.trading_days_results),
            'day_conditions': day_conditions,
            'patterns': patterns,
            'summary': {
                'good_days': len([d for d in self.trading_days_results.values() if d['success_rate'] >= 25]),
                'bad_days': len([d for d in self.trading_days_results.values() if d['success_rate'] < 25]),
                'avg_success_rate': statistics.mean([d['success_rate'] for d in self.trading_days_results.values()])
            }
        }
        
        # Convert datetime objects to strings for JSON serialization
        def convert_datetime(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            elif hasattr(obj, 'isoformat'):
                return obj.isoformat()
            return str(obj)
        
        with open(filename, 'w') as f:
            json.dump(analysis_data, f, indent=2, default=convert_datetime)
        
        print(f"\n💾 Analysis saved to {filename}")

def main():
    """Run the market sentiment analysis"""
    print("🔬 MARKET SENTIMENT ANALYSIS FOR MOMENTUM TRADING")
    print("=" * 60)
    print("Analyzing market conditions on days with winners vs losers")
    print("Looking for patterns in VIX, SPY, QQQ, sector ETFs, etc.")
    print()
    
    analyzer = MarketSentimentAnalyzer()
    
    # Analyze market conditions
    day_conditions = analyzer.compare_winning_vs_losing_days()
    
    # Find patterns
    patterns = analyzer.find_patterns(day_conditions)
    
    # Save results
    analyzer.save_analysis(day_conditions, patterns)
    
    print(f"\n✅ Analysis complete!")
    print("💡 Use these insights to improve alert timing and filtering")

if __name__ == "__main__":
    main()