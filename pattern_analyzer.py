#!/usr/bin/env python3
"""
Pattern Analyzer
Analyzes successful vs failed alerts to identify winning patterns.
"""

import json
import statistics
from collections import defaultdict, Counter
from pathlib import Path
import argparse

class PatternAnalyzer:
    def __init__(self, results_file="momentum_data/validation_results.json"):
        self.results_file = Path(results_file)
        self.load_results()
    
    def load_results(self):
        """Load validation results"""
        with open(self.results_file, 'r') as f:
            data = json.load(f)
        
        self.summary = data['summary']
        self.all_results = data['results']
        
        # Separate successful and failed tickers
        self.successful_tickers = data['successful_tickers']
        self.failed_tickers = data['failed_tickers']
        
        self.successful_data = {ticker: self.all_results[ticker] for ticker in self.successful_tickers}
        self.failed_data = {ticker: self.all_results[ticker] for ticker in self.failed_tickers}
        
        print(f"Loaded {len(self.successful_data)} successful and {len(self.failed_data)} failed tickers")
    
    def analyze_price_ranges(self):
        """Analyze price ranges of successful vs failed alerts"""
        successful_prices = [data['alert_price'] for data in self.successful_data.values()]
        failed_prices = [data['alert_price'] for data in self.failed_data.values()]
        
        # Define price buckets
        buckets = [
            (0, 1),      # Under $1
            (1, 2),      # $1-2
            (2, 5),      # $2-5
            (5, 10),     # $5-10
            (10, 20),    # $10-20
            (20, float('inf'))  # Over $20
        ]
        
        successful_buckets = defaultdict(int)
        failed_buckets = defaultdict(int)
        
        for price in successful_prices:
            for i, (low, high) in enumerate(buckets):
                if low <= price < high:
                    successful_buckets[f"${low}-{high if high != float('inf') else '20+'}"] += 1
                    break
        
        for price in failed_prices:
            for i, (low, high) in enumerate(buckets):
                if low <= price < high:
                    failed_buckets[f"${low}-{high if high != float('inf') else '20+'}"] += 1
                    break
        
        return {
            'successful_stats': {
                'mean': statistics.mean(successful_prices),
                'median': statistics.median(successful_prices),
                'min': min(successful_prices),
                'max': max(successful_prices),
                'buckets': dict(successful_buckets)
            },
            'failed_stats': {
                'mean': statistics.mean(failed_prices),
                'median': statistics.median(failed_prices),
                'min': min(failed_prices),
                'max': max(failed_prices),
                'buckets': dict(failed_buckets)
            }
        }
    
    def analyze_sectors(self):
        """Analyze sector distribution"""
        successful_sectors = Counter()
        failed_sectors = Counter()
        
        for data in self.successful_data.values():
            sector = data['alert_data'].get('sector', 'Unknown')
            successful_sectors[sector] += 1
        
        for data in self.failed_data.values():
            sector = data['alert_data'].get('sector', 'Unknown')
            failed_sectors[sector] += 1
        
        # Calculate success rates by sector
        sector_success_rates = {}
        all_sectors = set(successful_sectors.keys()) | set(failed_sectors.keys())
        
        for sector in all_sectors:
            success_count = successful_sectors.get(sector, 0)
            total_count = success_count + failed_sectors.get(sector, 0)
            success_rate = (success_count / total_count * 100) if total_count > 0 else 0
            sector_success_rates[sector] = {
                'success_count': success_count,
                'total_count': total_count,
                'success_rate': success_rate
            }
        
        return sector_success_rates
    
    def analyze_initial_change_patterns(self):
        """Analyze initial change percentage patterns"""
        successful_changes = [data['change_pct'] for data in self.successful_data.values()]
        failed_changes = [data['change_pct'] for data in self.failed_data.values()]
        
        # Define change buckets
        change_buckets = [
            (0, 25),     # 0-25%
            (25, 50),    # 25-50%
            (50, 100),   # 50-100%
            (100, 200),  # 100-200%
            (200, float('inf'))  # 200%+
        ]
        
        successful_change_buckets = defaultdict(int)
        failed_change_buckets = defaultdict(int)
        
        for change in successful_changes:
            for i, (low, high) in enumerate(change_buckets):
                if low <= change < high:
                    successful_change_buckets[f"{low}-{high if high != float('inf') else '200+'}%"] += 1
                    break
        
        for change in failed_changes:
            for i, (low, high) in enumerate(change_buckets):
                if low <= change < high:
                    failed_change_buckets[f"{low}-{high if high != float('inf') else '200+'}%"] += 1
                    break
        
        return {
            'successful_stats': {
                'mean': statistics.mean(successful_changes),
                'median': statistics.median(successful_changes),
                'min': min(successful_changes),
                'max': max(successful_changes),
                'buckets': dict(successful_change_buckets)
            },
            'failed_stats': {
                'mean': statistics.mean(failed_changes),
                'median': statistics.median(failed_changes),
                'min': min(failed_changes),
                'max': max(failed_changes),
                'buckets': dict(failed_change_buckets)
            }
        }
    
    def analyze_relative_volume_patterns(self):
        """Analyze relative volume patterns"""
        successful_volumes = []
        failed_volumes = []
        
        for data in self.successful_data.values():
            rel_vol = data['alert_data'].get('relative_volume')
            if rel_vol and rel_vol > 0:
                successful_volumes.append(rel_vol)
        
        for data in self.failed_data.values():
            rel_vol = data['alert_data'].get('relative_volume')
            if rel_vol and rel_vol > 0:
                failed_volumes.append(rel_vol)
        
        if not successful_volumes or not failed_volumes:
            return {'error': 'Insufficient volume data'}
        
        # Define volume buckets
        volume_buckets = [
            (0, 5),      # 0-5x
            (5, 20),     # 5-20x
            (20, 100),   # 20-100x
            (100, 500),  # 100-500x
            (500, float('inf'))  # 500x+
        ]
        
        successful_vol_buckets = defaultdict(int)
        failed_vol_buckets = defaultdict(int)
        
        for vol in successful_volumes:
            for i, (low, high) in enumerate(volume_buckets):
                if low <= vol < high:
                    successful_vol_buckets[f"{low}-{high if high != float('inf') else '500+'}x"] += 1
                    break
        
        for vol in failed_volumes:
            for i, (low, high) in enumerate(volume_buckets):
                if low <= vol < high:
                    failed_vol_buckets[f"{low}-{high if high != float('inf') else '500+'}x"] += 1
                    break
        
        return {
            'successful_stats': {
                'mean': statistics.mean(successful_volumes),
                'median': statistics.median(successful_volumes),
                'min': min(successful_volumes),
                'max': max(successful_volumes),
                'buckets': dict(successful_vol_buckets)
            },
            'failed_stats': {
                'mean': statistics.mean(failed_volumes),
                'median': statistics.median(failed_volumes),
                'min': min(failed_volumes),
                'max': max(failed_volumes),
                'buckets': dict(failed_vol_buckets)
            }
        }
    
    def analyze_alert_types(self):
        """Analyze which alert types are most successful"""
        successful_types = Counter()
        failed_types = Counter()
        
        for data in self.successful_data.values():
            alert_type = data['alert_type']
            successful_types[alert_type] += 1
        
        for data in self.failed_data.values():
            alert_type = data['alert_type']
            failed_types[alert_type] += 1
        
        # Calculate success rates by alert type
        type_success_rates = {}
        all_types = set(successful_types.keys()) | set(failed_types.keys())
        
        for alert_type in all_types:
            success_count = successful_types.get(alert_type, 0)
            total_count = success_count + failed_types.get(alert_type, 0)
            success_rate = (success_count / total_count * 100) if total_count > 0 else 0
            type_success_rates[alert_type] = {
                'success_count': success_count,
                'total_count': total_count,
                'success_rate': success_rate
            }
        
        return type_success_rates
    
    def find_high_performers(self, top_n=10):
        """Find the highest performing successful tickers"""
        performers = []
        for ticker, data in self.successful_data.items():
            performers.append({
                'ticker': ticker,
                'max_gain': data['max_gain'],
                'alert_price': data['alert_price'],
                'change_pct': data['change_pct'],
                'sector': data['alert_data'].get('sector', 'Unknown'),
                'relative_volume': data['alert_data'].get('relative_volume', 0),
                'alert_type': data['alert_type']
            })
        
        # Sort by max gain
        performers.sort(key=lambda x: x['max_gain'], reverse=True)
        return performers[:top_n]
    
    def calculate_success_rate_by_criteria(self):
        """Calculate success rates by various criteria combinations"""
        results = {}
        
        # Success rate by price range and change percentage
        price_change_matrix = defaultdict(lambda: {'success': 0, 'total': 0})
        
        for ticker, data in self.all_results.items():
            price = data['alert_price']
            change = data['change_pct']
            success = data['success']
            
            # Categorize price
            if price < 1:
                price_cat = "Under $1"
            elif price < 5:
                price_cat = "$1-5"
            elif price < 10:
                price_cat = "$5-10"
            else:
                price_cat = "Over $10"
            
            # Categorize change
            if change < 50:
                change_cat = "Under 50%"
            elif change < 100:
                change_cat = "50-100%"
            else:
                change_cat = "Over 100%"
            
            key = f"{price_cat} + {change_cat}"
            price_change_matrix[key]['total'] += 1
            if success:
                price_change_matrix[key]['success'] += 1
        
        # Calculate success rates
        for key, data in price_change_matrix.items():
            results[key] = {
                'success_count': data['success'],
                'total_count': data['total'],
                'success_rate': (data['success'] / data['total'] * 100) if data['total'] > 0 else 0
            }
        
        return results
    
    def generate_report(self):
        """Generate comprehensive pattern analysis report"""
        print("=" * 80)
        print("WINNING PATTERN ANALYSIS REPORT")
        print("=" * 80)
        
        # Price analysis
        print("\n📊 PRICE RANGE ANALYSIS")
        print("-" * 50)
        price_analysis = self.analyze_price_ranges()
        
        print(f"Successful Alerts - Average Price: ${price_analysis['successful_stats']['mean']:.2f}")
        print(f"Failed Alerts - Average Price: ${price_analysis['failed_stats']['mean']:.2f}")
        print(f"Successful Alerts - Median Price: ${price_analysis['successful_stats']['median']:.2f}")
        print(f"Failed Alerts - Median Price: ${price_analysis['failed_stats']['median']:.2f}")
        
        print("\nPrice Range Distribution:")
        for price_range in price_analysis['successful_stats']['buckets']:
            success_count = price_analysis['successful_stats']['buckets'][price_range]
            fail_count = price_analysis['failed_stats']['buckets'].get(price_range, 0)
            total = success_count + fail_count
            success_rate = (success_count / total * 100) if total > 0 else 0
            print(f"  {price_range:10} | Success: {success_count:3d} | Total: {total:3d} | Rate: {success_rate:5.1f}%")
        
        # Sector analysis
        print("\n🏭 SECTOR ANALYSIS")
        print("-" * 50)
        sector_analysis = self.analyze_sectors()
        
        # Sort by success rate
        sorted_sectors = sorted(sector_analysis.items(), key=lambda x: x[1]['success_rate'], reverse=True)
        
        for sector, data in sorted_sectors:
            if data['total_count'] >= 5:  # Only show sectors with 5+ alerts
                print(f"{sector:20} | Success: {data['success_count']:2d}/{data['total_count']:2d} | Rate: {data['success_rate']:5.1f}%")
        
        # Initial change analysis
        print("\n📈 INITIAL CHANGE PERCENTAGE ANALYSIS")
        print("-" * 50)
        change_analysis = self.analyze_initial_change_patterns()
        
        print(f"Successful Alerts - Average Change: {change_analysis['successful_stats']['mean']:.1f}%")
        print(f"Failed Alerts - Average Change: {change_analysis['failed_stats']['mean']:.1f}%")
        
        print("\nChange Range Distribution:")
        for change_range in change_analysis['successful_stats']['buckets']:
            success_count = change_analysis['successful_stats']['buckets'][change_range]
            fail_count = change_analysis['failed_stats']['buckets'].get(change_range, 0)
            total = success_count + fail_count
            success_rate = (success_count / total * 100) if total > 0 else 0
            print(f"  {change_range:10} | Success: {success_count:3d} | Total: {total:3d} | Rate: {success_rate:5.1f}%")
        
        # Volume analysis
        print("\n📊 RELATIVE VOLUME ANALYSIS")
        print("-" * 50)
        volume_analysis = self.analyze_relative_volume_patterns()
        
        if 'error' not in volume_analysis:
            print(f"Successful Alerts - Average Rel. Volume: {volume_analysis['successful_stats']['mean']:.1f}x")
            print(f"Failed Alerts - Average Rel. Volume: {volume_analysis['failed_stats']['mean']:.1f}x")
            
            print("\nVolume Range Distribution:")
            for vol_range in volume_analysis['successful_stats']['buckets']:
                success_count = volume_analysis['successful_stats']['buckets'][vol_range]
                fail_count = volume_analysis['failed_stats']['buckets'].get(vol_range, 0)
                total = success_count + fail_count
                success_rate = (success_count / total * 100) if total > 0 else 0
                print(f"  {vol_range:10} | Success: {success_count:3d} | Total: {total:3d} | Rate: {success_rate:5.1f}%")
        
        # Alert type analysis
        print("\n🚨 ALERT TYPE ANALYSIS")
        print("-" * 50)
        type_analysis = self.analyze_alert_types()
        
        for alert_type, data in sorted(type_analysis.items(), key=lambda x: x[1]['success_rate'], reverse=True):
            print(f"{alert_type:20} | Success: {data['success_count']:2d}/{data['total_count']:3d} | Rate: {data['success_rate']:5.1f}%")
        
        # Combined criteria analysis
        print("\n🎯 COMBINED CRITERIA ANALYSIS")
        print("-" * 50)
        combined_analysis = self.calculate_success_rate_by_criteria()
        
        for criteria, data in sorted(combined_analysis.items(), key=lambda x: x[1]['success_rate'], reverse=True):
            if data['total_count'] >= 10:  # Only show combinations with 10+ occurrences
                print(f"{criteria:25} | Success: {data['success_count']:2d}/{data['total_count']:3d} | Rate: {data['success_rate']:5.1f}%")
        
        # Top performers
        print("\n🏆 TOP 10 PERFORMERS")
        print("-" * 50)
        top_performers = self.find_high_performers(10)
        
        for i, performer in enumerate(top_performers, 1):
            print(f"{i:2d}. {performer['ticker']:6} | Gain: {performer['max_gain']:6.1f}% | "
                  f"Price: ${performer['alert_price']:5.2f} | Change: {performer['change_pct']:5.1f}% | "
                  f"Sector: {performer['sector']}")
        
        # Key insights
        print("\n🔍 KEY INSIGHTS & RECOMMENDATIONS")
        print("-" * 50)
        
        # Find best patterns
        best_sectors = [sector for sector, data in sorted_sectors if data['success_rate'] > 15 and data['total_count'] >= 5]
        
        # Price insights
        under_1_success = price_analysis['successful_stats']['buckets'].get('$0-1', 0)
        under_1_total = under_1_success + price_analysis['failed_stats']['buckets'].get('$0-1', 0)
        under_1_rate = (under_1_success / under_1_total * 100) if under_1_total > 0 else 0
        
        over_100_change_success = change_analysis['successful_stats']['buckets'].get('100-200+%', 0)
        over_100_change_total = over_100_change_success + change_analysis['failed_stats']['buckets'].get('100-200+%', 0)
        over_100_rate = (over_100_change_success / over_100_change_total * 100) if over_100_change_total > 0 else 0
        
        print(f"1. Stocks under $1 have {under_1_rate:.1f}% success rate")
        print(f"2. Stocks with 100%+ initial change have {over_100_rate:.1f}% success rate")
        
        if best_sectors:
            print(f"3. Best performing sectors: {', '.join(best_sectors[:3])}")
        
        print(f"4. Average successful alert price: ${price_analysis['successful_stats']['mean']:.2f}")
        print(f"5. Average successful initial change: {change_analysis['successful_stats']['mean']:.1f}%")
        
        if 'error' not in volume_analysis:
            print(f"6. Average successful relative volume: {volume_analysis['successful_stats']['mean']:.1f}x")
        
        print("\n" + "=" * 80)

def main():
    parser = argparse.ArgumentParser(description='Analyze patterns in successful vs failed alerts')
    parser.add_argument('--results-file', default='momentum_data/validation_results.json',
                        help='Path to validation results JSON file')
    
    args = parser.parse_args()
    
    analyzer = PatternAnalyzer(args.results_file)
    analyzer.generate_report()

if __name__ == "__main__":
    main()