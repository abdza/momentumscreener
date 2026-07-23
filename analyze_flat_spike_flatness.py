#!/usr/bin/env python3
"""
Does how flat a ticker was before its premarket spike predict flat_spike_strategy
trade outcome? Uses the daily-bar cache already fetched by flat_spike_backtester.py
(momentum_data/flat_spike_cache/{ticker}_{day}_daily.json) - no new API calls.

Usage:
    python analyze_flat_spike_flatness.py
    python analyze_flat_spike_flatness.py --trades momentum_data/flat_spike_trades/trade_history.json
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

FLAT_RANGE_THRESHOLD_PCT = 8.0  # matches strategy.FLAT_MAX_DAILY_RANGE_PCT


def load_daily_bars(cache_dir: Path, ticker: str, day: str):
    f = cache_dir / f'{ticker}_{day}_daily.json'
    if not f.exists():
        return None
    rows = json.load(open(f))
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: r['d'])
    return rows


def flat_streak_days(daily_bars, threshold_pct=FLAT_RANGE_THRESHOLD_PCT):
    """Consecutive days counting back from the most recent pre-spike day whose
    daily range % stayed under threshold_pct."""
    streak = 0
    for bar in reversed(daily_bars):
        if bar['c'] <= 0:
            break
        rng_pct = (bar['h'] - bar['l']) / bar['c'] * 100
        if rng_pct > threshold_pct:
            break
        streak += 1
    return streak


def window_stats(daily_bars, n):
    """max/avg daily range % and net drift % over the last n days."""
    if len(daily_bars) < n:
        return None
    window = daily_bars[-n:]
    ranges = [(b['h'] - b['l']) / b['c'] * 100 for b in window if b['c'] > 0]
    if not ranges:
        return None
    first_close = window[0]['c']
    last_close = window[-1]['c']
    net_drift = abs(last_close - first_close) / first_close * 100 if first_close > 0 else None
    return {
        'max_range_pct': max(ranges),
        'avg_range_pct': sum(ranges) / len(ranges),
        'net_drift_pct': net_drift,
    }


def build_features(trades, cache_dir: Path):
    rows = []
    for t in trades:
        ticker = t['ticker']
        day = t['entry_timestamp'][:10]
        daily_bars = load_daily_bars(cache_dir, ticker, day)
        if not daily_bars or len(daily_bars) < 5:
            continue

        row = {
            'ticker': ticker,
            'day': day,
            'profit_pct': t['profit_pct'],
            'win': t['profit_loss'] > 0,
            'flat_streak_days': flat_streak_days(daily_bars),
        }
        for n in (3, 5, 10):
            stats = window_stats(daily_bars, n)
            if stats:
                row[f'max_range_pct_{n}d'] = stats['max_range_pct']
                row[f'avg_range_pct_{n}d'] = stats['avg_range_pct']
                row[f'net_drift_pct_{n}d'] = stats['net_drift_pct']
        rows.append(row)
    return pd.DataFrame(rows)


def feature_correlations(df):
    print("=" * 78)
    print(f"FLATNESS vs TRADE OUTCOME (n={len(df)} trades)")
    print("=" * 78)
    feats = [
        ('flat_streak_days', 'Consecutive flat days before spike (range < 8%)'),
        ('max_range_pct_3d', 'Worst single-day range %, last 3 days'),
        ('max_range_pct_5d', 'Worst single-day range %, last 5 days'),
        ('max_range_pct_10d', 'Worst single-day range %, last 10 days'),
        ('avg_range_pct_5d', 'Avg daily range %, last 5 days'),
        ('avg_range_pct_10d', 'Avg daily range %, last 10 days'),
        ('net_drift_pct_5d', 'Net drift %, last 5 days'),
        ('net_drift_pct_10d', 'Net drift %, last 10 days'),
    ]
    print(f"\nBase rate: {df['win'].mean():.0%} win rate, median return {df['profit_pct'].median():+.1f}%\n")
    print(f"{'feature':<48}{'spearman':>10}   win rate by quartile (Q1(flattest)->Q4)")
    print("-" * 100)
    for col, label in feats:
        if col not in df.columns:
            continue
        e = df.dropna(subset=[col])
        if len(e) < 10:
            continue
        rho = e[col].rank().corr(e['profit_pct'].rank())
        try:
            q = pd.qcut(e[col], 4, duplicates='drop')
            wr = e.groupby(q, observed=True)['win'].mean()
            mp = e.groupby(q, observed=True)['profit_pct'].median()
            wrs = "  ".join(f"{v:.0%}" for v in wr)
            mps = "  ".join(f"{v:+.0f}%" for v in mp)
        except ValueError:
            wrs = mps = "n/a"
        print(f"{label:<48}{rho:>+9.2f}   {wrs}")
        print(f"{'':<48}{'':>10}   med return: {mps}")


def streak_buckets(df):
    print("\n" + "=" * 78)
    print("WIN RATE BY LENGTH OF FLAT STREAK")
    print("=" * 78)
    bins = [0, 3, 5, 8, 12, 100]
    labels = ['0-2d', '3-4d', '5-7d', '8-11d', '12d+']
    df = df.copy()
    df['streak_bucket'] = pd.cut(df['flat_streak_days'], bins=bins, labels=labels, right=False)
    g = df.groupby('streak_bucket', observed=True).agg(
        n=('win', 'size'), win_rate=('win', 'mean'), med_return=('profit_pct', 'median'),
        avg_return=('profit_pct', 'mean'))
    print(g.to_string(float_format=lambda x: f"{x:.2f}"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--trades', default='momentum_data/flat_spike_trades/trade_history.json')
    parser.add_argument('--cache-dir', default='momentum_data/flat_spike_cache')
    args = parser.parse_args()

    trades = json.load(open(args.trades))
    df = build_features(trades, Path(args.cache_dir))
    print(f"Built features for {len(df)}/{len(trades)} trades (rest missing cached daily bars)\n")

    feature_correlations(df)
    streak_buckets(df)


if __name__ == '__main__':
    main()
