#!/usr/bin/env python3
"""
Enhanced Alert Performance Analyzer
Advanced analysis of telegram alert data with focus on success patterns,
flat-to-spike detection, and performance optimization recommendations.
"""

import json
import os
import glob
from collections import defaultdict, Counter
from datetime import datetime, timedelta
import statistics
import sys

class EnhancedAlertAnalyzer:
    def __init__(self, data_folder):
        self.data_folder = data_folder
        self.start_date = "20250830"
        self.alerts_data = []
        self.success_patterns = {
            'flat_to_spike': [],
            'momentum_continuation': [],
            'premarket_follow_through': []
        }
        
    def load_alert_files(self):
        """Load all alert files from the specified date range."""
        print(f"Loading alert files from {self.start_date} onwards...")
        
        # Get files from both August 30th onwards and September
        patterns = [
            f"{self.data_folder}/alerts_{self.start_date}*.json",
            f"{self.data_folder}/alerts_202509*.json"
        ]
        
        files = []
        for pattern in patterns:
            files.extend(glob.glob(pattern))
        
        files.sort()
        print(f"Found {len(files)} alert files to analyze")
        
        loaded_count = 0
        for file_path in files:
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    self.alerts_data.append(data)
                    loaded_count += 1
            except Exception as e:
                print(f"Error loading {file_path}: {e}")
                
        print(f"Successfully loaded {loaded_count} alert files")
        
    def analyze_flat_to_spike_patterns(self):
        """Analyze flat-to-spike patterns and their characteristics."""
        print("\n=== FLAT-TO-SPIKE PATTERN ANALYSIS ===")
        
        flat_to_spike_alerts = []
        regular_spike_alerts = []
        
        for alert_data in self.alerts_data:
            for alert_type in ['volume_climbers', 'price_spikes']:
                alerts = alert_data.get(alert_type, [])
                for alert in alerts:
                    change_from_open = alert.get('change_from_open', 0)
                    if change_from_open > 15:  # Flat-to-spike threshold
                        flat_to_spike_alerts.append(alert)
                    elif change_from_open > 0:
                        regular_spike_alerts.append(alert)
        
        print(f"Flat-to-spike alerts: {len(flat_to_spike_alerts)}")
        print(f"Regular spike alerts: {len(regular_spike_alerts)}")
        
        if flat_to_spike_alerts:
            print("\nFlat-to-Spike Characteristics:")
            avg_change_from_open = statistics.mean([a.get('change_from_open', 0) for a in flat_to_spike_alerts])
            avg_rel_vol = statistics.mean([a.get('relative_volume', 0) for a in flat_to_spike_alerts if 'relative_volume' in a])
            avg_price_change = statistics.mean([a.get('change_pct', 0) for a in flat_to_spike_alerts])
            
            print(f"  Average change from open: {avg_change_from_open:.2f}%")
            print(f"  Average relative volume: {avg_rel_vol:.2f}x")
            print(f"  Average price change: {avg_price_change:.2f}%")
            
            # Top flat-to-spike performers
            sorted_fts = sorted(flat_to_spike_alerts, key=lambda x: x.get('change_from_open', 0), reverse=True)
            print(f"\nTop 10 Flat-to-Spike Performers:")
            print(f"{'Ticker':<8} {'Change from Open%':<18} {'Price Change%':<15} {'Rel Vol':<10} {'Sector'}")
            print("-" * 70)
            for alert in sorted_fts[:10]:
                ticker = alert.get('ticker', 'N/A')
                change_from_open = alert.get('change_from_open', 0)
                change_pct = alert.get('change_pct', 0)
                rel_vol = alert.get('relative_volume', 0)
                sector = alert.get('sector', 'Unknown')[:15]
                print(f"{ticker:<8} {change_from_open:<18.2f} {change_pct:<15.2f} {rel_vol:<10.2f} {sector}")
    
    def analyze_premarket_performance(self):
        """Analyze premarket alert performance and follow-through."""
        print("\n=== PREMARKET ALERT PERFORMANCE ===")
        
        premarket_alerts = {
            'volume': [],
            'price': []
        }
        
        for alert_data in self.alerts_data:
            premarket_alerts['volume'].extend(alert_data.get('premarket_volume_alerts', []))
            premarket_alerts['price'].extend(alert_data.get('premarket_price_alerts', []))
            
        total_premarket = len(premarket_alerts['volume']) + len(premarket_alerts['price'])
        print(f"Total premarket alerts: {total_premarket}")
        print(f"  Volume alerts: {len(premarket_alerts['volume'])} ({len(premarket_alerts['volume'])/total_premarket*100:.1f}%)")
        print(f"  Price alerts: {len(premarket_alerts['price'])} ({len(premarket_alerts['price'])/total_premarket*100:.1f}%)")
        
        if premarket_alerts['price']:
            print("\nPremarket Price Alert Analysis:")
            avg_change = statistics.mean([a.get('change_pct', 0) for a in premarket_alerts['price']])
            avg_rel_vol = statistics.mean([a.get('relative_volume', 0) for a in premarket_alerts['price'] if 'relative_volume' in a])
            
            print(f"  Average price change: {avg_change:.2f}%")
            print(f"  Average relative volume: {avg_rel_vol:.2f}x")
            
            # High momentum premarket alerts
            high_momentum = [a for a in premarket_alerts['price'] if a.get('change_pct', 0) > 15]
            print(f"  High momentum alerts (>15%): {len(high_momentum)} ({len(high_momentum)/len(premarket_alerts['price'])*100:.1f}%)")
    
    def analyze_sector_momentum_patterns(self):
        """Analyze momentum patterns by sector."""
        print("\n=== SECTOR MOMENTUM PATTERNS ===")
        
        sector_momentum = defaultdict(lambda: {
            'flat_to_spike_count': 0,
            'regular_alerts': 0,
            'avg_relative_volume': [],
            'avg_momentum_score': [],
            'top_performers': []
        })
        
        for alert_data in self.alerts_data:
            for alert_type in ['volume_climbers', 'price_spikes', 'premarket_price_alerts']:
                alerts = alert_data.get(alert_type, [])
                for alert in alerts:
                    sector = alert.get('sector', 'Unknown')
                    change_from_open = alert.get('change_from_open', 0)
                    
                    if change_from_open > 15:
                        sector_momentum[sector]['flat_to_spike_count'] += 1
                    else:
                        sector_momentum[sector]['regular_alerts'] += 1
                    
                    if 'relative_volume' in alert:
                        sector_momentum[sector]['avg_relative_volume'].append(alert['relative_volume'])
                    
                    # Calculate momentum score
                    momentum_score = (alert.get('change_pct', 0) * 0.4 + 
                                    alert.get('relative_volume', 0) * 0.3 + 
                                    alert.get('change_from_open', 0) * 0.3)
                    sector_momentum[sector]['avg_momentum_score'].append(momentum_score)
                    
                    # Track top performers
                    if momentum_score > 50:
                        sector_momentum[sector]['top_performers'].append({
                            'ticker': alert.get('ticker'),
                            'momentum_score': momentum_score,
                            'change_pct': alert.get('change_pct', 0)
                        })
        
        print(f"Sector Momentum Analysis:")
        print(f"{'Sector':<25} {'FTS Count':<10} {'Regular':<8} {'Avg RelVol':<12} {'Momentum Score':<15}")
        print("-" * 80)
        
        for sector, data in sorted(sector_momentum.items(), 
                                 key=lambda x: x[1]['flat_to_spike_count'], reverse=True)[:15]:
            if sector is None:
                sector = "Unknown"
            avg_rel_vol = statistics.mean(data['avg_relative_volume']) if data['avg_relative_volume'] else 0
            avg_momentum = statistics.mean(data['avg_momentum_score']) if data['avg_momentum_score'] else 0
            
            print(f"{sector:<25} {data['flat_to_spike_count']:<10} {data['regular_alerts']:<8} {avg_rel_vol:<12.2f} {avg_momentum:<15.2f}")
    
    def analyze_ticker_success_patterns(self):
        """Analyze individual ticker success patterns."""
        print("\n=== TICKER SUCCESS PATTERNS ===")
        
        ticker_performance = defaultdict(lambda: {
            'total_alerts': 0,
            'flat_to_spike_count': 0,
            'high_momentum_count': 0,
            'avg_change_pct': [],
            'avg_relative_volume': [],
            'best_performance': 0,
            'alert_types': set()
        })
        
        for alert_data in self.alerts_data:
            for alert_type in ['volume_climbers', 'volume_newcomers', 'price_spikes', 
                             'premarket_volume_alerts', 'premarket_price_alerts']:
                alerts = alert_data.get(alert_type, [])
                for alert in alerts:
                    ticker = alert.get('ticker')
                    if not ticker:
                        continue
                        
                    perf = ticker_performance[ticker]
                    perf['total_alerts'] += 1
                    perf['alert_types'].add(alert_type)
                    
                    change_from_open = alert.get('change_from_open', 0)
                    change_pct = alert.get('change_pct', 0)
                    
                    if change_from_open > 15:
                        perf['flat_to_spike_count'] += 1
                    
                    if change_pct > 15:
                        perf['high_momentum_count'] += 1
                    
                    perf['avg_change_pct'].append(change_pct)
                    if 'relative_volume' in alert:
                        perf['avg_relative_volume'].append(alert['relative_volume'])
                    
                    perf['best_performance'] = max(perf['best_performance'], change_pct)
        
        # Find tickers with consistent patterns
        consistent_performers = []
        for ticker, perf in ticker_performance.items():
            if perf['total_alerts'] >= 5:  # At least 5 alerts
                fts_ratio = perf['flat_to_spike_count'] / perf['total_alerts']
                high_momentum_ratio = perf['high_momentum_count'] / perf['total_alerts']
                avg_change = statistics.mean(perf['avg_change_pct']) if perf['avg_change_pct'] else 0
                
                if fts_ratio > 0.3 or high_momentum_ratio > 0.4:  # Good success pattern
                    consistent_performers.append({
                        'ticker': ticker,
                        'total_alerts': perf['total_alerts'],
                        'fts_ratio': fts_ratio,
                        'high_momentum_ratio': high_momentum_ratio,
                        'avg_change': avg_change,
                        'best_performance': perf['best_performance']
                    })
        
        consistent_performers.sort(key=lambda x: x['avg_change'], reverse=True)
        
        print(f"Top Consistent Performers (5+ alerts):")
        print(f"{'Ticker':<8} {'Alerts':<7} {'FTS Ratio':<10} {'HM Ratio':<10} {'Avg Change%':<12} {'Best %':<8}")
        print("-" * 65)
        
        for perf in consistent_performers[:15]:
            print(f"{perf['ticker']:<8} {perf['total_alerts']:<7} {perf['fts_ratio']:<10.2f} "
                  f"{perf['high_momentum_ratio']:<10.2f} {perf['avg_change']:<12.2f} {perf['best_performance']:<8.2f}")
    
    def generate_optimization_recommendations(self):
        """Generate specific recommendations for alert optimization."""
        print("\n" + "="*70)
        print("ADVANCED OPTIMIZATION RECOMMENDATIONS")
        print("="*70)
        
        # Calculate key metrics
        all_alerts = []
        flat_to_spike_alerts = []
        high_momentum_alerts = []
        
        for alert_data in self.alerts_data:
            for alert_type in ['volume_climbers', 'price_spikes', 'premarket_price_alerts']:
                alerts = alert_data.get(alert_type, [])
                for alert in alerts:
                    all_alerts.append(alert)
                    
                    change_from_open = alert.get('change_from_open', 0)
                    change_pct = alert.get('change_pct', 0)
                    
                    if change_from_open > 15:
                        flat_to_spike_alerts.append(alert)
                    
                    if change_pct > 15:
                        high_momentum_alerts.append(alert)
        
        total_alerts = len(all_alerts)
        fts_count = len(flat_to_spike_alerts)
        hm_count = len(high_momentum_alerts)
        
        print(f"\n1. SUCCESS PATTERN ANALYSIS:")
        print(f"   • Total analyzed alerts: {total_alerts}")
        print(f"   • Flat-to-spike patterns: {fts_count} ({fts_count/total_alerts*100:.1f}%)")
        print(f"   • High momentum alerts: {hm_count} ({hm_count/total_alerts*100:.1f}%)")
        
        if fts_count > 0:
            avg_fts_change = statistics.mean([a.get('change_pct', 0) for a in flat_to_spike_alerts])
            avg_fts_rel_vol = statistics.mean([a.get('relative_volume', 0) for a in flat_to_spike_alerts if 'relative_volume' in a])
            print(f"   • Avg FTS price change: {avg_fts_change:.2f}%")
            print(f"   • Avg FTS relative volume: {avg_fts_rel_vol:.2f}x")
        
        print(f"\n2. THRESHOLD OPTIMIZATION:")
        if all_alerts:
            rel_vols = [a.get('relative_volume', 0) for a in all_alerts if 'relative_volume' in a]
            price_changes = [a.get('change_pct', 0) for a in all_alerts]
            
            if rel_vols:
                p75_rel_vol = sorted(rel_vols)[int(len(rel_vols) * 0.75)]
                p90_rel_vol = sorted(rel_vols)[int(len(rel_vols) * 0.9)]
                print(f"   → 75th percentile relative volume: {p75_rel_vol:.2f}x")
                print(f"   → 90th percentile relative volume: {p90_rel_vol:.2f}x")
                print(f"   → RECOMMENDATION: Set high-quality threshold at {p75_rel_vol:.1f}x+")
            
            if price_changes:
                p75_price = sorted(price_changes)[int(len(price_changes) * 0.75)]
                p90_price = sorted(price_changes)[int(len(price_changes) * 0.9)]
                print(f"   → 75th percentile price change: {p75_price:.2f}%")
                print(f"   → 90th percentile price change: {p90_price:.2f}%")
                print(f"   → RECOMMENDATION: Set immediate alert threshold at {p90_price:.1f}%+")
        
        print(f"\n3. PATTERN-SPECIFIC RECOMMENDATIONS:")
        print(f"   → FLAT-TO-SPIKE DETECTION:")
        print(f"     • Current threshold: 15% change from open")
        if fts_count > 0:
            fts_changes = [a.get('change_from_open', 0) for a in flat_to_spike_alerts]
            min_fts_change = min(fts_changes)
            print(f"     • Minimum detected FTS: {min_fts_change:.2f}%")
            print(f"     • RECOMMENDATION: Consider lowering to {min_fts_change*0.8:.1f}% for earlier detection")
        
        print(f"\n   → MOMENTUM SCORING SYSTEM:")
        print(f"     • Implement composite scoring: (price_change * 0.4) + (rel_volume * 0.3) + (change_from_open * 0.3)")
        print(f"     • Priority tiers: High (>50), Medium (20-50), Low (<20)")
        
        print(f"\n4. ALERT FREQUENCY OPTIMIZATION:")
        print(f"   → Implement ticker cooldown periods:")
        print(f"     • High performers: 5-minute cooldown")
        print(f"     • Regular alerts: 10-minute cooldown")
        print(f"     • Poor performers: 20-minute cooldown")
        
        print(f"\n5. SECTOR-SPECIFIC TUNING:")
        print(f"   → Finance & Health Tech: Higher relative volume thresholds (excessive activity)")
        print(f"   → Technology Services: Lower price change thresholds (early momentum)")
        print(f"   → Utilities: Special handling for consistent performers")
        
    def run_enhanced_analysis(self):
        """Run the complete enhanced analysis."""
        print("Enhanced Telegram Alert Performance Analysis")
        print("="*60)
        print(f"Analysis Period: From {self.start_date} onwards")
        print(f"Current Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        self.load_alert_files()
        
        if not self.alerts_data:
            print("No alert data found for analysis.")
            return
            
        self.analyze_flat_to_spike_patterns()
        self.analyze_premarket_performance()
        self.analyze_sector_momentum_patterns()
        self.analyze_ticker_success_patterns()
        self.generate_optimization_recommendations()
        
        print(f"\n" + "="*60)
        print("Enhanced analysis completed successfully!")

def main():
    """Main function to run the enhanced analysis."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_folder = os.path.join(script_dir, 'momentum_data')
    
    if not os.path.exists(data_folder):
        print(f"Error: momentum_data folder not found at {data_folder}")
        sys.exit(1)
    
    analyzer = EnhancedAlertAnalyzer(data_folder)
    analyzer.run_enhanced_analysis()

if __name__ == "__main__":
    main()