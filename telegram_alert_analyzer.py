#!/usr/bin/env python3
"""
Telegram Alert Analysis Script
Analyzes telegram alert data from the momentum_data folder to extract insights and performance metrics.
Focuses on data from this week (20250830 onwards) to provide actionable insights for improving alerts.
"""

import json
import os
import glob
from collections import defaultdict, Counter
from datetime import datetime, timedelta
import statistics
import sys

class TelegramAlertAnalyzer:
    def __init__(self, data_folder):
        self.data_folder = data_folder
        self.start_date = "20250830"  # Start from this week
        self.alerts_data = []
        self.ticker_appearances = defaultdict(list)
        self.sector_data = defaultdict(list)
        self.hourly_distribution = defaultdict(int)
        self.alert_type_stats = defaultdict(int)
        self.metrics_by_type = {
            'volume_climbers': [],
            'volume_newcomers': [],
            'price_spikes': [],
            'premarket_volume_alerts': [],
            'premarket_price_alerts': []
        }
        
    def load_alert_files(self):
        """Load all alert files from the specified date range."""
        print(f"Loading alert files from {self.start_date} onwards...")
        
        pattern = f"{self.data_folder}/alerts_{self.start_date}*.json"
        files = glob.glob(pattern)
        
        # Also include September files
        sept_pattern = f"{self.data_folder}/alerts_202509*.json"
        files.extend(glob.glob(sept_pattern))
        
        files.sort()
        print(f"Found {len(files)} alert files to analyze")
        
        loaded_count = 0
        for file_path in files:
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    self.alerts_data.append(data)
                    loaded_count += 1
                    
                    # Extract timestamp info for hourly analysis
                    timestamp = data.get('timestamp', '')
                    if timestamp:
                        try:
                            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            hour = dt.hour
                            self.hourly_distribution[hour] += 1
                        except:
                            pass
                            
            except Exception as e:
                print(f"Error loading {file_path}: {e}")
                
        print(f"Successfully loaded {loaded_count} alert files")
        
    def analyze_alert_types(self):
        """Analyze distribution and performance of different alert types."""
        print("\n=== ALERT TYPE ANALYSIS ===")
        
        total_alerts = 0
        for alert_data in self.alerts_data:
            summary = alert_data.get('summary', {})
            for alert_type, count in summary.items():
                if alert_type.startswith('total_'):
                    clean_type = alert_type.replace('total_', '')
                    self.alert_type_stats[clean_type] += count
                    total_alerts += count
                    
        print(f"Total Alerts Sent: {total_alerts}")
        print("\nAlert Type Distribution:")
        for alert_type, count in sorted(self.alert_type_stats.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / total_alerts * 100) if total_alerts > 0 else 0
            print(f"  {alert_type}: {count} alerts ({percentage:.1f}%)")
            
    def analyze_tickers(self):
        """Analyze ticker frequency and performance patterns."""
        print("\n=== TICKER ANALYSIS ===")
        
        ticker_stats = defaultdict(lambda: {
            'appearances': 0,
            'alert_types': set(),
            'avg_volume': [],
            'avg_price': [],
            'avg_change_pct': [],
            'avg_relative_volume': [],
            'sectors': set(),
            'max_change_from_open': 0,
            'appearance_counts': [],
            'alert_types_counts': []
        })
        
        for alert_data in self.alerts_data:
            for alert_type in ['volume_climbers', 'volume_newcomers', 'price_spikes', 
                             'premarket_volume_alerts', 'premarket_price_alerts']:
                alerts = alert_data.get(alert_type, [])
                
                for alert in alerts:
                    ticker = alert.get('ticker')
                    if not ticker:
                        continue
                        
                    stats = ticker_stats[ticker]
                    stats['appearances'] += 1
                    stats['alert_types'].add(alert_type)
                    
                    # Collect metrics
                    if 'volume' in alert:
                        stats['avg_volume'].append(alert['volume'])
                    if 'price' in alert:
                        stats['avg_price'].append(alert['price'])
                    if 'change_pct' in alert:
                        stats['avg_change_pct'].append(alert['change_pct'])
                    if 'relative_volume' in alert:
                        stats['avg_relative_volume'].append(alert['relative_volume'])
                    if 'sector' in alert:
                        stats['sectors'].add(alert['sector'])
                    if 'change_from_open' in alert:
                        stats['max_change_from_open'] = max(stats['max_change_from_open'], 
                                                          alert['change_from_open'])
                    if 'appearance_count' in alert:
                        stats['appearance_counts'].append(alert['appearance_count'])
                    if 'alert_types_count' in alert:
                        stats['alert_types_counts'].append(alert['alert_types_count'])
        
        # Sort by frequency and show top performers
        sorted_tickers = sorted(ticker_stats.items(), 
                              key=lambda x: x[1]['appearances'], reverse=True)
        
        print(f"\nTop 20 Most Active Tickers:")
        print(f"{'Ticker':<8} {'Alerts':<7} {'Alert Types':<25} {'Avg Change%':<12} {'Avg RelVol':<12} {'Sector'}")
        print("-" * 90)
        
        for ticker, stats in sorted_tickers[:20]:
            avg_change = statistics.mean(stats['avg_change_pct']) if stats['avg_change_pct'] else 0
            avg_rel_vol = statistics.mean(stats['avg_relative_volume']) if stats['avg_relative_volume'] else 0
            alert_types_str = ','.join(sorted(stats['alert_types']))[:24]
            sector = list(stats['sectors'])[0] if stats['sectors'] else 'Unknown'
            
            print(f"{ticker:<8} {stats['appearances']:<7} {alert_types_str:<25} {avg_change:<12.2f} {avg_rel_vol:<12.2f} {sector}")
            
    def analyze_sectors(self):
        """Analyze sector distribution and performance."""
        print("\n=== SECTOR ANALYSIS ===")
        
        sector_stats = defaultdict(lambda: {
            'count': 0,
            'tickers': set(),
            'avg_change_pct': [],
            'avg_relative_volume': []
        })
        
        for alert_data in self.alerts_data:
            for alert_type in ['volume_climbers', 'volume_newcomers', 'price_spikes', 
                             'premarket_volume_alerts', 'premarket_price_alerts']:
                alerts = alert_data.get(alert_type, [])
                
                for alert in alerts:
                    sector = alert.get('sector', 'Unknown')
                    ticker = alert.get('ticker')
                    
                    if ticker:
                        sector_stats[sector]['count'] += 1
                        sector_stats[sector]['tickers'].add(ticker)
                        
                        if 'change_pct' in alert:
                            sector_stats[sector]['avg_change_pct'].append(alert['change_pct'])
                        if 'relative_volume' in alert:
                            sector_stats[sector]['avg_relative_volume'].append(alert['relative_volume'])
        
        print(f"Sector Performance (sorted by alert count):")
        print(f"{'Sector':<25} {'Alerts':<8} {'Unique Tickers':<15} {'Avg Change%':<12} {'Avg RelVol':<12}")
        print("-" * 80)
        
        sorted_sectors = sorted(sector_stats.items(), key=lambda x: x[1]['count'], reverse=True)
        for sector, stats in sorted_sectors:
            if sector is None:
                sector = "Unknown"
            avg_change = statistics.mean(stats['avg_change_pct']) if stats['avg_change_pct'] else 0
            avg_rel_vol = statistics.mean(stats['avg_relative_volume']) if stats['avg_relative_volume'] else 0
            
            print(f"{sector:<25} {stats['count']:<8} {len(stats['tickers']):<15} {avg_change:<12.2f} {avg_rel_vol:<12.2f}")
            
    def analyze_time_patterns(self):
        """Analyze when alerts are most active."""
        print("\n=== TIME PATTERN ANALYSIS ===")
        
        if not self.hourly_distribution:
            print("No time data available for analysis")
            return
            
        total_files = sum(self.hourly_distribution.values())
        print(f"Alert Activity by Hour (based on {total_files} alert files):")
        
        # Convert to more readable format
        hourly_stats = []
        for hour in range(24):
            count = self.hourly_distribution.get(hour, 0)
            percentage = (count / total_files * 100) if total_files > 0 else 0
            hourly_stats.append((hour, count, percentage))
            
        # Sort by count to find peak hours
        sorted_hours = sorted(hourly_stats, key=lambda x: x[1], reverse=True)
        
        print("\nPeak Activity Hours:")
        for hour, count, pct in sorted_hours[:8]:
            time_str = f"{hour:02d}:00-{hour:02d}:59"
            print(f"  {time_str}: {count} files ({pct:.1f}%)")
            
        print("\nHourly Distribution:")
        for hour, count, pct in hourly_stats:
            if count > 0:
                time_str = f"{hour:02d}:00"
                bar = "█" * int(pct / 2) if pct > 0 else ""
                print(f"  {time_str}: {bar} ({count})")
                
    def analyze_alert_quality(self):
        """Analyze quality metrics of alerts."""
        print("\n=== ALERT QUALITY METRICS ===")
        
        quality_metrics = {
            'high_relative_volume': [],  # > 3x
            'very_high_relative_volume': [],  # > 5x
            'significant_price_moves': [],  # > 5%
            'large_price_moves': [],  # > 10%
            'massive_price_moves': [],  # > 25%
            'flat_to_spike_patterns': [],  # change_from_open > 15%
        }
        
        all_metrics = {
            'relative_volumes': [],
            'change_pcts': [],
            'change_from_opens': [],
            'rank_changes': []
        }
        
        for alert_data in self.alerts_data:
            for alert_type in ['volume_climbers', 'volume_newcomers', 'price_spikes', 
                             'premarket_volume_alerts', 'premarket_price_alerts']:
                alerts = alert_data.get(alert_type, [])
                
                for alert in alerts:
                    ticker = alert.get('ticker')
                    if not ticker:
                        continue
                        
                    # Collect all metrics
                    rel_vol = alert.get('relative_volume', 0)
                    change_pct = alert.get('change_pct', 0)
                    change_from_open = alert.get('change_from_open', 0)
                    rank_change = alert.get('rank_change', 0)
                    
                    all_metrics['relative_volumes'].append(rel_vol)
                    all_metrics['change_pcts'].append(change_pct)
                    all_metrics['change_from_opens'].append(change_from_open)
                    all_metrics['rank_changes'].append(rank_change)
                    
                    # Quality classifications
                    if rel_vol > 3:
                        quality_metrics['high_relative_volume'].append(ticker)
                    if rel_vol > 5:
                        quality_metrics['very_high_relative_volume'].append(ticker)
                    if change_pct > 5:
                        quality_metrics['significant_price_moves'].append(ticker)
                    if change_pct > 10:
                        quality_metrics['large_price_moves'].append(ticker)
                    if change_pct > 25:
                        quality_metrics['massive_price_moves'].append(ticker)
                    if change_from_open > 15:
                        quality_metrics['flat_to_spike_patterns'].append(ticker)
        
        # Statistical analysis
        print("Statistical Overview:")
        for metric, values in all_metrics.items():
            if values:
                avg_val = statistics.mean(values)
                median_val = statistics.median(values)
                max_val = max(values)
                min_val = min(values)
                print(f"  {metric}: avg={avg_val:.2f}, median={median_val:.2f}, max={max_val:.2f}, min={min_val:.2f}")
        
        print("\nQuality Distribution:")
        total_alerts = sum(self.alert_type_stats.values())
        for quality, tickers in quality_metrics.items():
            count = len(tickers)
            percentage = (count / total_alerts * 100) if total_alerts > 0 else 0
            print(f"  {quality}: {count} alerts ({percentage:.1f}%)")
            
    def generate_insights(self):
        """Generate actionable insights based on the analysis."""
        print("\n" + "="*60)
        print("ACTIONABLE INSIGHTS AND RECOMMENDATIONS")
        print("="*60)
        
        # Calculate key statistics for insights
        total_alerts = sum(self.alert_type_stats.values())
        if total_alerts == 0:
            print("No alerts found in the analyzed period.")
            return
            
        # Alert type insights
        dominant_alert_type = max(self.alert_type_stats.items(), key=lambda x: x[1])
        print(f"\n1. ALERT TYPE PERFORMANCE:")
        print(f"   • Dominant alert type: {dominant_alert_type[0]} ({dominant_alert_type[1]} alerts)")
        print(f"   • Total alerts this week: {total_alerts}")
        
        if self.alert_type_stats.get('volume_climbers', 0) > total_alerts * 0.4:
            print(f"   → INSIGHT: Volume climbers dominate. Consider tightening volume thresholds.")
        
        if self.alert_type_stats.get('price_spikes', 0) < total_alerts * 0.1:
            print(f"   → INSIGHT: Few price spikes detected. Consider lowering price spike thresholds.")
            
        # Time-based insights
        if self.hourly_distribution:
            peak_hour = max(self.hourly_distribution.items(), key=lambda x: x[1])
            print(f"\n2. TIMING INSIGHTS:")
            print(f"   • Peak activity hour: {peak_hour[0]:02d}:00 ({peak_hour[1]} files)")
            
            # Market hours analysis
            market_hours = sum(self.hourly_distribution.get(h, 0) for h in range(9, 16))  # 9 AM - 4 PM EST
            premarket_hours = sum(self.hourly_distribution.get(h, 0) for h in range(4, 9))  # 4 AM - 9 AM EST
            after_hours = sum(self.hourly_distribution.get(h, 0) for h in [16, 17, 18, 19, 20])  # 4 PM - 8 PM EST
            
            total_files = sum(self.hourly_distribution.values())
            if market_hours > total_files * 0.6:
                print(f"   → INSIGHT: Most activity during market hours ({market_hours/total_files*100:.1f}%)")
            if premarket_hours > total_files * 0.3:
                print(f"   → INSIGHT: Significant premarket activity ({premarket_hours/total_files*100:.1f}%)")
        
        print(f"\n3. QUALITY RECOMMENDATIONS:")
        
        # Quality thresholds analysis
        all_rel_vols = []
        all_change_pcts = []
        for alert_data in self.alerts_data:
            for alert_type in ['volume_climbers', 'volume_newcomers', 'price_spikes']:
                alerts = alert_data.get(alert_type, [])
                for alert in alerts:
                    if 'relative_volume' in alert:
                        all_rel_vols.append(alert['relative_volume'])
                    if 'change_pct' in alert:
                        all_change_pcts.append(alert['change_pct'])
        
        if all_rel_vols:
            avg_rel_vol = statistics.mean(all_rel_vols)
            median_rel_vol = statistics.median(all_rel_vols)
            print(f"   • Avg relative volume: {avg_rel_vol:.2f}x, Median: {median_rel_vol:.2f}x")
            
            if median_rel_vol < 2.0:
                print(f"   → RECOMMENDATION: Increase minimum relative volume to 2.5x+")
            elif median_rel_vol > 5.0:
                print(f"   → RECOMMENDATION: Consider lowering relative volume threshold for more alerts")
                
        if all_change_pcts:
            avg_change = statistics.mean(all_change_pcts)
            median_change = statistics.median(all_change_pcts)
            print(f"   • Avg price change: {avg_change:.2f}%, Median: {median_change:.2f}%")
            
            if median_change < 3.0:
                print(f"   → RECOMMENDATION: Increase minimum price change threshold to 4%+")
            elif median_change > 15.0:
                print(f"   → RECOMMENDATION: Consider lowering price change threshold for earlier alerts")
        
        print(f"\n4. SYSTEM OPTIMIZATION:")
        print(f"   → Monitor top performing tickers for pattern recognition")
        print(f"   → Focus on sectors with highest relative volume averages")
        print(f"   → Consider separate thresholds for different market conditions")
        print(f"   → Implement ticker cooldown periods to reduce noise")
        
        print(f"\n5. PERFORMANCE TRACKING:")
        print(f"   → Track alert-to-significant-move conversion rate")
        print(f"   → Monitor false positive rates by alert type")
        print(f"   → Implement follow-up tracking for alerted tickers")
        print(f"   → Consider momentum scoring system")
        
    def run_analysis(self):
        """Run the complete analysis."""
        print("Telegram Alert Analysis Report")
        print("="*50)
        print(f"Analysis Period: From {self.start_date} onwards")
        print(f"Current Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        self.load_alert_files()
        
        if not self.alerts_data:
            print("No alert data found for analysis.")
            return
            
        self.analyze_alert_types()
        self.analyze_tickers()
        self.analyze_sectors()
        self.analyze_time_patterns()
        self.analyze_alert_quality()
        self.generate_insights()
        
        print(f"\n" + "="*50)
        print("Analysis completed successfully!")
        

def main():
    """Main function to run the analysis."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_folder = os.path.join(script_dir, 'momentum_data')
    
    if not os.path.exists(data_folder):
        print(f"Error: momentum_data folder not found at {data_folder}")
        sys.exit(1)
    
    analyzer = TelegramAlertAnalyzer(data_folder)
    analyzer.run_analysis()

if __name__ == "__main__":
    main()