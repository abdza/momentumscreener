#!/usr/bin/env python3
"""
Symbol -> free float lookup for the post-TradingView trackers.

TradingView's scanner used to supply float_shares_outstanding; since the
trackers moved to Alpaca the field has been written as None, and Alpaca has no
fundamentals endpoint to replace it. Float is harvested into float_shares.json
instead and looked up at runtime, the same shape symbol_meta.py uses for
sector/exchange.

Two sources, in precedence order:

  yfinance   - live 'floatShares', falling back to 'sharesOutstanding' when the
               float itself is unpublished (common for recent listings). Fetched
               in a background thread so a scan loop never blocks on the network.
  snapshot   - float_shares_outstanding harvested from the historical
               pretop20/screener_*.json and momentum_data/raw_data_*.json files
               written while TradingView was still the source. Stale by months,
               but these are ranked in order-of-magnitude buckets, so a stale
               float beats no float.

Float moves with every offering and these are diluting microcaps, so entries
carry a fetch date and are refreshed once they pass MAX_AGE_DAYS.

    python float_shares.py            # seed from snapshots, then refresh stale
    python float_shares.py --seed     # snapshots only, no network
    python float_shares.py --all      # force-refresh every known symbol
"""

import argparse
import glob
import json
import logging
import math
import os
import queue
import threading
import time
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FLOAT_FILE = os.path.join(BASE_DIR, 'float_shares.json')
SNAPSHOT_GLOBS = [
    os.path.join(BASE_DIR, 'pretop20', 'screener_*.json'),
    os.path.join(BASE_DIR, 'momentum_data', 'raw_data_*.json'),
]

MAX_AGE_DAYS = 7          # refetch a symbol's float once its entry is older
FETCH_INTERVAL = 0.5      # seconds between yfinance calls, background and CLI
SAVE_INTERVAL = 30        # seconds between background cache flushes
QUEUE_LIMIT = 2000        # bound the backlog on a very busy morning

_cache = None
_lock = threading.Lock()
_queue = None
_worker = None
_queued = set()


# ---------------------------------------------------------------- cache file

def _load():
    """The symbol -> entry map; {} when the file is absent."""
    global _cache
    with _lock:
        if _cache is None:
            try:
                with open(FLOAT_FILE) as f:
                    _cache = json.load(f)
            except FileNotFoundError:
                logger.warning(f"⚠️  {FLOAT_FILE} not found - floats will be blank "
                               "(run: python float_shares.py)")
                _cache = {}
            except Exception as e:
                logger.warning(f"⚠️  could not load {FLOAT_FILE}: {e}")
                _cache = {}
        return _cache


def _save():
    """Write the cache out atomically so a crashed scan can't truncate it."""
    with _lock:
        if _cache is None:
            return
        snapshot = dict(_cache)
    tmp = FLOAT_FILE + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(snapshot, f, indent=0, sort_keys=True)
        os.replace(tmp, FLOAT_FILE)
    except Exception as e:
        logger.warning(f"⚠️  could not write {FLOAT_FILE}: {e}")


def _stale(entry):
    if not entry:
        return True
    try:
        fetched = datetime.strptime(entry.get('ts', ''), '%Y-%m-%d').date()
    except ValueError:
        return True
    return (date.today() - fetched) > timedelta(days=MAX_AGE_DAYS)


# ------------------------------------------------------------------- lookup

def lookup(symbol):
    """Free float for `symbol`, or None when it isn't known yet.

    Cache-only and non-blocking: a missing or stale symbol is queued for the
    background refresher and None comes back for this scan. Callers get a real
    number from the next scan onward.
    """
    if not symbol:
        return None
    entry = _load().get(symbol)
    if _stale(entry):
        _enqueue(symbol)
    if not entry:
        return None
    value = entry.get('float')
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return value if value > 0 else None


def annotate(records, key='float_shares_outstanding', name_key='name'):
    """Stamp `key` onto every record that hasn't already got a usable value.

    Records arriving from a source that still carries its own float keep it;
    everything else picks the cache up. Returns `records` for chaining.
    """
    if not records:
        return records
    for record in records:
        if not isinstance(record, dict):
            continue
        current = record.get(key)
        if isinstance(current, (int, float)) and not (
                isinstance(current, float) and math.isnan(current)) and current > 0:
            continue
        record[key] = lookup(record.get(name_key))
    return records


