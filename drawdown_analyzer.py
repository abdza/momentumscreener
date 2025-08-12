#!/usr/bin/env python3
"""
Drawdown Analyzer
Analyzes successful tickers to find optimal stop-loss levels by examining
how much they dropped before hitting 30%+ gains.
"""

import json
import glob
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
import statistics

class DrawdownAnalyzer:
    def __init__(self, 
                 results_file="momentum_data/validation_results.json",
                 momentum_data_dir="momentum_data"):
        self.results_file = Path(results_file)
        self.momentum_data_dir = Path(momentum_data_dir)
        self.load_results()
        self.load_alert_files()
        
    def load_results(self):
        """Load validation results to get successful tickers"""
        with open(self.results_file, 'r') as f:
            data = json.load(f)
        
        self.all_results = data['results']
        self.successful_tickers = data['successful_tickers']
        
        print(f"Loaded {len(self.successful_tickers)} successful tickers for drawdown analysis")
    
    def load_alert_files(self):
        """Load all alert files to track price movements"""
        alert_files = sorted(list(self.momentum_data_dir.glob("alerts_*.json")))
        self.alerts_by_ticker = defaultdict(list)
        
        print(f"Loading {len(alert_files)} alert files...")
        
        for file_path in alert_files:
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                
                timestamp = self._parse_timestamp(data['timestamp'])
                
                # Extract all tickers and their prices from this timestamp
                all_alerts = []
                
                # Price spikes
                for alert in data.get('price_spikes', []):
                    all_alerts.append({
                        'ticker': alert['ticker'],
                        'timestamp': timestamp,
                        'price': alert['current_price'],
                        'change_pct': alert['change_pct'],
                        'alert_type': 'price_spike'
                    })
                
                # Premarket alerts
                for alert in data.get('premarket_volume_alerts', []) + data.get('premarket_price_alerts', []):
                    all_alerts.append({
                        'ticker': alert['ticker'],
                        'timestamp': timestamp,
                        'price': alert['current_price'],
                        'change_pct': alert.get('premarket_change', 0),
                        'alert_type': 'premarket'
                    })
                
                # Group by ticker
                for alert in all_alerts:
                    self.alerts_by_ticker[alert['ticker']].append(alert)
                    
            except Exception as e:
                continue
        
        print(f"Loaded price data for {len(self.alerts_by_ticker)} tickers")
    
    def _parse_timestamp(self, timestamp_str):
        """Parse timestamp from various formats"""
        try:
            return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except:
            try:
                return datetime.fromisoformat(timestamp_str)
            except:
                for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"]:
                    try:
                        return datetime.strptime(timestamp_str, fmt)
                    except:
                        continue
        raise ValueError(f"Could not parse timestamp: {timestamp_str}")
    
    def analyze_ticker_drawdown(self, ticker):
        """Analyze drawdown pattern for a specific successful ticker"""
        if ticker not in self.successful_tickers:
            return None
        
        ticker_result = self.all_results[ticker]
        alert_time = datetime.fromisoformat(ticker_result['first_seen'])
        alert_price = ticker_result['alert_price']
        max_gain = ticker_result['max_gain']
        
        # Get all price points for this ticker on the same day
        ticker_prices = self.alerts_by_ticker.get(ticker, [])
        
        if not ticker_prices:
            return None
        
        # Filter to prices after the alert time on the same day
        same_day_prices = []
        alert_date = alert_time.date()
        
        for price_point in ticker_prices:
            if price_point['timestamp'].date() == alert_date and price_point['timestamp'] >= alert_time:
                same_day_prices.append(price_point)
        
        if len(same_day_prices) < 2:
            return None
        
        # Sort by timestamp
        same_day_prices.sort(key=lambda x: x['timestamp'])
        
        # Calculate drawdown from alert price
        max_drawdown_pct = 0
        min_price_seen = alert_price
        max_price_seen = alert_price
        
        # Track price progression
        price_progression = [{
            'timestamp': alert_time,
            'price': alert_price,
            'change_from_alert': 0,
            'drawdown_from_alert': 0
        }]
        
        for price_point in same_day_prices:
            current_price = price_point['price']
            
            # Update min/max
            min_price_seen = min(min_price_seen, current_price)
            max_price_seen = max(max_price_seen, current_price)
            
            # Calculate change from alert price
            change_from_alert = ((current_price - alert_price) / alert_price) * 100
            
            # Calculate drawdown (negative change)
            if current_price < alert_price:
                drawdown = ((alert_price - current_price) / alert_price) * 100
                max_drawdown_pct = max(max_drawdown_pct, drawdown)
            else:
                drawdown = 0
            
            price_progression.append({
                'timestamp': price_point['timestamp'],
                'price': current_price,
                'change_from_alert': change_from_alert,
                'drawdown_from_alert': drawdown
            })
        
        # Calculate final metrics
        final_max_gain = ((max_price_seen - alert_price) / alert_price) * 100
        final_max_drawdown = ((alert_price - min_price_seen) / alert_price) * 100
        
        return {
            'ticker': ticker,
            'alert_price': alert_price,
            'alert_time': alert_time,
            'max_price_seen': max_price_seen,
            'min_price_seen': min_price_seen,
            'max_gain_calculated': final_max_gain,
            'max_gain_reported': max_gain,
            'max_drawdown_pct': final_max_drawdown,
            'price_progression': price_progression,
            'data_points': len(same_day_prices)
        }
    
    def analyze_all_successful_drawdowns(self):
        """Analyze drawdowns for all successful tickers"""
        drawdown_data = []
        
        print("Analyzing drawdowns for successful tickers...")
        
        for i, ticker in enumerate(self.successful_tickers, 1):
            print(f"Processing {ticker} ({i}/{len(self.successful_tickers)})...")
            
            analysis = self.analyze_ticker_drawdown(ticker)
            if analysis and analysis['data_points'] >= 2:
                drawdown_data.append(analysis)
        
        print(f"Successfully analyzed {len(drawdown_data)} tickers with sufficient data")
        return drawdown_data
    
    def calculate_stop_loss_recommendations(self, drawdown_data):
        """Calculate optimal stop-loss levels based on drawdown analysis"""
        
        if not drawdown_data:
            return None
        
        # Extract drawdown percentages
        drawdowns = [data['max_drawdown_pct'] for data in drawdown_data if data['max_drawdown_pct'] > 0]
        
        if not drawdowns:
            return {
                'message': 'No significant drawdowns found in successful tickers',
                'recommendation': 'Most successful tickers did not drop below alert price'
            }
        
        # Calculate statistics
        max_drawdown = max(drawdowns)
        avg_drawdown = statistics.mean(drawdowns)
        median_drawdown = statistics.median(drawdowns)
        
        # Calculate percentiles for stop-loss recommendations
        drawdowns_sorted = sorted(drawdowns)
        n = len(drawdowns_sorted)
        
        percentile_75 = drawdowns_sorted[int(0.75 * n)] if n > 0 else 0
        percentile_90 = drawdowns_sorted[int(0.90 * n)] if n > 0 else 0
        percentile_95 = drawdowns_sorted[int(0.95 * n)] if n > 0 else 0
        
        # Calculate how many would be saved with different stop-loss levels
        stop_loss_analysis = {}
        for stop_level in [5, 10, 15, 20, 25]:
            tickers_stopped = sum(1 for dd in drawdowns if dd >= stop_level)
            percentage_stopped = (tickers_stopped / len(drawdowns)) * 100
            stop_loss_analysis[stop_level] = {
                'tickers_stopped': tickers_stopped,
                'percentage_stopped': percentage_stopped,
                'tickers_saved': len(drawdowns) - tickers_stopped
            }
        
        return {
            'total_analyzed': len(drawdown_data),
            'tickers_with_drawdowns': len(drawdowns),
            'max_drawdown': max_drawdown,
            'avg_drawdown': avg_drawdown,
            'median_drawdown': median_drawdown,
            'percentile_75': percentile_75,
            'percentile_90': percentile_90,
            'percentile_95': percentile_95,
            'stop_loss_analysis': stop_loss_analysis,
            'individual_drawdowns': drawdowns
        }
    
    def generate_comprehensive_report(self):
        """Generate comprehensive drawdown and stop-loss analysis"""
        print("=" * 80)
        print("DRAWDOWN & STOP-LOSS ANALYSIS FOR SUCCESSFUL TICKERS")
        print("=" * 80)
        
        # Analyze all successful tickers
        drawdown_data = self.analyze_all_successful_drawdowns()
        
        if not drawdown_data:
            print("❌ No sufficient data found for drawdown analysis")
            return
        
        # Calculate stop-loss recommendations
        stop_loss_metrics = self.calculate_stop_loss_recommendations(drawdown_data)
        
        if 'message' in stop_loss_metrics:
            print(f"✅ {stop_loss_metrics['message']}")
            print(f"💡 {stop_loss_metrics['recommendation']}")
            return
        
        print(f"\n📊 ANALYSIS SUMMARY")
        print("-" * 50)
        print(f"Successful tickers analyzed: {stop_loss_metrics['total_analyzed']}")
        print(f"Tickers with price drawdowns: {stop_loss_metrics['tickers_with_drawdowns']}")
        print(f"Tickers that never dropped below alert price: {stop_loss_metrics['total_analyzed'] - stop_loss_metrics['tickers_with_drawdowns']}")
        
        if stop_loss_metrics['tickers_with_drawdowns'] > 0:
            print(f"\n📉 DRAWDOWN STATISTICS")
            print("-" * 50)
            print(f"Maximum drawdown seen: {stop_loss_metrics['max_drawdown']:.1f}%")
            print(f"Average drawdown: {stop_loss_metrics['avg_drawdown']:.1f}%")
            print(f"Median drawdown: {stop_loss_metrics['median_drawdown']:.1f}%")
            print(f"75th percentile: {stop_loss_metrics['percentile_75']:.1f}%")
            print(f"90th percentile: {stop_loss_metrics['percentile_90']:.1f}%")
            print(f"95th percentile: {stop_loss_metrics['percentile_95']:.1f}%")
            
            print(f"\n🛑 STOP-LOSS ANALYSIS")
            print("-" * 50)
            print("Stop Level | Tickers Stopped | % Stopped | Winners Saved")
            print("-" * 50)
            
            for stop_level, analysis in stop_loss_metrics['stop_loss_analysis'].items():
                print(f"    {stop_level:2d}%    |      {analysis['tickers_stopped']:2d}        |   {analysis['percentage_stopped']:5.1f}%   |     {analysis['tickers_saved']:2d}")
        
        print(f"\n🎯 RECOMMENDATIONS")
        print("-" * 50)
        
        no_drawdown_count = stop_loss_metrics['total_analyzed'] - stop_loss_metrics['tickers_with_drawdowns']
        no_drawdown_pct = (no_drawdown_count / stop_loss_metrics['total_analyzed']) * 100
        
        print(f"1. {no_drawdown_pct:.1f}% of winners never dropped below alert price")
        
        if stop_loss_metrics['tickers_with_drawdowns'] > 0:
            # Recommend based on percentiles
            conservative_stop = stop_loss_metrics['percentile_75']
            moderate_stop = stop_loss_metrics['percentile_90'] 
            aggressive_stop = stop_loss_metrics['percentile_95']
            
            print(f"2. CONSERVATIVE stop-loss: {conservative_stop:.1f}% (saves 75% of winners)")
            print(f"3. MODERATE stop-loss: {moderate_stop:.1f}% (saves 90% of winners)")
            print(f"4. AGGRESSIVE stop-loss: {aggressive_stop:.1f}% (saves 95% of winners)")
            
            # Find optimal stop-loss
            best_stop = None
            best_ratio = 0
            
            for stop_level, analysis in stop_loss_metrics['stop_loss_analysis'].items():
                # Calculate risk/reward ratio (winners saved vs simplicity)
                winners_saved_pct = (analysis['tickers_saved'] / stop_loss_metrics['tickers_with_drawdowns']) * 100
                if winners_saved_pct >= 80:  # Must save at least 80% of winners
                    ratio = winners_saved_pct / stop_level  # Higher is better
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_stop = stop_level
            
            if best_stop:
                print(f"\n💡 OPTIMAL STOP-LOSS: {best_stop}%")
                saved = stop_loss_metrics['stop_loss_analysis'][best_stop]['tickers_saved']
                total = stop_loss_metrics['tickers_with_drawdowns']
                print(f"   Saves {saved}/{total} winners ({saved/total*100:.1f}%)")
                print(f"   Simple round number for easy implementation")
        
        # Show individual examples
        print(f"\n📋 INDIVIDUAL EXAMPLES")
        print("-" * 50)
        
        # Sort by drawdown to show examples
        drawdown_data.sort(key=lambda x: x['max_drawdown_pct'], reverse=True)
        
        print("Ticker | Alert Price | Max Drawdown | Final Gain | Data Points")
        print("-" * 65)
        
        for data in drawdown_data[:10]:  # Show top 10
            print(f"{data['ticker']:6} | ${data['alert_price']:10.2f} | {data['max_drawdown_pct']:11.1f}% | "
                  f"{data['max_gain_calculated']:9.1f}% | {data['data_points']:11d}")
        
        if len(drawdown_data) > 10:
            print(f"... and {len(drawdown_data) - 10} more")
        
        print("\n" + "=" * 80)

def main():
    analyzer = DrawdownAnalyzer()
    analyzer.generate_comprehensive_report()

if __name__ == "__main__":
    main()