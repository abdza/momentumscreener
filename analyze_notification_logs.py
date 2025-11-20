#!/usr/bin/env python3
"""
Analyze telegram notification logs to optimize parameters for list_flat
"""

import json
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

def analyze_logs():
    log_file = "momentum_data/telegram_alerts_sent.jsonl"

    alerts = []
    with open(log_file, 'r') as f:
        for line in f:
            try:
                alerts.append(json.loads(line.strip()))
            except:
                continue

    print(f"\n{'='*80}")
    print(f"📊 NOTIFICATION LOG ANALYSIS")
    print(f"{'='*80}")
    print(f"\nTotal alerts logged: {len(alerts)}")

    if not alerts:
        print("No alerts found!")
        return

    # Date range
    timestamps = [datetime.fromisoformat(a['timestamp']) for a in alerts]
    print(f"Date range: {min(timestamps).strftime('%Y-%m-%d')} to {max(timestamps).strftime('%Y-%m-%d')}")

    # Analyze by various dimensions
    print(f"\n{'='*80}")
    print("📈 PRICE CHANGE ANALYSIS")
    print(f"{'='*80}")

    change_pcts = [a.get('change_pct', 0) for a in alerts if a.get('change_pct')]
    if change_pcts:
        print(f"  Min change: {min(change_pcts):.1f}%")
        print(f"  Max change: {max(change_pcts):.1f}%")
        print(f"  Mean change: {statistics.mean(change_pcts):.1f}%")
        print(f"  Median change: {statistics.median(change_pcts):.1f}%")

        # Distribution
        ranges = [(0, 5), (5, 10), (10, 15), (15, 20), (20, 30), (30, 50), (50, 100), (100, 1000)]
        print(f"\n  Change % Distribution:")
        for low, high in ranges:
            count = len([c for c in change_pcts if low <= c < high])
            pct = count / len(change_pcts) * 100
            bar = '█' * int(pct / 2)
            print(f"    {low:3d}-{high:3d}%: {count:4d} ({pct:5.1f}%) {bar}")

    print(f"\n{'='*80}")
    print("📊 RELATIVE VOLUME ANALYSIS")
    print(f"{'='*80}")

    rel_vols = [a.get('relative_volume', 0) for a in alerts if a.get('relative_volume') and a.get('relative_volume') > 0]
    if rel_vols:
        print(f"  Min relative volume: {min(rel_vols):.1f}x")
        print(f"  Max relative volume: {max(rel_vols):.1f}x")
        print(f"  Mean relative volume: {statistics.mean(rel_vols):.1f}x")
        print(f"  Median relative volume: {statistics.median(rel_vols):.1f}x")

        # Distribution
        vol_ranges = [(0, 1), (1, 2), (2, 3), (3, 5), (5, 10), (10, 20), (20, 100)]
        print(f"\n  Relative Volume Distribution:")
        for low, high in vol_ranges:
            count = len([v for v in rel_vols if low <= v < high])
            pct = count / len(rel_vols) * 100
            bar = '█' * int(pct / 2)
            print(f"    {low:3d}-{high:3d}x: {count:4d} ({pct:5.1f}%) {bar}")

    print(f"\n{'='*80}")
    print("🏷️ SECTOR ANALYSIS")
    print(f"{'='*80}")

    sectors = defaultdict(list)
    for a in alerts:
        sector = a.get('sector', 'Unknown')
        sectors[sector].append(a)

    print(f"\n  Alerts by Sector:")
    sector_stats = []
    for sector, sector_alerts in sorted(sectors.items(), key=lambda x: -len(x[1])):
        changes = [a.get('change_pct', 0) for a in sector_alerts if a.get('change_pct')]
        avg_change = statistics.mean(changes) if changes else 0
        sector_stats.append((sector, len(sector_alerts), avg_change))

    for sector, count, avg_change in sector_stats[:15]:
        pct = count / len(alerts) * 100
        print(f"    {sector[:30]:30s}: {count:4d} ({pct:5.1f}%) avg_chg={avg_change:+.1f}%")

    print(f"\n{'='*80}")
    print("🔔 ALERT TYPE ANALYSIS")
    print(f"{'='*80}")

    alert_types = defaultdict(list)
    for a in alerts:
        atype = a.get('alert_type', 'unknown')
        alert_types[atype].append(a)

    print(f"\n  Alerts by Type:")
    for atype, type_alerts in sorted(alert_types.items(), key=lambda x: -len(x[1])):
        changes = [a.get('change_pct', 0) for a in type_alerts if a.get('change_pct')]
        avg_change = statistics.mean(changes) if changes else 0
        pct = len(type_alerts) / len(alerts) * 100
        print(f"    {atype:25s}: {len(type_alerts):4d} ({pct:5.1f}%) avg_chg={avg_change:+.1f}%")

    print(f"\n{'='*80}")
    print("⚡ IMMEDIATE SPIKE ANALYSIS")
    print(f"{'='*80}")

    immediate = [a for a in alerts if a.get('is_immediate_spike')]
    regular = [a for a in alerts if not a.get('is_immediate_spike')]

    print(f"\n  Immediate spikes: {len(immediate)} ({len(immediate)/len(alerts)*100:.1f}%)")
    print(f"  Regular alerts: {len(regular)} ({len(regular)/len(alerts)*100:.1f}%)")

    if immediate:
        imm_changes = [a.get('change_pct', 0) for a in immediate if a.get('change_pct')]
        if imm_changes:
            print(f"\n  Immediate spike stats:")
            print(f"    Min change: {min(imm_changes):.1f}%")
            print(f"    Max change: {max(imm_changes):.1f}%")
            print(f"    Avg change: {statistics.mean(imm_changes):.1f}%")

    print(f"\n{'='*80}")
    print("📈 WIN PROBABILITY ANALYSIS")
    print(f"{'='*80}")

    probabilities = defaultdict(list)
    for a in alerts:
        prob_cat = a.get('win_probability_category', 'UNKNOWN')
        probabilities[prob_cat].append(a)

    print(f"\n  Alerts by Win Probability Category:")
    for cat, cat_alerts in sorted(probabilities.items(), key=lambda x: -len(x[1])):
        changes = [a.get('change_pct', 0) for a in cat_alerts if a.get('change_pct')]
        avg_change = statistics.mean(changes) if changes else 0
        pct = len(cat_alerts) / len(alerts) * 100
        print(f"    {cat:15s}: {len(cat_alerts):4d} ({pct:5.1f}%) avg_chg={avg_change:+.1f}%")

    print(f"\n{'='*80}")
    print("🚫 DISREGARDED ALERTS")
    print(f"{'='*80}")

    disregarded = [a for a in alerts if a.get('disregarded')]
    print(f"\n  Disregarded alerts: {len(disregarded)} ({len(disregarded)/len(alerts)*100:.1f}%)")

    if disregarded:
        dis_tickers = defaultdict(int)
        for a in disregarded:
            dis_tickers[a.get('ticker', 'N/A')] += 1
        print(f"\n  Top disregarded tickers:")
        for ticker, count in sorted(dis_tickers.items(), key=lambda x: -x[1])[:10]:
            print(f"    {ticker}: {count}")

    print(f"\n{'='*80}")
    print("📊 TOP TICKERS BY FREQUENCY")
    print(f"{'='*80}")

    tickers = defaultdict(list)
    for a in alerts:
        tickers[a.get('ticker', 'N/A')].append(a)

    print(f"\n  Top 20 Most Alerted Tickers:")
    ticker_stats = []
    for ticker, ticker_alerts in tickers.items():
        changes = [a.get('change_pct', 0) for a in ticker_alerts if a.get('change_pct')]
        avg_change = statistics.mean(changes) if changes else 0
        ticker_stats.append((ticker, len(ticker_alerts), avg_change))

    ticker_stats.sort(key=lambda x: -x[1])
    for ticker, count, avg_change in ticker_stats[:20]:
        pct = count / len(alerts) * 100
        print(f"    {ticker:6s}: {count:4d} alerts ({pct:5.1f}%) avg_chg={avg_change:+.1f}%")

    print(f"\n{'='*80}")
    print("⏰ TIME OF DAY ANALYSIS")
    print(f"{'='*80}")

    hours = defaultdict(list)
    for a in alerts:
        try:
            ts = datetime.fromisoformat(a['timestamp'])
            hours[ts.hour].append(a)
        except:
            pass

    print(f"\n  Alerts by Hour (EST):")
    for hour in sorted(hours.keys()):
        hour_alerts = hours[hour]
        changes = [a.get('change_pct', 0) for a in hour_alerts if a.get('change_pct')]
        avg_change = statistics.mean(changes) if changes else 0
        pct = len(hour_alerts) / len(alerts) * 100
        bar = '█' * int(pct)
        print(f"    {hour:02d}:00 - {len(hour_alerts):4d} ({pct:5.1f}%) avg_chg={avg_change:+.1f}% {bar}")

    print(f"\n{'='*80}")
    print("💡 OPTIMIZATION RECOMMENDATIONS")
    print(f"{'='*80}")

    # Calculate optimal thresholds based on data
    print(f"\n  Based on the analysis:")

    # 1. Volume ratio recommendations
    if rel_vols:
        p25 = sorted(rel_vols)[len(rel_vols)//4]
        p50 = statistics.median(rel_vols)
        p75 = sorted(rel_vols)[3*len(rel_vols)//4]
        print(f"\n  📊 VOLUME RATIO:")
        print(f"    Current: 1x minimum")
        print(f"    25th percentile: {p25:.1f}x")
        print(f"    50th percentile: {p50:.1f}x")
        print(f"    75th percentile: {p75:.1f}x")
        if p25 > 1.5:
            print(f"    ⚡ RECOMMENDATION: Increase minimum to {max(1.5, p25-0.5):.1f}x to filter noise")

    # 2. Price change recommendations
    if change_pcts:
        p25 = sorted(change_pcts)[len(change_pcts)//4]
        p50 = statistics.median(change_pcts)
        print(f"\n  📈 PRICE CHANGE:")
        print(f"    25th percentile: {p25:.1f}%")
        print(f"    50th percentile: {p50:.1f}%")
        print(f"    ⚡ RECOMMENDATION: Consider focusing on {p25:.0f}%+ moves for better signal quality")

    # 3. Sector recommendations
    high_noise_sectors = []
    for sector, count, avg_change in sector_stats:
        if count > len(alerts) * 0.05 and avg_change < 10:
            high_noise_sectors.append(sector)

    if high_noise_sectors:
        print(f"\n  🏷️ SECTOR FILTERING:")
        print(f"    High-noise sectors (consider higher thresholds):")
        for sector in high_noise_sectors[:5]:
            print(f"      - {sector}")

    # 4. Time recommendations
    print(f"\n  ⏰ TIME-BASED:")
    peak_hours = sorted(hours.keys(), key=lambda h: len(hours[h]), reverse=True)[:3]
    print(f"    Peak activity hours: {', '.join([f'{h:02d}:00' for h in peak_hours])}")

    # 5. Alert type recommendations
    print(f"\n  🔔 ALERT TYPE QUALITY:")
    best_types = []
    for atype, type_alerts in alert_types.items():
        if len(type_alerts) >= 10:
            changes = [a.get('change_pct', 0) for a in type_alerts if a.get('change_pct')]
            if changes:
                avg = statistics.mean(changes)
                best_types.append((atype, avg, len(type_alerts)))

    best_types.sort(key=lambda x: -x[1])
    print(f"    Best performing alert types:")
    for atype, avg_change, count in best_types[:5]:
        print(f"      - {atype}: avg {avg_change:+.1f}% ({count} alerts)")

    print(f"\n{'='*80}")
    print("📋 SPECIFIC PARAMETER SUGGESTIONS FOR LIST_FLAT")
    print(f"{'='*80}")

    # Analyze for list_flat specific optimizations
    print(f"\n  Current list_flat settings:")
    print(f"    - Volume ratio minimum: 1x")
    print(f"    - Max results: 20")
    print(f"    - Sort: by intraday movement")

    print(f"\n  Suggested optimizations:")

    # Based on volume data
    if rel_vols and statistics.median(rel_vols) > 2:
        print(f"    1. VOLUME RATIO: Increase minimum from 1x to 1.5x")
        print(f"       (Current median is {statistics.median(rel_vols):.1f}x)")

    # Based on the noise level
    print(f"    2. TOP RESULTS: Consider reducing from 20 to 15")
    print(f"       (Focus on higher quality signals)")

    # Based on price movements
    if change_pcts:
        low_movers = len([c for c in change_pcts if c < 5])
        if low_movers > len(change_pcts) * 0.3:
            print(f"    3. INTRADAY MOVEMENT: Add minimum threshold of 2%")
            print(f"       ({low_movers} alerts ({low_movers/len(change_pcts)*100:.0f}%) were <5%)")

    print(f"\n")

if __name__ == "__main__":
    analyze_logs()
