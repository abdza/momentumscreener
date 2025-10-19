#!/usr/bin/env python3
"""
Flat EOD Spike Scanner
Scans tickers for days when the trading day was relatively flat on 5-minute scale
but had a price spike in the final hour/minutes of trading.
"""

import yfinance as yf
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from typing import List, Dict, Tuple
import argparse


class FlatEODSpikeScanner:
    def __init__(self,
                 flat_threshold_pct: float = 2.0,
                 eod_spike_threshold_pct: float = 5.0,
                 eod_window_minutes: int = 60):
        """
        Initialize scanner with pattern detection parameters.

        Args:
            flat_threshold_pct: Max intraday range % to consider "flat"
            eod_spike_threshold_pct: Min % increase in EOD window to be a "spike"
            eod_window_minutes: Number of minutes at end of day to check for spike
        """
        self.flat_threshold_pct = flat_threshold_pct
        self.eod_spike_threshold_pct = eod_spike_threshold_pct
        self.eod_window_minutes = eod_window_minutes

    def calculate_intraday_range(self, df: pd.DataFrame, exclude_eod_minutes: int) -> float:
        """
        Calculate the price range % for the day excluding EOD period.

        Args:
            df: DataFrame with 5-minute data
            exclude_eod_minutes: Minutes at end of day to exclude

        Returns:
            Range percentage
        """
        if len(df) == 0:
            return 0.0

        # Exclude the last N minutes
        bars_to_exclude = exclude_eod_minutes // 5
        if bars_to_exclude >= len(df):
            return 0.0

        df_body = df.iloc[:-bars_to_exclude] if bars_to_exclude > 0 else df

        if len(df_body) == 0:
            return 0.0

        high = df_body['High'].max()
        low = df_body['Low'].min()
        avg_price = (high + low) / 2

        if avg_price == 0:
            return 0.0

        range_pct = ((high - low) / avg_price) * 100
        return range_pct

    def calculate_eod_spike(self, df: pd.DataFrame, window_minutes: int) -> Tuple[float, float, float]:
        """
        Calculate the price movement in the EOD window.

        Args:
            df: DataFrame with 5-minute data
            window_minutes: Number of minutes at end of day to analyze

        Returns:
            Tuple of (spike_pct, eod_start_price, eod_end_price)
        """
        if len(df) == 0:
            return 0.0, 0.0, 0.0

        bars_in_window = window_minutes // 5
        if bars_in_window >= len(df):
            bars_in_window = len(df)

        eod_data = df.iloc[-bars_in_window:]

        if len(eod_data) == 0:
            return 0.0, 0.0, 0.0

        # Get the starting price (open of first bar in window)
        eod_start_price = eod_data.iloc[0]['Open']

        # Get the ending price (close of last bar)
        eod_end_price = eod_data.iloc[-1]['Close']

        if eod_start_price == 0:
            return 0.0, eod_start_price, eod_end_price

        spike_pct = ((eod_end_price - eod_start_price) / eod_start_price) * 100

        return spike_pct, eod_start_price, eod_end_price

    def scan_ticker_for_pattern(self, ticker: str, start_date: str, end_date: str) -> List[Dict]:
        """
        Scan a ticker for flat-to-EOD-spike pattern.

        Args:
            ticker: Stock ticker symbol
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            List of pattern matches with details
        """
        matches = []

        try:
            # Download 5-minute data
            stock = yf.Ticker(ticker)
            df = stock.history(start=start_date, end=end_date, interval='5m')

            if df.empty:
                print(f"  ⚠️  No data for {ticker}")
                return matches

            # Group by date
            df['Date'] = df.index.date

            for date, day_data in df.groupby('Date'):
                # Need at least some bars to analyze
                if len(day_data) < 10:
                    continue

                # Calculate intraday range excluding EOD window
                intraday_range_pct = self.calculate_intraday_range(
                    day_data,
                    self.eod_window_minutes
                )

                # Calculate EOD spike
                eod_spike_pct, eod_start, eod_end = self.calculate_eod_spike(
                    day_data,
                    self.eod_window_minutes
                )

                # Check if pattern matches
                is_flat = intraday_range_pct <= self.flat_threshold_pct
                has_eod_spike = eod_spike_pct >= self.eod_spike_threshold_pct

                if is_flat and has_eod_spike:
                    matches.append({
                        'ticker': ticker,
                        'date': str(date),
                        'intraday_range_pct': round(intraday_range_pct, 2),
                        'eod_spike_pct': round(eod_spike_pct, 2),
                        'eod_start_price': round(eod_start, 2),
                        'eod_end_price': round(eod_end, 2),
                        'day_open': round(day_data.iloc[0]['Open'], 2),
                        'day_high': round(day_data['High'].max(), 2),
                        'day_low': round(day_data['Low'].min(), 2),
                        'day_close': round(day_data.iloc[-1]['Close'], 2),
                        'volume': int(day_data['Volume'].sum())
                    })

        except Exception as e:
            print(f"  ❌ Error scanning {ticker}: {str(e)}")

        return matches

    def scan_multiple_tickers(self,
                            tickers: List[str],
                            start_date: str,
                            end_date: str,
                            verbose: bool = True) -> Dict[str, List[Dict]]:
        """
        Scan multiple tickers for the pattern.

        Args:
            tickers: List of ticker symbols
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            verbose: Print progress

        Returns:
            Dictionary mapping tickers to their pattern matches
        """
        all_results = {}

        for ticker in tickers:
            if verbose:
                print(f"\n📊 Scanning {ticker}...")

            matches = self.scan_ticker_for_pattern(ticker, start_date, end_date)

            if matches:
                all_results[ticker] = matches
                if verbose:
                    print(f"  ✅ Found {len(matches)} pattern match(es)")
            else:
                if verbose:
                    print(f"  ❌ No patterns found")

        return all_results

    def print_results(self, results: Dict[str, List[Dict]]):
        """Print formatted results."""
        print("\n" + "=" * 100)
        print("FLAT-TO-EOD-SPIKE PATTERN SCAN RESULTS")
        print("=" * 100)

        if not results:
            print("\nNo patterns found matching criteria.")
            return

        total_matches = sum(len(matches) for matches in results.values())
        print(f"\nFound {total_matches} total pattern matches across {len(results)} tickers\n")

        for ticker, matches in results.items():
            print(f"\n{ticker} - {len(matches)} match(es):")
            print("-" * 100)

            for match in matches:
                print(f"  Date: {match['date']}")
                print(f"    Intraday Range: {match['intraday_range_pct']}% (flat threshold: {self.flat_threshold_pct}%)")
                print(f"    EOD Spike: {match['eod_spike_pct']}% (from ${match['eod_start_price']} to ${match['eod_end_price']})")
                print(f"    Day Stats: Open=${match['day_open']}, High=${match['day_high']}, Low=${match['day_low']}, Close=${match['day_close']}")
                print(f"    Volume: {match['volume']:,}")
                print()


