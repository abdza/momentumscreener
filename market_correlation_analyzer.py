#!/usr/bin/env python3
"""
Market Correlation Analyzer
Analyzes correlation between screener performance and market indices (S&P 500, Gold, Oil)
"""

import json
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

try:
    import matplotlib.pyplot as plt
    import seaborn as sns
    PLOTTING_AVAILABLE = True
except ImportError:
    PLOTTING_AVAILABLE = False
    print("Note: matplotlib/seaborn not available. Skipping visualizations.")

class MarketCorrelationAnalyzer:
    def __init__(self):
        self.alerts = []
        self.market_data = {}
        self.daily_performance = defaultdict(lambda: {
            'alert_count': 0,
            'winners': 0,  # 30%+ gain within 5 days
            'avg_gain': [],
            'flat_to_spike_count': 0,
            'high_momentum_count': 0
        })

    def load_alerts(self):
        """Load alerts from telegram_alerts_sent.jsonl"""
        print("Loading alert data...")

        try:
            with open('momentum_data/telegram_alerts_sent.jsonl', 'r') as f:
                for line in f:
                    if line.strip():
                        alert = json.loads(line)
                        self.alerts.append(alert)

            print(f"Loaded {len(self.alerts)} alerts")
            return True
        except Exception as e:
            print(f"Error loading alerts: {e}")
            return False

    def get_price_performance(self, ticker, alert_date, alert_price):
        """Get the price performance after an alert"""
        try:
            # Get data for 5 days after alert
            end_date = alert_date + timedelta(days=5)
            data = yf.download(ticker, start=alert_date, end=end_date,
                             progress=False, interval='1d')

            if data.empty:
                return None

            # Get high price in the 5 days after alert
            max_price = data['High'].max()
            max_gain_pct = ((max_price - alert_price) / alert_price) * 100

            return float(max_gain_pct)
        except Exception as e:
            return None

    def analyze_daily_performance(self):
        """Analyze daily screener performance"""
        print("\nAnalyzing daily screener performance...")
        print(f"Total alerts to process: {len(self.alerts)}")

        # Process unique tickers only
        unique_tickers = {}
        for alert in self.alerts:
            ticker = alert['ticker']
            if ticker not in unique_tickers:
                unique_tickers[ticker] = alert

        print(f"Unique tickers: {len(unique_tickers)}")

        processed = 0
        for ticker, alert in unique_tickers.items():
            if processed % 50 == 0:
                print(f"  Processed {processed}/{len(unique_tickers)} unique tickers...")

            alert_time = datetime.fromisoformat(alert['timestamp'].replace('Z', '+00:00'))
            alert_date = alert_time.date()
            date_str = alert_date.strftime('%Y-%m-%d')

            # Count all alerts for this ticker (could be multiple)
            ticker_alerts = [a for a in self.alerts if a['ticker'] == ticker]

            self.daily_performance[date_str]['alert_count'] += len(ticker_alerts)

            # Check for flat-to-spike pattern in any alert
            for a in ticker_alerts:
                if 'flat_to_spike_detected' in a.get('alert_types', []):
                    self.daily_performance[date_str]['flat_to_spike_count'] += 1
                    break  # Count once per ticker

            # Calculate performance for this ticker
            alert_price = alert['alert_price']
            gain = self.get_price_performance(ticker, alert_date, alert_price)

            if gain is not None:
                self.daily_performance[date_str]['avg_gain'].append(gain)

                if gain >= 30:
                    self.daily_performance[date_str]['winners'] += 1

                if gain >= 15:
                    self.daily_performance[date_str]['high_momentum_count'] += 1

            processed += 1

        print(f"  Completed: {processed}/{len(unique_tickers)} unique tickers")
        print(f"Analyzed {len(self.daily_performance)} trading days")

    def fetch_market_data(self):
        """Fetch S&P 500, Gold, and Oil data"""
        print("\nFetching market index data...")

        # Get date range from alerts
        dates = [datetime.fromisoformat(a['timestamp'].replace('Z', '+00:00')).date()
                for a in self.alerts]
        start_date = min(dates) - timedelta(days=5)
        end_date = max(dates) + timedelta(days=5)

        print(f"Date range: {start_date} to {end_date}")

        # Fetch data for each index
        indices = {
            'SPY': 'S&P 500',  # S&P 500 ETF
            'GLD': 'Gold',      # Gold ETF
            'USO': 'Oil',       # Oil ETF
            '^VIX': 'VIX'       # Volatility Index
        }

        for ticker, name in indices.items():
            print(f"Fetching {name} ({ticker})...")
            try:
                data = yf.download(ticker, start=start_date, end=end_date,
                                 progress=False, interval='1d')

                if not data.empty:
                    # Calculate daily returns
                    data['Returns'] = data['Close'].pct_change() * 100
                    self.market_data[name] = data
                    print(f"  ✓ Got {len(data)} days of data")
                else:
                    print(f"  ✗ No data retrieved")
            except Exception as e:
                print(f"  ✗ Error: {e}")

    def calculate_correlations(self):
        """Calculate correlations between screener performance and market indices"""
        print("\nCalculating correlations...")

        # Prepare daily metrics
        dates = sorted(self.daily_performance.keys())
        print(f"Processing {len(dates)} dates for correlation analysis...")

        metrics = {
            'date': [],
            'alert_count': [],
            'win_rate': [],
            'avg_gain': [],
            'flat_to_spike_ratio': [],
            'high_momentum_ratio': []
        }

        for date_str in dates:
            perf = self.daily_performance[date_str]

            metrics['date'].append(date_str)
            metrics['alert_count'].append(perf['alert_count'])

            # Win rate (30%+ gains)
            total_with_data = len(perf['avg_gain'])
            win_rate = (perf['winners'] / total_with_data * 100) if total_with_data > 0 else 0
            metrics['win_rate'].append(win_rate)

            # Average gain
            avg_gain = np.mean(perf['avg_gain']) if perf['avg_gain'] else 0
            metrics['avg_gain'].append(avg_gain)

            # Flat to spike ratio
            fts_ratio = (perf['flat_to_spike_count'] / perf['alert_count'] * 100) if perf['alert_count'] > 0 else 0
            metrics['flat_to_spike_ratio'].append(fts_ratio)

            # High momentum ratio
            hm_ratio = (perf['high_momentum_count'] / total_with_data * 100) if total_with_data > 0 else 0
            metrics['high_momentum_ratio'].append(hm_ratio)

        # Create DataFrame
        df = pd.DataFrame(metrics)
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        print(f"Created DataFrame with {len(df)} rows")

        # Add market data
        print("Aligning market data with screener performance dates...")
        for name, market_df in self.market_data.items():
            print(f"  Processing {name}...")
            # Align dates
            aligned_returns = []
            for date in df.index:
                if date in market_df.index:
                    value = market_df.loc[date, 'Returns']
                    # Convert to scalar if it's a Series
                    if hasattr(value, 'iloc'):
                        value = float(value.iloc[0]) if len(value) > 0 else 0.0
                    aligned_returns.append(float(value) if pd.notna(value) else 0.0)
                else:
                    # Use previous trading day's return
                    prev_dates = market_df.index[market_df.index < date]
                    if len(prev_dates) > 0:
                        value = market_df.loc[prev_dates[-1], 'Returns']
                        if hasattr(value, 'iloc'):
                            value = float(value.iloc[0]) if len(value) > 0 else 0.0
                        aligned_returns.append(float(value) if pd.notna(value) else 0.0)
                    else:
                        aligned_returns.append(0.0)

            df[f'{name}_return'] = aligned_returns

        # Debug: Print DataFrame info
        print(f"\nDataFrame columns: {list(df.columns)}")
        print(f"DataFrame dtypes:\n{df.dtypes}")
        print(f"\nFirst few rows:\n{df.head()}")

        # Calculate correlations
        print("\n" + "="*80)
        print("CORRELATION ANALYSIS: Screener Performance vs Market Indices")
        print("="*80)

        market_cols = [col for col in df.columns if col.endswith('_return')]
        screener_metrics = ['alert_count', 'win_rate', 'avg_gain',
                          'flat_to_spike_ratio', 'high_momentum_ratio']

        correlation_results = []
        print(f"Calculating correlations for {len(screener_metrics)} metrics against {len(market_cols)} market indices...")

        for metric in screener_metrics:
            print(f"\n{metric.replace('_', ' ').title()}:")
            print("-" * 60)

            for market_col in market_cols:
                market_name = market_col.replace('_return', '')
                print(f"    Checking {metric} vs {market_name}...", end=" ")

                # Remove NaN and infinite values
                try:
                    valid_data = df[[metric, market_col]].copy()
                    # Convert to numeric if needed
                    valid_data[metric] = pd.to_numeric(valid_data[metric], errors='coerce')
                    valid_data[market_col] = pd.to_numeric(valid_data[market_col], errors='coerce')
                    # Now drop NaN and inf
                    valid_data = valid_data.replace([np.inf, -np.inf], np.nan).dropna()
                except Exception as e:
                    print(f"ERROR: {e}")
                    continue

                if len(valid_data) > 2:
                    try:
                        correlation = valid_data[metric].corr(valid_data[market_col])

                        correlation_results.append({
                            'screener_metric': metric,
                            'market_index': market_name,
                            'correlation': correlation,
                            'sample_size': len(valid_data)
                        })

                        # Interpret correlation strength
                        if abs(correlation) > 0.7:
                            strength = "STRONG"
                        elif abs(correlation) > 0.4:
                            strength = "MODERATE"
                        elif abs(correlation) > 0.2:
                            strength = "WEAK"
                        else:
                            strength = "VERY WEAK"

                        direction = "positive" if correlation > 0 else "negative"

                        print(f"{correlation:+.3f} ({strength} {direction}, n={len(valid_data)})")
                    except Exception as e:
                        print(f"ERROR in correlation: {e}")
                else:
                    print(f"Insufficient data (n={len(valid_data)})")

        # Overall summary
        print("\n" + "="*80)
        print("KEY FINDINGS")
        print("="*80)

        # Find strongest correlations
        corr_df = pd.DataFrame(correlation_results)
        corr_df['abs_correlation'] = corr_df['correlation'].abs()
        strongest = corr_df.nlargest(5, 'abs_correlation')

        print("\nTop 5 Strongest Correlations:")
        for i, row in strongest.iterrows():
            direction = "positive" if row['correlation'] > 0 else "negative"
            print(f"  {i+1}. {row['screener_metric']:20s} vs {row['market_index']:10s}: "
                  f"{row['correlation']:+.3f} ({direction})")

        # Market environment analysis
        print("\n" + "="*80)
        print("MARKET ENVIRONMENT ANALYSIS")
        print("="*80)

        for name, market_df in self.market_data.items():
            avg_return = market_df['Returns'].mean()
            volatility = market_df['Returns'].std()
            trend = "bullish" if avg_return > 0 else "bearish"

            print(f"\n{name}:")
            print(f"  Average daily return: {avg_return:+.2f}%")
            print(f"  Volatility (std dev): {volatility:.2f}%")
            print(f"  Overall trend: {trend}")

        # Screener performance summary
        print("\n" + "="*80)
        print("SCREENER PERFORMANCE SUMMARY")
        print("="*80)

        print(f"\nTotal trading days analyzed: {len(df)}")
        print(f"Total alerts: {df['alert_count'].sum():.0f}")
        print(f"Average alerts per day: {df['alert_count'].mean():.1f}")
        print(f"Average win rate: {df['win_rate'].mean():.1f}%")
        print(f"Average gain per alert: {df['avg_gain'].mean():.1f}%")
        print(f"Average flat-to-spike ratio: {df['flat_to_spike_ratio'].mean():.1f}%")
        print(f"Average high momentum ratio: {df['high_momentum_ratio'].mean():.1f}%")

        # Save detailed results
        output_file = 'market_correlation_analysis.csv'
        df.to_csv(output_file)
        print(f"\nDetailed results saved to: {output_file}")

        return df, corr_df

    def create_visualization(self, df, corr_df):
        """Create visualization of correlations"""
        if not PLOTTING_AVAILABLE:
            print("\nSkipping visualizations (matplotlib/seaborn not available)")
            return

        print("\nCreating visualizations...")

        # Create correlation heatmap
        screener_metrics = ['alert_count', 'win_rate', 'avg_gain',
                          'flat_to_spike_ratio', 'high_momentum_ratio']
        market_cols = [col for col in df.columns if col.endswith('_return')]

        # Prepare correlation matrix
        corr_matrix = pd.DataFrame(index=screener_metrics,
                                  columns=[col.replace('_return', '') for col in market_cols])

        for metric in screener_metrics:
            for market_col in market_cols:
                market_name = market_col.replace('_return', '')
                valid_data = df[[metric, market_col]].copy()
                # Convert to numeric
                valid_data[metric] = pd.to_numeric(valid_data[metric], errors='coerce')
                valid_data[market_col] = pd.to_numeric(valid_data[market_col], errors='coerce')
                valid_data = valid_data.replace([np.inf, -np.inf], np.nan).dropna()

                if len(valid_data) > 2:
                    corr_matrix.loc[metric, market_name] = valid_data[metric].corr(valid_data[market_col])
                else:
                    corr_matrix.loc[metric, market_name] = np.nan

        corr_matrix = corr_matrix.astype(float)

        # Create figure
        plt.figure(figsize=(10, 8))
        sns.heatmap(corr_matrix, annot=True, cmap='RdYlGn', center=0,
                   vmin=-1, vmax=1, fmt='.3f', linewidths=1)
        plt.title('Screener Performance vs Market Indices Correlation', fontsize=14, fontweight='bold')
        plt.xlabel('Market Index', fontsize=12)
        plt.ylabel('Screener Metric', fontsize=12)
        plt.tight_layout()

        output_file = 'correlation_heatmap.png'
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        print(f"Heatmap saved to: {output_file}")

        # Create time series comparison
        fig, axes = plt.subplots(3, 1, figsize=(14, 10))

        # Plot 1: Alert count vs S&P 500
        ax1 = axes[0]
        ax1_twin = ax1.twinx()

        ax1.plot(df.index, df['alert_count'], color='blue', linewidth=2, label='Alert Count')
        ax1.set_ylabel('Alert Count', color='blue', fontsize=10)
        ax1.tick_params(axis='y', labelcolor='blue')

        if 'S&P 500_return' in df.columns:
            ax1_twin.plot(df.index, df['S&P 500_return'], color='red', alpha=0.7, label='S&P 500 Return')
            ax1_twin.set_ylabel('S&P 500 Daily Return (%)', color='red', fontsize=10)
            ax1_twin.tick_params(axis='y', labelcolor='red')
            ax1_twin.axhline(y=0, color='gray', linestyle='--', alpha=0.5)

        ax1.set_title('Alert Count vs S&P 500 Returns', fontsize=12, fontweight='bold')
        ax1.grid(True, alpha=0.3)

        # Plot 2: Win rate vs Gold
        ax2 = axes[1]
        ax2_twin = ax2.twinx()

        ax2.plot(df.index, df['win_rate'], color='green', linewidth=2, label='Win Rate')
        ax2.set_ylabel('Win Rate (%)', color='green', fontsize=10)
        ax2.tick_params(axis='y', labelcolor='green')

        if 'Gold_return' in df.columns:
            ax2_twin.plot(df.index, df['Gold_return'], color='orange', alpha=0.7, label='Gold Return')
            ax2_twin.set_ylabel('Gold Daily Return (%)', color='orange', fontsize=10)
            ax2_twin.tick_params(axis='y', labelcolor='orange')
            ax2_twin.axhline(y=0, color='gray', linestyle='--', alpha=0.5)

        ax2.set_title('Win Rate vs Gold Returns', fontsize=12, fontweight='bold')
        ax2.grid(True, alpha=0.3)

        # Plot 3: Average gain vs Oil
        ax3 = axes[2]
        ax3_twin = ax3.twinx()

        ax3.plot(df.index, df['avg_gain'], color='purple', linewidth=2, label='Avg Gain')
        ax3.set_ylabel('Average Gain (%)', color='purple', fontsize=10)
        ax3.tick_params(axis='y', labelcolor='purple')

        if 'Oil_return' in df.columns:
            ax3_twin.plot(df.index, df['Oil_return'], color='brown', alpha=0.7, label='Oil Return')
            ax3_twin.set_ylabel('Oil Daily Return (%)', color='brown', fontsize=10)
            ax3_twin.tick_params(axis='y', labelcolor='brown')
            ax3_twin.axhline(y=0, color='gray', linestyle='--', alpha=0.5)

        ax3.set_title('Average Gain vs Oil Returns', fontsize=12, fontweight='bold')
        ax3.set_xlabel('Date', fontsize=10)
        ax3.grid(True, alpha=0.3)

        plt.tight_layout()

        output_file = 'time_series_comparison.png'
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        print(f"Time series plot saved to: {output_file}")

    def run_analysis(self):
        """Run the complete correlation analysis"""
        print("Market Correlation Analysis")
        print("="*80)
        print(f"Analysis started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        if not self.load_alerts():
            return

        self.analyze_daily_performance()
        self.fetch_market_data()
        df, corr_df = self.calculate_correlations()

        try:
            self.create_visualization(df, corr_df)
        except Exception as e:
            print(f"\nNote: Visualization creation failed: {e}")
            print("Analysis results are still available in the CSV file.")

        print("\n" + "="*80)
        print("Analysis complete!")
        print("="*80)

def main():
    analyzer = MarketCorrelationAnalyzer()
    analyzer.run_analysis()

if __name__ == "__main__":
    main()
