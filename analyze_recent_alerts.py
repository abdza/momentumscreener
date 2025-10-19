#!/usr/bin/env python3
"""
Analyze recent alerts from the last 2 weeks to determine optimal ranges
"""

import json
import yfinance as yf
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

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

print(f"📊 ANALYZING {len(alerts)} ALERTS FROM LAST 2 WEEKS")
print("=" * 70)

# Analyze success by getting unique tickers (first alert only)
unique_tickers = {}
for alert in alerts:
    ticker = alert['ticker']
    if ticker not in unique_tickers:
        unique_tickers[ticker] = alert

print(f"📈 Found {len(unique_tickers)} unique tickers")
print()

# Analyze each ticker's performance
winners = []
losers = []
no_data = []

print("🔍 Checking price performance for each ticker...")
for i, (ticker, alert) in enumerate(unique_tickers.items(), 1):
    if i % 10 == 0:
        print(f"   Processed {i}/{len(unique_tickers)} tickers...")

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

        alert['max_gain'] = max_gain_value
        alert['max_price'] = max_price_value

        if max_gain_value >= 30:
            winners.append(alert)
        else:
            losers.append(alert)
    else:
        no_data.append(ticker)

print()
print("=" * 70)
print(f"✅ WINNERS (30%+ gain): {len(winners)}")
print(f"❌ LOSERS (<30% gain): {len(losers)}")
print(f"⚠️  NO DATA: {len(no_data)}")
if len(winners) + len(losers) > 0:
    print(f"📊 SUCCESS RATE: {len(winners)/(len(winners)+len(losers))*100:.1f}%")
else:
    print(f"📊 SUCCESS RATE: N/A (no performance data available)")
print("=" * 70)
print()

# Analyze winning patterns
if winners:
    print("🏆 WINNING PATTERN ANALYSIS")
    print("=" * 70)

    # Price ranges
    winner_prices = [w['alert_price'] for w in winners]
    print(f"💰 PRICE RANGES:")
    print(f"   Under $1: {len([p for p in winner_prices if p < 1])}")
    print(f"   $1-3: {len([p for p in winner_prices if 1 <= p < 3])}")
    print(f"   $3-6: {len([p for p in winner_prices if 3 <= p < 6])}")
    print(f"   $6-10: {len([p for p in winner_prices if 6 <= p < 10])}")
    print(f"   Over $10: {len([p for p in winner_prices if p >= 10])}")
    print(f"   Avg: ${statistics.mean(winner_prices):.2f}, Median: ${statistics.median(winner_prices):.2f}")
    print()

    # Volume ranges
    winner_volumes = [w['relative_volume'] for w in winners if w.get('relative_volume')]
    if winner_volumes:
        print(f"📊 RELATIVE VOLUME RANGES:")
        print(f"   Under 10x: {len([v for v in winner_volumes if v < 10])}")
        print(f"   10-50x: {len([v for v in winner_volumes if 10 <= v < 50])}")
        print(f"   50-200x: {len([v for v in winner_volumes if 50 <= v < 200])}")
        print(f"   200-500x: {len([v for v in winner_volumes if 200 <= v < 500])}")
        print(f"   Over 500x: {len([v for v in winner_volumes if v >= 500])}")
        print(f"   Avg: {statistics.mean(winner_volumes):.1f}x, Median: {statistics.median(winner_volumes):.1f}x")
        print()

    # Change percentage ranges
    winner_changes = [w['change_pct'] for w in winners]
    print(f"⚡ INITIAL CHANGE % RANGES:")
    print(f"   Under 15%: {len([c for c in winner_changes if c < 15])}")
    print(f"   15-30%: {len([c for c in winner_changes if 15 <= c < 30])}")
    print(f"   30-50%: {len([c for c in winner_changes if 30 <= c < 50])}")
    print(f"   50-100%: {len([c for c in winner_changes if 50 <= c < 100])}")
    print(f"   Over 100%: {len([c for c in winner_changes if c >= 100])}")
    print(f"   Avg: {statistics.mean(winner_changes):.1f}%, Median: {statistics.median(winner_changes):.1f}%")
    print()

    # Sectors
    winner_sectors = defaultdict(int)
    for w in winners:
        winner_sectors[w.get('sector', 'Unknown')] += 1
    print(f"🏭 TOP WINNING SECTORS:")
    for sector, count in sorted(winner_sectors.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"   {sector}: {count}")
    print()

    # Alert types
    winner_types = defaultdict(int)
    for w in winners:
        for atype in w.get('alert_types', []):
            winner_types[atype] += 1
    print(f"📈 WINNING ALERT TYPES:")
    for atype, count in sorted(winner_types.items(), key=lambda x: x[1], reverse=True):
        print(f"   {atype}: {count}")
    print()

    # Pattern scores
    winner_scores = [w.get('pattern_score', 0) for w in winners if w.get('pattern_score')]
    if winner_scores:
        print(f"🎯 PATTERN SCORES:")
        print(f"   Avg: {statistics.mean(winner_scores):.1f}, Median: {statistics.median(winner_scores):.1f}")
        print(f"   Min: {min(winner_scores)}, Max: {max(winner_scores)}")
        print()

