#!/usr/bin/env python3
"""
Side-by-side comparison: alpaca_stream_screener.StreamScreener vs the TradingView
candidate source in premarket_top20_monitor.py.

Records, for every ticker either source surfaces, the first time each one did -
so "which finds movers sooner" is answered with timestamps rather than argument.

Reads pretop20/screener_*.json for the incumbent side, which the already-running
premarket_top20_monitor.py writes ~once a minute. It does not touch the monitor.

SUPERSEDED for routine use by analyze_candidate_sources.py. The monitor now runs
the stream itself and tags records with their source, so discovery lag is readable
straight from its snapshots - and since Alpaca permits one market-data websocket
per account, running this while the monitor is up will fail on the connection.
Stop the monitor first if you want the standalone A/B.

IMPORTANT: start this at 04:00 ET, together with the monitor. A late start makes
the comparison meaningless in the incumbent's favour - the monitor will have been
accumulating candidates since the premarket open while the stream begins with an
empty table and cannot surface a ticker until it has accrued enough fresh bars to
clear the dollar-volume floor. A 06:36 ET start on 2026-07-27 produced uniformly
"stream is later" deltas that were pure cold-start artifact.

Usage:
    python compare_stream_vs_pipeline.py                 # run until 09:25 ET
    python compare_stream_vs_pipeline.py --until 07:00   # stop earlier
"""

import argparse
import glob
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pytz

from alpaca_stream_screener import StreamScreener

ET = pytz.timezone('America/New_York')
LOCAL = pytz.timezone('Asia/Kuala_Lumpur')  # pretop20 timestamps are naive local time
BASE = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)


def pipeline_candidates(now_et, min_change):
    """Tickers at/above min_change in the newest pretop20 snapshot, and its timestamp."""
    files = sorted(glob.glob(str(BASE / 'pretop20' / f'screener_{now_et:%Y%m%d}_*.json')))
    if not files:
        return set(), None
    try:
        snap = json.load(open(files[-1], encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return set(), None
    ts = datetime.fromisoformat(snap.get('timestamp', ''))
    ts = LOCAL.localize(ts).astimezone(ET) if ts.tzinfo is None else ts.astimezone(ET)
    out = set()
    for r in snap.get('data', []):
        chg = r.get('alpaca_premarket_change')
        if chg is None:
            chg = r.get('premarket_change')
        if chg is not None and chg >= min_change:
            out.add(r['name'])
    return out, ts


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--until', default='09:25', help='stop at this ET time (HH:MM)')
    ap.add_argument('--min-change', type=float, default=10.0)
    ap.add_argument('--min-dollar-vol', type=float, default=100_000)
    ap.add_argument('--out', default=None, help='results JSON (default: momentum_data/stream_comparison_YYYYMMDD.json)')
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.getLogger('alpaca').setLevel(logging.WARNING)

    now = datetime.now(ET)
    hh, mm = (int(x) for x in args.until.split(':'))
    end = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    out_path = Path(args.out) if args.out else \
        BASE / 'momentum_data' / f'stream_comparison_{now:%Y%m%d}.json'
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if now >= end:
        logger.error(f"start time {now:%H:%M} ET is already past --until {args.until} ET")
        sys.exit(1)
    if now.hour > 4 or (now.hour == 4 and now.minute > 10):
        logger.warning(f"⚠️  starting at {now:%H:%M} ET, not 04:00 - the stream begins cold "
                        f"while the monitor has been running since the open, so early "
                        f"'who was first' deltas will favour the pipeline unfairly")

    screener = StreamScreener()
    screener.start()
    logger.info(f"▶️  comparison running until {end:%H:%M} ET -> {out_path}")

    first_stream, first_pipe, peak_change = {}, {}, {}
    try:
        while datetime.now(ET) < end:
            time.sleep(60)
            now = datetime.now(ET)
            try:
                cands = screener.candidates(min_change_pct=args.min_change,
                                            min_dollar_volume=args.min_dollar_vol)
            except Exception as e:
                logger.warning(f"⚠️  candidates() failed: {e}")
                cands = []
            for c in cands:
                first_stream.setdefault(c['symbol'], now)
                peak_change[c['symbol']] = max(peak_change.get(c['symbol'], -999.0),
                                               c['change_pct'])

            pipe, pipe_ts = pipeline_candidates(now, args.min_change)
            for sym in pipe:
                first_pipe.setdefault(sym, pipe_ts or now)

            st = screener.stats()
            logger.info(f"stream {len(cands):>3} cands / {st['symbols_tracked']:>4} tracked / "
                        f"{st['bars_seen']:>6} bars | pipeline {len(pipe):>3} | "
                        f"stream-only {len(set(first_stream) - set(first_pipe)):>3} | "
                        f"pipeline-only {len(set(first_pipe) - set(first_stream)):>3}")

            json.dump({
                'date': f'{now:%Y-%m-%d}',
                'params': vars(args),
                'first_stream': {k: v.isoformat() for k, v in first_stream.items()},
                'first_pipeline': {k: v.isoformat() for k, v in first_pipe.items()},
                'peak_change_pct': peak_change,
            }, open(out_path, 'w', encoding='utf-8'), indent=2)
    except KeyboardInterrupt:
        pass
    finally:
        screener.stop()

    both = sorted(set(first_stream) & set(first_pipe),
                  key=lambda s: (first_stream[s] - first_pipe[s]).total_seconds())
    print(f"\n{'='*66}\nRESULTS {out_path}\n{'='*66}")
    print(f"stream found {len(first_stream)}, pipeline found {len(first_pipe)}, both {len(both)}")
    if both:
        deltas = sorted((first_stream[s] - first_pipe[s]).total_seconds() / 60 for s in both)
        print(f"median delta (negative = stream first): {deltas[len(deltas)//2]:+.0f} min\n")
        print(f"{'ticker':<8}{'stream':>10}{'pipeline':>10}{'delta':>9}{'peak%':>9}")
        for s in both:
            d = (first_stream[s] - first_pipe[s]).total_seconds() / 60
            print(f"{s:<8}{first_stream[s]:%H:%M:%S}{first_pipe[s]:%H:%M:%S}"
                  f"{d:>+8.0f}m{peak_change.get(s, 0):>+9.0f}")
    print(f"\nstream-only:   {sorted(set(first_stream) - set(first_pipe))}")
    print(f"pipeline-only: {sorted(set(first_pipe) - set(first_stream))}")


if __name__ == '__main__':
    main()