# ------------------------------------------------------------ yfinance fetch

def fetch(symbol):
    """One yfinance lookup -> entry dict, or None when the symbol has neither
    a published float nor a share count."""
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).get_info() or {}
    except Exception as e:
        logger.debug(f"float fetch failed for {symbol}: {e}")
        return None

    def num(value):
        if isinstance(value, (int, float)) and not (
                isinstance(value, float) and math.isnan(value)) and value > 0:
            return int(value)
        return None

    shares = num(info.get('sharesOutstanding'))
    free = num(info.get('floatShares'))
    if free is None and shares is None:
        return None
    return {
        'float': free if free is not None else shares,
        'shares': shares,
        # Flagged so consumers can tell a true free float from a share count
        # standing in for one - the two diverge a lot on insider-heavy names.
        'src': 'yfinance' if free is not None else 'yfinance_shares',
        'ts': date.today().isoformat(),
    }


def _store(symbol, entry):
    if not entry:
        return
    _load()
    with _lock:
        _cache[symbol] = entry


# ------------------------------------------------------- background refresher

def _enqueue(symbol):
    if not symbol or not symbol.isalpha():
        return
    _ensure_worker()
    with _lock:
        if symbol in _queued or _queue.qsize() >= QUEUE_LIMIT:
            return
        _queued.add(symbol)
    try:
        _queue.put_nowait(symbol)
    except queue.Full:
        with _lock:
            _queued.discard(symbol)


def _ensure_worker():
    global _queue, _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        if _queue is None:
            _queue = queue.Queue(maxsize=QUEUE_LIMIT)
        _worker = threading.Thread(target=_run_worker, name='float-refresh',
                                   daemon=True)
        _worker.start()


def _run_worker():
    """Drain the queue slowly, flushing the cache on a timer.

    Daemon thread: a scan that exits mid-refresh loses at most the symbols
    fetched since the last flush, and those are simply re-queued next run.
    """
    last_save = time.monotonic()
    while True:
        try:
            symbol = _queue.get(timeout=60)
        except queue.Empty:
            if time.monotonic() - last_save > SAVE_INTERVAL:
                _save()
                last_save = time.monotonic()
            continue
        try:
            entry = fetch(symbol)
            if entry:
                _store(symbol, entry)
            else:
                # Remember the miss too, so an unlisted symbol isn't refetched
                # on every single scan for the next week.
                _store(symbol, {'float': None, 'shares': None,
                                'src': 'unavailable', 'ts': date.today().isoformat()})
        except Exception as e:
            logger.debug(f"float refresh failed for {symbol}: {e}")
        finally:
            with _lock:
                _queued.discard(symbol)
            _queue.task_done()
        if time.monotonic() - last_save > SAVE_INTERVAL:
            _save()
            last_save = time.monotonic()
        time.sleep(FETCH_INTERVAL)


# ------------------------------------------------------------------ CLI build

def seed_from_snapshots():
    """Harvest TradingView-era floats out of the archived snapshot files.

    Only fills symbols the cache doesn't already hold - a live yfinance entry
    always beats a months-old snapshot value.
    """
    cache = _load()
    files = []
    for pattern in SNAPSHOT_GLOBS:
        files.extend(glob.glob(pattern))
    print(f"Scanning {len(files)} snapshot files for historical floats...")

    harvested = {}
    for path in sorted(files):  # newest last, so the freshest float wins
        try:
            with open(path) as f:
                raw = f.read().replace('NaN', 'null').replace('Infinity', 'null')
            snap = json.loads(raw)
        except Exception:
            continue
        records = snap.get('data', snap) if isinstance(snap, dict) else snap
        if not isinstance(records, list):
            continue
        stamp = os.path.basename(path).split('_')[-2]  # YYYYMMDD
        for r in records:
            if not isinstance(r, dict):
                continue
            name = r.get('name')
            value = r.get('float_shares_outstanding')
            if not name or not isinstance(value, (int, float)) or value <= 0:
                continue
            if isinstance(value, float) and math.isnan(value):
                continue
            try:
                ts = datetime.strptime(stamp, '%Y%m%d').date().isoformat()
            except ValueError:
                ts = '1970-01-01'
            harvested[name] = {'float': int(value), 'shares': None,
                               'src': 'snapshot', 'ts': ts}

    added = 0
    with _lock:
        for name, entry in harvested.items():
            if name not in cache:
                cache[name] = entry
                added += 1
    _save()
    print(f"Seeded {added} symbols from snapshots ({len(harvested)} found, "
          f"{len(harvested) - added} already cached)")


