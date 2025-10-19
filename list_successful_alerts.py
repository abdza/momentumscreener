#!/usr/bin/env python3
"""
List all successful alerts with dates and tickers
"""

import json
import yfinance as yf
from datetime import datetime, timedelta

def get_price_performance(ticker, alert_date, alert_price):
    """Get the price performance after an alert"""
    try:
        # Get data for 5 days after alert
        end_date = alert_date + timedelta(days=5)
        data = yf.download(ticker, start=alert_date, end=end_date, progress=False, interval='1d')

        if data.empty:
            return None, None

        # Get high price in the 5 days after alert
        max_price = data['High'].max()
        max_gain_pct = ((max_price - alert_price) / alert_price) * 100

        return max_price, max_gain_pct
    except Exception as e:
        return None, None

# Load alerts from last 2 weeks
two_weeks_ago = datetime.now() - timedelta(days=14)
alerts = []

with open('momentum_data/telegram_alerts_sent.jsonl', 'r') as f:
    for line in f:
        if line.strip():
            alert = json.loads(line)
            alert_time = datetime.fromisoformat(alert['timestamp'].replace('Z', '+00:00'))

            # Only include alerts from last 2 weeks
            if alert_time.replace(tzinfo=None) >= two_weeks_ago:
                alerts.append(alert)

# Get unique tickers (first alert only)
unique_tickers = {}
for alert in alerts:
    ticker = alert['ticker']
    if ticker not in unique_tickers:
        unique_tickers[ticker] = alert

# Analyze each ticker's performance
winners = []

print("Analyzing alerts...")
for i, (ticker, alert) in enumerate(unique_tickers.items(), 1):
    if i % 10 == 0:
        print(f"Processed {i}/{len(unique_tickers)} tickers...")

    alert_date = datetime.fromisoformat(alert['timestamp'].replace('Z', '+00:00')).date()
    alert_price = alert['alert_price']

    max_price, max_gain = get_price_performance(ticker, alert_date, alert_price)

    if max_gain is not None:
        # Convert Series to float if needed
        if hasattr(max_gain, 'iloc'):
            max_gain_value = float(max_gain.iloc[0])
            max_price_value = float(max_price.iloc[0]) if hasattr(max_price, 'iloc') else float(max_price)
        else:
            max_gain_value = float(max_gain)
            max_price_value = float(max_price)

        if max_gain_value >= 30:
            winners.append({
                'ticker': ticker,
                'date': alert_date.strftime('%Y-%m-%d'),
                'alert_price': alert_price,
                'max_price': max_price_value,
                'max_gain': max_gain_value,
                'alert_types': alert.get('alert_types', []),
                'sector': alert.get('sector', 'Unknown')
            })

# Sort by date
winners.sort(key=lambda x: x['date'])

print("\n" + "="*80)
print("SUCCESSFUL ALERTS (30%+ gain within 5 days)")
print("="*80)
print(f"Total: {len(winners)} alerts\n")

for w in winners:
    alert_types_str = ', '.join(w['alert_types'])
    print(f"{w['date']} | {w['ticker']:8s} | ${w['alert_price']:7.2f} -> ${w['max_price']:7.2f} | +{w['max_gain']:6.1f}% | {alert_types_str}")
    print(f"           | Sector: {w['sector']}")
    print()

print("="*80)
print(f"SUCCESS RATE: {len(winners)}/{len(unique_tickers)} = {len(winners)/len(unique_tickers)*100:.1f}%")
print("="*80)
