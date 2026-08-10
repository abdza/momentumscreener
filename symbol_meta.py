#!/usr/bin/env python3
"""
Symbol -> {sector, exchange} lookup for the post-TradingView trackers.

Alpaca's market data carries no sector classification; TradingView's scanner
used to supply it. Months of snapshot files (pretop20/screener_*.json and
momentum_data/raw_data_*.json) already hold that metadata for every symbol the
screeners ever surfaced, so it is harvested into symbol_meta.json once and
looked up at runtime. Symbols never seen before simply get blank metadata -
the dashboards render '' sectors fine.

Rebuild (also merges newly seen symbols into the existing map):
    python symbol_meta.py
"""

import glob
import json
import logging
import os

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
META_FILE = os.path.join(BASE_DIR, 'symbol_meta.json')
SNAPSHOT_GLOBS = [
    os.path.join(BASE_DIR, 'pretop20', 'screener_*.json'),
    os.path.join(BASE_DIR, 'momentum_data', 'raw_data_*.json'),
]

_cache = None


def load_symbol_meta():
    """The symbol -> {'sector','exchange'} map; {} when the file is absent."""
    global _cache
    if _cache is None:
        try:
            with open(META_FILE) as f:
                _cache = json.load(f)
        except FileNotFoundError:
            logger.warning(f"⚠️  {META_FILE} not found - sectors will be blank "
                           "(run: python symbol_meta.py)")
            _cache = {}
        except Exception as e:
            logger.warning(f"⚠️  could not load {META_FILE}: {e}")
            _cache = {}
    return _cache


def lookup(symbol):
    meta = load_symbol_meta().get(symbol, {})
    return meta.get('sector', ''), meta.get('exchange', '')


def build():
    """Harvest sector/exchange from every historical snapshot into META_FILE."""
    meta = {}
    if os.path.exists(META_FILE):
        with open(META_FILE) as f:
            meta = json.load(f)

    files = []
    for pattern in SNAPSHOT_GLOBS:
        files.extend(glob.glob(pattern))
    print(f"Scanning {len(files)} snapshot files...")

    for path in sorted(files):  # newest last, so recent metadata wins
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
            if not isinstance(r, dict):
                continue
            name = r.get('name')
            sector = r.get('sector') or ''
            exchange = r.get('exchange') or ''
            if name and (sector or exchange):
                meta[name] = {'sector': sector, 'exchange': exchange}

    with open(META_FILE, 'w') as f:
        json.dump(meta, f, indent=0, sort_keys=True)
    print(f"Wrote {len(meta)} symbols to {META_FILE}")


if __name__ == '__main__':
    build()
