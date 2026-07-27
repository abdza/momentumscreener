#!/usr/bin/env python3
"""
Real-time candidate discovery from Alpaca's wildcard minute-bar stream.

Built to replace the candidate-discovery half of premarket_top20_monitor.py's
merge, which currently has two delayed sources and no live one:

  - the TradingView scanner serves this account delayed_streaming_900 data, so a
    ticker only enters its volume/change rankings ~15 minutes after it moves;
  - Alpaca's ScreenerClient (get_market_movers / get_most_actives) is an
    end-of-day snapshot, not a live feed - at 06:17 ET on 2026-07-27 both
    endpoints reported last_updated=2026-07-24 23:59 UTC, i.e. the previous
    Friday's close. Its "gainers" during premarket are the prior session's.

This subscribes to bars("*") on the SIP feed - every US equity, delivered at
minute close - and keeps a rolling per-symbol table in memory. Ranking is then
computed locally from that table, so discovery never waits on a third party's
refresh cycle and the criteria are ours rather than theirs.

Previous closes (needed for premarket % change) come from the snapshots endpoint,
fetched lazily in batches for symbols that clear a cheap activity pre-filter and
cached for the session - fetching all ~11k tradable symbols up front would be
mostly waste, since only a few hundred print in any premarket minute.

Note: Alpaca permits one concurrent market-data websocket per account, so exactly
one process may hold this stream. Run it inside the monitor, or as a standalone
service the monitor reads from - not both.

Usage:
    from alpaca_stream_screener import StreamScreener
    s = StreamScreener(); s.start()
    ...
    for c in s.candidates(min_change_pct=5.0):
        print(c['symbol'], c['change_pct'], c['dollar_volume'])
    s.stop()

Standalone smoke test (prints the live leaderboard once a minute):
    python alpaca_stream_screener.py --minutes 5
"""

import argparse
import asyncio
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta

import pytz

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live.stock import StockDataStream
from alpaca.data.requests import StockSnapshotRequest

logger = logging.getLogger(__name__)

ET_TZ = pytz.timezone('America/New_York')

# Rolling window of recent minute bars kept per symbol, sized for the 10-minute
# candle-spike rule plus its 6-bucket baseline (see premarket_top20_monitor.py).
BAR_HISTORY_MINUTES = 90

# Symbols below this cumulative dollar volume are not worth a previous-close
# lookup - they are noise prints, not candidates.
PREVCLOSE_MIN_DOLLAR_VOL = 25_000.0
PREVCLOSE_BATCH = 200

# Drop symbols that have gone quiet, so the table does not grow all session.
STALE_AFTER_MINUTES = 120


class SymbolState:
    __slots__ = ('symbol', 'first_ts', 'first_open', 'high', 'low', 'last_price',
                 'last_ts', 'volume', 'dollar_volume', 'bars')

    def __init__(self, symbol, bar):
        self.symbol = symbol
        self.first_ts = bar.timestamp
        self.first_open = float(bar.open)
        self.high = float(bar.high)
        self.low = float(bar.low)
        self.last_price = float(bar.close)
        self.last_ts = bar.timestamp
        self.volume = float(bar.volume or 0)
        self.dollar_volume = float(bar.volume or 0) * float(bar.close)
        self.bars = deque(maxlen=BAR_HISTORY_MINUTES)
        self.bars.append(bar)

    def update(self, bar):
        px = float(bar.close)
        self.high = max(self.high, float(bar.high))
        self.low = min(self.low, float(bar.low))
        self.last_price = px
        self.last_ts = bar.timestamp
        self.volume += float(bar.volume or 0)
        self.dollar_volume += float(bar.volume or 0) * px
        self.bars.append(bar)


