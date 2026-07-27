#!/usr/bin/env python3
"""
Measure the TradingView scanner's discovery lag from the monitor's own output.

premarket_top20_monitor.py merges scanner records first and bar-stream records
second, so a record tagged source='alpaca_stream' is one the scanner did NOT
have at that moment. When the same ticker later reappears tagged 'tradingview',
the gap between those two snapshots is the scanner's lag, measured directly.

This replaces compare_stream_vs_pipeline.py for routine use: it needs no
websocket of its own (Alpaca permits one per account, and the monitor now holds
it), and it reads snapshots already on disk, so it can be run after the fact for
any past session.

Usage:
    python analyze_candidate_sources.py                # today
    python analyze_candidate_sources.py --date 20260728
"""

import argparse
import glob
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytz

LOCAL = pytz.timezone('Asia/Kuala_Lumpur')  # pretop20 timestamps are naive local time
BASE = Path(__file__).resolve().parent


def load_snapshots(date_str):
    out = []
    for f in sorted(glob.glob(str(BASE / 'pretop20' / f'screener_{date_str}_*.json'))):
        try:
            snap = json.load(open(f, encoding='utf-8'))
            ts = datetime.fromisoformat(snap['timestamp'])
            if ts.tzinfo is None:
                ts = LOCAL.localize(ts)
            out.append((ts, snap.get('data', [])))
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            continue
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--date', default=datetime.now().strftime('%Y%m%d'))
    args = ap.parse_args()

    snaps = load_snapshots(args.date)
    if not snaps:
        print(f"no snapshots for {args.date}")
        return

    first_seen, first_by_source = {}, {}
    for ts, rows in snaps:
        for r in rows:
            sym, src = r.get('name'), r.get('source', 'tradingview')
            if not sym:
                continue
            first_seen.setdefault(sym, (ts, src))
            first_by_source.setdefault((sym, src), ts)

    print(f"{len(snaps)} snapshots, {snaps[0][0]:%H:%M}-{snaps[-1][0]:%H:%M} local, "
          f"{len(first_seen)} distinct tickers\n")
    print("first discovered by:", dict(Counter(src for _, src in first_seen.values())))

    # tickers the stream found before the scanner had them
    lags = []
    stream_only = []
    for sym, (ts, src) in first_seen.items():
        if src != 'alpaca_stream':
            continue
        tv = first_by_source.get((sym, 'tradingview'))
        if tv:
            lags.append(((tv - ts).total_seconds() / 60, sym, ts, tv))
        else:
            stream_only.append((sym, ts))

    if lags:
        lags.sort(reverse=True)
        print(f"\n{len(lags)} tickers found by the stream first, then picked up by the scanner:")
        print(f"  {'ticker':<8}{'stream':>9}{'scanner':>10}{'scanner lag':>13}")
        for d, sym, ts, tv in lags:
            print(f"  {sym:<8}{ts:%H:%M:%S}{tv:%H:%M:%S}{d:>+11.0f}m")
        vals = sorted(d for d, _, _, _ in lags)
        print(f"  median scanner lag behind the stream: {vals[len(vals)//2]:+.0f} min")
    else:
        print("\nno ticker was found by the stream and later picked up by the scanner")

    if stream_only:
        print(f"\n{len(stream_only)} found only by the stream (scanner never listed them):")
        print("  " + ", ".join(f"{s}@{t:%H:%M}" for s, t in sorted(stream_only, key=lambda x: x[1])))


if __name__ == '__main__':
    main()