# Analyze losing patterns for comparison
if losers:
    print("❌ LOSING PATTERN ANALYSIS (for comparison)")
    print("=" * 70)

    # Price ranges
    loser_prices = [l['alert_price'] for l in losers]
    print(f"💰 PRICE RANGES:")
    print(f"   Under $1: {len([p for p in loser_prices if p < 1])}")
    print(f"   $1-3: {len([p for p in loser_prices if 1 <= p < 3])}")
    print(f"   $3-6: {len([p for p in loser_prices if 3 <= p < 6])}")
    print(f"   $6-10: {len([p for p in loser_prices if 6 <= p < 10])}")
    print(f"   Over $10: {len([p for p in loser_prices if p >= 10])}")
    print(f"   Avg: ${statistics.mean(loser_prices):.2f}, Median: ${statistics.median(loser_prices):.2f}")
    print()

    # Volume ranges
    loser_volumes = [l['relative_volume'] for l in losers if l.get('relative_volume')]
    if loser_volumes:
        print(f"📊 RELATIVE VOLUME RANGES:")
        print(f"   Under 10x: {len([v for v in loser_volumes if v < 10])}")
        print(f"   10-50x: {len([v for v in loser_volumes if 10 <= v < 50])}")
        print(f"   50-200x: {len([v for v in loser_volumes if 50 <= v < 200])}")
        print(f"   200-500x: {len([v for v in loser_volumes if 200 <= v < 500])}")
        print(f"   Over 500x: {len([v for v in loser_volumes if v >= 500])}")
        print(f"   Avg: {statistics.mean(loser_volumes):.1f}x, Median: {statistics.median(loser_volumes):.1f}x")
        print()

print("=" * 70)
print("💡 RECOMMENDATIONS FOR volume_momentum_tracker.py")
print("=" * 70)

if winners and losers:
    winner_prices = [w['alert_price'] for w in winners]
    loser_prices = [l['alert_price'] for l in losers]

    # Price sweet spot
    winner_1_3 = len([p for p in winner_prices if 1 <= p < 3])
    total_1_3 = len([p for p in winner_prices if 1 <= p < 3]) + len([p for p in loser_prices if 1 <= p < 3])

    winner_3_6 = len([p for p in winner_prices if 3 <= p < 6])
    total_3_6 = len([p for p in winner_prices if 3 <= p < 6]) + len([p for p in loser_prices if 3 <= p < 6])

    if total_1_3 > 0:
        success_1_3 = (winner_1_3 / total_1_3) * 100
        print(f"📊 $1-3 range: {success_1_3:.1f}% success rate ({winner_1_3}/{total_1_3})")

    if total_3_6 > 0:
        success_3_6 = (winner_3_6 / total_3_6) * 100
        print(f"📊 $3-6 range: {success_3_6:.1f}% success rate ({winner_3_6}/{total_3_6})")

    # Volume analysis
    winner_volumes = [w['relative_volume'] for w in winners if w.get('relative_volume')]
    loser_volumes = [l['relative_volume'] for l in losers if l.get('relative_volume')]

    if winner_volumes:
        print(f"📊 Winning alerts avg volume: {statistics.mean(winner_volumes):.1f}x")
    if loser_volumes:
        print(f"📊 Losing alerts avg volume: {statistics.mean(loser_volumes):.1f}x")

print()
print("✅ Analysis complete!")