def main():
    parser = argparse.ArgumentParser(
        description='Scan tickers for flat intraday with EOD spike pattern'
    )
    parser.add_argument(
        '--tickers',
        type=str,
        help='Comma-separated list of tickers (e.g., AAPL,MSFT,TSLA)',
        required=False
    )
    parser.add_argument(
        '--file',
        type=str,
        help='File containing tickers (one per line)',
        required=False
    )
    parser.add_argument(
        '--start-date',
        type=str,
        help='Start date (YYYY-MM-DD)',
        default=(datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    )
    parser.add_argument(
        '--end-date',
        type=str,
        help='End date (YYYY-MM-DD)',
        default=datetime.now().strftime('%Y-%m-%d')
    )
    parser.add_argument(
        '--flat-threshold',
        type=float,
        help='Max intraday range %% to consider "flat" (default: 2.0)',
        default=2.0
    )
    parser.add_argument(
        '--spike-threshold',
        type=float,
        help='Min EOD spike %% (default: 5.0)',
        default=5.0
    )
    parser.add_argument(
        '--eod-window',
        type=int,
        help='EOD window in minutes (default: 60)',
        default=60
    )

    args = parser.parse_args()

    # Get tickers list
    tickers = []
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(',')]
    elif args.file:
        with open(args.file, 'r') as f:
            tickers = [line.strip().upper() for line in f if line.strip()]
    else:
        # Default example tickers
        tickers = ['AAPL', 'MSFT', 'TSLA', 'NVDA', 'AMD']
        print("No tickers specified, using examples:", tickers)

    print(f"\n{'=' * 100}")
    print("CONFIGURATION")
    print(f"{'=' * 100}")
    print(f"Tickers: {', '.join(tickers)}")
    print(f"Date Range: {args.start_date} to {args.end_date}")
    print(f"Flat Threshold: {args.flat_threshold}% intraday range")
    print(f"EOD Spike Threshold: {args.spike_threshold}%")
    print(f"EOD Window: Last {args.eod_window} minutes")
    print(f"{'=' * 100}")

    # Create scanner and run
    scanner = FlatEODSpikeScanner(
        flat_threshold_pct=args.flat_threshold,
        eod_spike_threshold_pct=args.spike_threshold,
        eod_window_minutes=args.eod_window
    )

    results = scanner.scan_multiple_tickers(
        tickers,
        args.start_date,
        args.end_date
    )

    scanner.print_results(results)


if __name__ == "__main__":
    main()
