#!/usr/bin/env python3
"""
Scan Recent Alerts for Flat-to-EOD-Spike Pattern
Extracts tickers from recent alerts and scans them for flat days with EOD spikes.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Set, List
from flat_eod_spike_scanner import FlatEODSpikeScanner


def extract_tickers_from_alerts(alerts_dir: str, days_back: int = 21) -> Set[str]:
    """
    Extract unique tickers from alert files in the past N days.

    Args:
        alerts_dir: Directory containing alert files
        days_back: Number of days to look back

    Returns:
        Set of unique ticker symbols
    """
    cutoff_date = datetime.now() - timedelta(days=days_back)
    tickers = set()

    alerts_path = Path(alerts_dir)
    if not alerts_path.exists():
        print(f"Warning: Alerts directory {alerts_dir} not found")
        return tickers

    # Find all alert JSON files
    alert_files = sorted(alerts_path.glob("alerts_*.json"), reverse=True)

    print(f"Scanning {len(alert_files)} alert files for tickers from the past {days_back} days...")

    for alert_file in alert_files:
        try:
            # Parse timestamp from filename (format: alerts_YYYYMMDD_HHMMSS.json)
            filename = alert_file.stem
            date_str = filename.split('_')[1]  # Get YYYYMMDD part
            file_date = datetime.strptime(date_str, '%Y%m%d')

            # Skip if file is too old
            if file_date < cutoff_date:
                continue

            # Read and parse the alert file
            with open(alert_file, 'r') as f:
                data = json.load(f)

            # Extract tickers from all alert categories
            alert_categories = [
                'volume_climbers',
                'volume_newcomers',
                'price_spikes',
                'premarket_volume_alerts',
                'premarket_price_alerts',
                'sustained_positive_alerts'
            ]

            for category in alert_categories:
                if category in data and isinstance(data[category], list):
                    for alert in data[category]:
                        if 'ticker' in alert:
                            tickers.add(alert['ticker'])

        except Exception as e:
            print(f"Warning: Error processing {alert_file.name}: {e}")
            continue

    return tickers


def extract_tickers_from_telegram(telegram_file: str, days_back: int = 21) -> Set[str]:
    """
    Extract tickers from telegram_last_sent.json that were sent in the past N days.

    Args:
        telegram_file: Path to telegram_last_sent.json
        days_back: Number of days to look back

    Returns:
        Set of unique ticker symbols
    """
    tickers = set()
    cutoff_date = datetime.now() - timedelta(days=days_back)

    telegram_path = Path(telegram_file)
    if not telegram_path.exists():
        print(f"Warning: Telegram file {telegram_file} not found")
        return tickers

    try:
        with open(telegram_path, 'r') as f:
            data = json.load(f)

        for ticker, timestamp_str in data.items():
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                if timestamp >= cutoff_date:
                    tickers.add(ticker)
            except Exception as e:
                print(f"Warning: Error parsing timestamp for {ticker}: {e}")
                continue

    except Exception as e:
        print(f"Warning: Error reading telegram file: {e}")

    return tickers


def main():
    # Configuration
    ALERTS_DIR = "momentum_data"
    TELEGRAM_FILE = "momentum_data/telegram_last_sent.json"
    DAYS_BACK = 21  # Past 3 weeks

    print("=" * 100)
    print("RECENT ALERTS FLAT-TO-EOD-SPIKE SCANNER")
    print("=" * 100)
    print(f"\nExtracting tickers from the past {DAYS_BACK} days...\n")

    # Extract tickers from alerts
    alert_tickers = extract_tickers_from_alerts(ALERTS_DIR, DAYS_BACK)
    print(f"\nFound {len(alert_tickers)} unique tickers from alert files")

    # Extract tickers from telegram
    telegram_tickers = extract_tickers_from_telegram(TELEGRAM_FILE, DAYS_BACK)
    print(f"Found {len(telegram_tickers)} unique tickers from telegram file")

    # Combine all tickers
    all_tickers = alert_tickers.union(telegram_tickers)
    print(f"\nTotal unique tickers to scan: {len(all_tickers)}")
    print(f"Tickers: {sorted(all_tickers)}\n")

    if not all_tickers:
        print("No tickers found. Exiting.")
        return

    # Calculate date range for scanning
    # Scan from 30 days ago to today to capture patterns
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')

    print(f"Scanning date range: {start_date} to {end_date}")
    print("=" * 100)

    # Create scanner with parameters
    scanner = FlatEODSpikeScanner(
        flat_threshold_pct=2.0,      # Max 2% intraday range for "flat"
        eod_spike_threshold_pct=5.0,  # Min 5% spike at EOD
        eod_window_minutes=60         # Last 60 minutes of trading day
    )

    # Scan all tickers
    results = scanner.scan_multiple_tickers(
        sorted(all_tickers),
        start_date,
        end_date,
        verbose=True
    )

    # Print results
    scanner.print_results(results)

    # Save results to file
    output_file = "momentum_data/flat_eod_spike_results.json"
    output_data = {
        'scan_date': datetime.now().isoformat(),
        'days_back': DAYS_BACK,
        'date_range': {'start': start_date, 'end': end_date},
        'total_tickers_scanned': len(all_tickers),
        'tickers_with_patterns': len(results),
        'total_patterns_found': sum(len(matches) for matches in results.values()),
        'results': results
    }

    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)

    print(f"\n\nResults saved to: {output_file}")


if __name__ == "__main__":
    main()