class StreamScreener:
    """Holds the wildcard bar subscription and answers candidate queries from it."""

    def __init__(self, api_key=None, api_secret=None, feed=DataFeed.SIP):
        self.api_key = api_key or os.environ.get('APCA_API_KEY_ID')
        self.api_secret = api_secret or os.environ.get('APCA_API_SECRET_KEY')
        if not self.api_key or not self.api_secret:
            raise RuntimeError("Alpaca API keys not found - set APCA_API_KEY_ID / "
                               "APCA_API_SECRET_KEY (e.g. `source secrets.env`)")
        self.feed = feed
        self._state = {}
        self._lock = threading.Lock()
        self._prev_close = {}        # symbol -> float, session cache
        self._prevclose_missing = set()
        self._rest = StockHistoricalDataClient(self.api_key, self.api_secret)
        self._stream = None
        self._thread = None
        self._running = False
        self.started_at = None
        self.bars_seen = 0

    # ------------------------------------------------------------------ stream

    async def _on_bar(self, bar):
        with self._lock:
            self.bars_seen += 1
            st = self._state.get(bar.symbol)
            if st is None:
                self._state[bar.symbol] = SymbolState(bar.symbol, bar)
            else:
                st.update(bar)

    def _run(self):
        # Each thread needs its own loop; the stream binds to whichever is current.
        asyncio.set_event_loop(asyncio.new_event_loop())
        while self._running:
            try:
                self._stream = StockDataStream(self.api_key, self.api_secret, feed=self.feed)
                self._stream.subscribe_bars(self._on_bar, "*")
                self._stream.run()
            except Exception as e:
                if self._running:
                    logger.warning(f"⚠️  bar stream dropped ({e}); reconnecting in 5s")
                    time.sleep(5)

    def start(self):
        if self._running:
            return
        self._running = True
        self.started_at = datetime.now(ET_TZ)
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name='alpaca-bar-stream')
        self._thread.start()
        logger.info("📡 wildcard bar stream started (SIP, all US equities)")

    def stop(self):
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception:
                pass
        logger.info("📡 bar stream stopped")

    # -------------------------------------------------------------- prev close

    def _ensure_prev_closes(self, symbols):
        """Batch-fetch and cache previous daily closes for symbols we don't have."""
        want = [s for s in symbols
                if s not in self._prev_close and s not in self._prevclose_missing]
        for i in range(0, len(want), PREVCLOSE_BATCH):
            chunk = want[i:i + PREVCLOSE_BATCH]
            try:
                snaps = self._rest.get_stock_snapshot(
                    StockSnapshotRequest(symbol_or_symbols=chunk, feed=self.feed))
            except Exception as e:
                logger.warning(f"⚠️  snapshot fetch failed for {len(chunk)} symbols: {e}")
                continue
            for sym in chunk:
                snap = (snaps or {}).get(sym)
                pdb = getattr(snap, 'previous_daily_bar', None) if snap else None
                if pdb and pdb.close:
                    self._prev_close[sym] = float(pdb.close)
                else:
                    self._prevclose_missing.add(sym)

    # -------------------------------------------------------------- candidates

    def _prune(self, now):
        cutoff = now - timedelta(minutes=STALE_AFTER_MINUTES)
        for sym in [s for s, st in self._state.items() if st.last_ts < cutoff]:
            del self._state[sym]

    def candidates(self, min_change_pct=5.0, min_dollar_volume=PREVCLOSE_MIN_DOLLAR_VOL,
                   spike_bucket_minutes=10, spike_ratio_threshold=3.0):
        """Current candidate list, computed from the in-memory bar table.

        Returns dicts sorted by change_pct desc, each with the symbol, live price,
        % change vs previous close, session high/low seen on the stream, cumulative
        volume, and a candle-spike ratio (latest bucket's range vs the average of
        prior buckets) mirroring premarket_top20_monitor._detect_candle_spikes.
        """
        now = datetime.now(pytz.UTC)
        with self._lock:
            self._prune(now)
            snap = [(st.symbol, st.last_price, st.high, st.low, st.volume,
                     st.dollar_volume, st.last_ts, list(st.bars))
                    for st in self._state.values()
                    if st.dollar_volume >= min_dollar_volume]

        self._ensure_prev_closes([s[0] for s in snap])

        out = []
        for sym, px, hi, lo, vol, dvol, last_ts, bars in snap:
            prev = self._prev_close.get(sym)
            if not prev:
                continue
            change_pct = (px - prev) / prev * 100
            if change_pct < min_change_pct:
                continue
            out.append({
                'symbol': sym,
                'price': px,
                'previous_close': prev,
                'change_pct': change_pct,
                'high': hi,
                'low': lo,
                'volume': vol,
                'dollar_volume': dvol,
                'last_bar_ts': last_ts,
                'candle_spike_ratio': self._spike_ratio(bars, spike_bucket_minutes),
            })
        out.sort(key=lambda r: -r['change_pct'])
        for r in out:
            r['candle_spike'] = (r['candle_spike_ratio'] or 0) >= spike_ratio_threshold
        return out

    @staticmethod
    def _spike_ratio(bars, bucket_minutes):
        """Latest bucket's high-low range over the mean range of prior buckets."""
        if len(bars) < bucket_minutes * 2:
            return None
        buckets = []
        for i in range(len(bars), 0, -bucket_minutes):
            chunk = bars[max(0, i - bucket_minutes):i]
            if len(chunk) < 3:
                continue
            buckets.append(max(float(b.high) for b in chunk) -
                           min(float(b.low) for b in chunk))
            if len(buckets) > 7:
                break
        if len(buckets) < 3:
            return None
        latest, baseline = buckets[0], buckets[1:]
        avg = sum(baseline) / len(baseline)
        return latest / avg if avg > 0 else None

    def stats(self):
        with self._lock:
            return {'symbols_tracked': len(self._state), 'bars_seen': self.bars_seen,
                    'prev_closes_cached': len(self._prev_close),
                    'started_at': self.started_at}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--minutes', type=float, default=5)
    ap.add_argument('--min-change', type=float, default=5.0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    s = StreamScreener()
    s.start()
    deadline = time.time() + args.minutes * 60
    try:
        while time.time() < deadline:
            time.sleep(60)
            cands = s.candidates(min_change_pct=args.min_change)
            st = s.stats()
            print(f"\n[{datetime.now(ET_TZ):%H:%M:%S} ET] tracking {st['symbols_tracked']} symbols, "
                  f"{st['bars_seen']} bars -> {len(cands)} candidates >= {args.min_change}%")
            for c in cands[:15]:
                spike = ' 🕯️' if c['candle_spike'] else ''
                print(f"   {c['symbol']:<7}{c['change_pct']:>+8.1f}%  ${c['price']:>8.2f}  "
                      f"vol {c['volume']:>11,.0f}  ${c['dollar_volume']/1e6:>7.2f}M{spike}")
    except KeyboardInterrupt:
        pass
    finally:
        s.stop()


if __name__ == '__main__':
    main()