def refresh(symbols=None, force=False):
    """Fetch floats synchronously, for the CLI. Skips fresh entries unless
    `force`."""
    cache = _load()
    if symbols is None:
        symbols = sorted(cache)
    todo = [s for s in symbols if force or _stale(cache.get(s))]
    print(f"Refreshing {len(todo)} of {len(symbols)} symbols via yfinance "
          f"(~{len(todo) * FETCH_INTERVAL / 60:.0f} min)...")

    ok = miss = 0
    for i, symbol in enumerate(todo, 1):
        entry = fetch(symbol)
        if entry:
            _store(symbol, entry)
            ok += 1
        else:
            _store(symbol, {'float': None, 'shares': None,
                            'src': 'unavailable', 'ts': date.today().isoformat()})
            miss += 1
        if i % 50 == 0:
            _save()
            print(f"  {i}/{len(todo)}  ok={ok} unavailable={miss}")
        time.sleep(FETCH_INTERVAL)
    _save()
    print(f"Done: {ok} resolved, {miss} unavailable, {len(cache)} symbols cached")


def recent_symbols(days=30, per_day=6):
    """Symbols seen in the snapshot files over the last `days` days - the set
    worth keeping warm, rather than every symbol ever screened.

    Samples `per_day` snapshots per file-prefix per day rather than parsing all
    of them: a day holds ~300 premarket and ~190 market snapshots whose symbol
    lists overlap almost entirely, and parsing every one costs minutes on a Pi
    for a handful of extra symbols.
    """
    cutoff = (date.today() - timedelta(days=days)).strftime('%Y%m%d')
    sampled = []
    for pattern in SNAPSHOT_GLOBS:
        by_day = {}
        for path in glob.glob(pattern):
            stamp = os.path.basename(path).split('_')[-2]
            if stamp >= cutoff:
                by_day.setdefault(stamp, []).append(path)
        for stamp, paths in by_day.items():
            paths.sort()
            if len(paths) <= per_day:
                sampled.extend(paths)
            else:
                step = len(paths) / per_day
                sampled.extend(paths[int(i * step)] for i in range(per_day))

    symbols = set()
    for path in sampled:
        try:
            with open(path) as f:
                raw = f.read().replace('NaN', 'null').replace('Infinity', 'null')
            snap = json.loads(raw)
        except Exception:
            continue
        records = snap.get('data', snap) if isinstance(snap, dict) else snap
        if not isinstance(records, list):
            continue
        for r in records:
            if isinstance(r, dict) and r.get('name'):
                symbols.add(r['name'])
    return sorted(symbols)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--seed', action='store_true',
                    help='harvest historical floats from snapshots, no network')
    ap.add_argument('--all', action='store_true',
                    help='refresh every cached symbol, not just recently seen ones')
    ap.add_argument('--force', action='store_true',
                    help='refetch even entries that are still fresh')
    ap.add_argument('--days', type=int, default=30,
                    help='how far back to look for active symbols (default 30)')
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(message)s')
    # The seed walks every snapshot ever written, so it is a one-off: run it
    # when asked, or when there is no cache yet to refresh.
    if args.seed or not _load():
        seed_from_snapshots()
    if args.seed:
        return
    symbols = None if args.all else recent_symbols(args.days)
    if symbols is not None:
        print(f"{len(symbols)} symbols seen in the last {args.days} days")
    refresh(symbols, force=args.force)


if __name__ == '__main__':
    main()
