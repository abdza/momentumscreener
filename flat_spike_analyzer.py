#!/usr/bin/env python3
"""
Flat-to-Spike Pattern Analyzer
Analyzes whether sudden spikes after flat periods are more successful than other patterns.
"""

import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
import statistics

class FlatSpikeAnalyzer:
    def __init__(self, results_file="momentum_data/validation_results.json"):
        self.results_file = Path(results_file)
        self.load_results()
        
    def load_results(self):
        """Load validation results"""
        with open(self.results_file, 'r') as f:
            data = json.load(f)
        
        self.all_results = data['results']
        self.successful_tickers = data['successful_tickers']
        self.failed_tickers = data['failed_tickers']
        
        print(f"Loaded {len(self.successful_tickers)} successful and {len(self.failed_tickers)} failed tickers")
    
    def analyze_premarket_vs_intraday_patterns(self):
        """Analyze if premarket gap vs intraday spike patterns differ in success"""
        premarket_patterns = defaultdict(list)
        intraday_patterns = defaultdict(list)
        
        for ticker, data in self.all_results.items():
            alert_type = data['alert_type']
            success = data['success']
            change_pct = data['change_pct']
            
            # Categorize based on alert type and premarket presence
            alert_data = data.get('alert_data', {})
            premarket_change = alert_data.get('premarket_change', 0)
            
            if alert_type in ['premarket_price', 'premarket_volume']:
                # This had premarket activity
                if premarket_change > 0:
                    category = "premarket_gap_up"
                else:
                    category = "premarket_other"
                premarket_patterns[category].append({
                    'ticker': ticker,
                    'success': success,
                    'change_pct': change_pct,
                    'premarket_change': premarket_change
                })
            else:
                # This is likely an intraday spike (price_spike type)
                # Assume sudden spike if no premarket change mentioned
                if premarket_change == 0 or premarket_change is None:
                    category = "sudden_intraday_spike"
                else:
                    category = "intraday_after_premarket"
                
                intraday_patterns[category].append({
                    'ticker': ticker,
                    'success': success,
                    'change_pct': change_pct,
                    'premarket_change': premarket_change
                })
        
        return premarket_patterns, intraday_patterns
    
    def analyze_timing_patterns(self):
        """Analyze timing of successful alerts to detect flat-to-spike patterns"""
        timing_analysis = defaultdict(list)
        
        for ticker, data in self.all_results.items():
            # Parse timestamp to get time of day
            try:
                timestamp_str = data['first_seen']
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                hour = timestamp.hour
                minute = timestamp.minute
                
                # Categorize by time periods
                if 4 <= hour < 9:  # Premarket hours (4 AM - 9 AM EST)
                    time_category = "premarket"
                elif 9 <= hour < 10:  # Market open first hour
                    time_category = "market_open"
                elif 10 <= hour < 15:  # Regular trading hours
                    time_category = "regular_hours"
                elif 15 <= hour < 16:  # Market close hour
                    time_category = "market_close"
                else:  # After hours
                    time_category = "after_hours"
                
                timing_analysis[time_category].append({
                    'ticker': ticker,
                    'success': data['success'],
                    'change_pct': data['change_pct'],
                    'hour': hour,
                    'minute': minute,
                    'alert_type': data['alert_type']
                })
                
            except Exception as e:
                continue
        
        return timing_analysis
    
    def analyze_spike_magnitude_patterns(self):
        """Analyze if smaller sudden spikes are more successful than large premarket gaps"""
        
        patterns = {
            'small_sudden_spikes': [],      # 25-75% sudden spikes
            'medium_sudden_spikes': [],     # 75-150% sudden spikes  
            'large_sudden_spikes': [],      # 150%+ sudden spikes
            'small_premarket_gaps': [],     # 25-75% premarket gaps
            'medium_premarket_gaps': [],    # 75-150% premarket gaps
            'large_premarket_gaps': []      # 150%+ premarket gaps
        }
        
        for ticker, data in self.all_results.items():
            change_pct = data['change_pct']
            alert_type = data['alert_type']
            success = data['success']
            alert_data = data.get('alert_data', {})
            premarket_change = alert_data.get('premarket_change', 0)
            
            entry = {
                'ticker': ticker,
                'success': success,
                'change_pct': change_pct,
                'max_gain': data.get('max_gain', 0)
            }
            
            # Determine if this is a sudden spike or premarket gap
            is_premarket = alert_type in ['premarket_price', 'premarket_volume']
            
            # Categorize by magnitude and type
            if 25 <= change_pct < 75:
                if is_premarket:
                    patterns['small_premarket_gaps'].append(entry)
                else:
                    patterns['small_sudden_spikes'].append(entry)
            elif 75 <= change_pct < 150:
                if is_premarket:
                    patterns['medium_premarket_gaps'].append(entry)
                else:
                    patterns['medium_sudden_spikes'].append(entry)
            elif change_pct >= 150:
                if is_premarket:
                    patterns['large_premarket_gaps'].append(entry)
                else:
                    patterns['large_sudden_spikes'].append(entry)
        
        return patterns
    
    def calculate_success_metrics(self, data_list):
        """Calculate success rate and other metrics for a list of alerts"""
        if not data_list:
            return {'count': 0, 'success_rate': 0, 'avg_change': 0, 'avg_max_gain': 0}
        
        successful = [item for item in data_list if item['success']]
        success_rate = len(successful) / len(data_list) * 100
        
        avg_change = statistics.mean([item['change_pct'] for item in data_list])
        successful_gains = [item.get('max_gain', 0) for item in successful if item.get('max_gain', 0) > 0]
        avg_max_gain = statistics.mean(successful_gains) if successful_gains else 0
        
        return {
            'count': len(data_list),
            'success_count': len(successful),
            'success_rate': success_rate,
            'avg_change': avg_change,
            'avg_max_gain': avg_max_gain,
            'successful_tickers': [item['ticker'] for item in successful]
        }
    
    def generate_comprehensive_report(self):
        """Generate comprehensive flat-to-spike analysis report"""
        print("=" * 80)
        print("FLAT-TO-SPIKE PATTERN ANALYSIS")
        print("=" * 80)
        
        # 1. Premarket vs Intraday Analysis
        print("\n📊 PREMARKET GAP vs INTRADAY SPIKE ANALYSIS")
        print("-" * 60)
        
        premarket_patterns, intraday_patterns = self.analyze_premarket_vs_intraday_patterns()
        
        for category, data_list in premarket_patterns.items():
            metrics = self.calculate_success_metrics(data_list)
            print(f"{category.replace('_', ' ').title():25} | "
                  f"Count: {metrics['count']:3d} | "
                  f"Success: {metrics['success_rate']:5.1f}% | "
                  f"Avg Change: {metrics['avg_change']:5.1f}%")
        
        for category, data_list in intraday_patterns.items():
            metrics = self.calculate_success_metrics(data_list)
            print(f"{category.replace('_', ' ').title():25} | "
                  f"Count: {metrics['count']:3d} | "
                  f"Success: {metrics['success_rate']:5.1f}% | "
                  f"Avg Change: {metrics['avg_change']:5.1f}%")
        
        # 2. Timing Analysis
        print("\n⏰ TIMING PATTERN ANALYSIS")
        print("-" * 60)
        
        timing_analysis = self.analyze_timing_patterns()
        
        for time_period, data_list in timing_analysis.items():
            metrics = self.calculate_success_metrics(data_list)
            print(f"{time_period.replace('_', ' ').title():20} | "
                  f"Count: {metrics['count']:3d} | "
                  f"Success: {metrics['success_rate']:5.1f}% | "
                  f"Avg Change: {metrics['avg_change']:5.1f}%")
        
        # 3. Spike Magnitude Analysis
        print("\n📈 SPIKE MAGNITUDE vs TYPE ANALYSIS")
        print("-" * 60)
        
        magnitude_patterns = self.analyze_spike_magnitude_patterns()
        
        # Compare similar magnitude spikes vs gaps
        comparisons = [
            ('small_sudden_spikes', 'small_premarket_gaps', '25-75% Range'),
            ('medium_sudden_spikes', 'medium_premarket_gaps', '75-150% Range'),
            ('large_sudden_spikes', 'large_premarket_gaps', '150%+ Range')
        ]
        
        for spike_key, gap_key, range_desc in comparisons:
            spike_metrics = self.calculate_success_metrics(magnitude_patterns[spike_key])
            gap_metrics = self.calculate_success_metrics(magnitude_patterns[gap_key])
            
            print(f"\n{range_desc}:")
            print(f"  Sudden Spikes      | Count: {spike_metrics['count']:3d} | Success: {spike_metrics['success_rate']:5.1f}%")
            print(f"  Premarket Gaps     | Count: {gap_metrics['count']:3d} | Success: {gap_metrics['success_rate']:5.1f}%")
            
            if spike_metrics['count'] > 0 and gap_metrics['count'] > 0:
                advantage = spike_metrics['success_rate'] - gap_metrics['success_rate']
                winner = "Sudden Spikes" if advantage > 0 else "Premarket Gaps"
                print(f"  → {winner} advantage: {abs(advantage):4.1f} percentage points")
        
        # 4. Key Insights
        print("\n🔍 KEY INSIGHTS")
        print("-" * 60)
        
        # Find the best performing pattern
        all_patterns = {}
        for category, data_list in {**premarket_patterns, **intraday_patterns}.items():
            if len(data_list) >= 10:  # Only consider patterns with sufficient data
                metrics = self.calculate_success_metrics(data_list)
                all_patterns[category] = metrics
        
        best_pattern = max(all_patterns.items(), key=lambda x: x[1]['success_rate'])
        
        print(f"1. Best performing pattern: {best_pattern[0].replace('_', ' ').title()}")
        print(f"   Success rate: {best_pattern[1]['success_rate']:.1f}% ({best_pattern[1]['success_count']}/{best_pattern[1]['count']})")
        
        # Compare sudden spikes vs premarket gaps overall
        sudden_spikes = magnitude_patterns['small_sudden_spikes'] + magnitude_patterns['medium_sudden_spikes'] + magnitude_patterns['large_sudden_spikes']
        premarket_gaps = magnitude_patterns['small_premarket_gaps'] + magnitude_patterns['medium_premarket_gaps'] + magnitude_patterns['large_premarket_gaps']
        
        sudden_metrics = self.calculate_success_metrics(sudden_spikes)
        premarket_metrics = self.calculate_success_metrics(premarket_gaps)
        
        print(f"\n2. Overall Pattern Comparison:")
        print(f"   Sudden Intraday Spikes: {sudden_metrics['success_rate']:.1f}% success ({sudden_metrics['success_count']}/{sudden_metrics['count']})")
        print(f"   Premarket Gaps: {premarket_metrics['success_rate']:.1f}% success ({premarket_metrics['success_count']}/{premarket_metrics['count']})")
        
        if sudden_metrics['success_rate'] > premarket_metrics['success_rate']:
            advantage = sudden_metrics['success_rate'] - premarket_metrics['success_rate']
            print(f"   ✅ YOUR HYPOTHESIS IS CORRECT! Sudden spikes are {advantage:.1f}pp better!")
        else:
            advantage = premarket_metrics['success_rate'] - sudden_metrics['success_rate']
            print(f"   ❌ Premarket gaps actually perform {advantage:.1f}pp better")
        
        # 3. Sample successful sudden spikes
        if sudden_metrics['successful_tickers']:
            print(f"\n3. Sample successful sudden spike tickers:")
            sample_tickers = sudden_metrics['successful_tickers'][:5]
            for ticker in sample_tickers:
                ticker_data = self.all_results[ticker]
                print(f"   {ticker}: {ticker_data['change_pct']:.1f}% initial → {ticker_data.get('max_gain', 0):.1f}% max gain")
        
        print("\n" + "=" * 80)

def main():
    analyzer = FlatSpikeAnalyzer()
    analyzer.generate_comprehensive_report()

if __name__ == "__main__":
    main()