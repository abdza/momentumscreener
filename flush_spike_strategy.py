#!/usr/bin/env python3
"""
Flush-then-reload strategy: pure signal/simulation logic shared by
flush_spike_backtester.py and flush_spike_live_trader.py. No I/O here - just
data-in/data-out functions so both callers stay in sync.

Sibling to flat_spike_strategy.py, but for a different premarket shape: instead of
a calm stock spiking once from a quiet baseline, this looks for a violent
peak -> flush -> reload cycle that can happen anytime in premarket, including
right at the 4:00am open (which permanently disqualifies a ticker under
flat_spike's find_spike_start, since that only ever compares against the fixed
previous-close baseline). A single ticker can produce several flush/reload legs
in one session, so - unlike flat_spike - this strategy supports multiple trades
per ticker per day; callers should re-run find_flush_reload_start on the bars
remaining after each simulated/live exit rather than treating one entry as the
day's final word on a ticker.

Strategy:
  - Track the running premarket peak (highest high seen so far). Any bar whose
    high exceeds it becomes the new peak and invalidates whatever flush leg was
    being tracked - the pattern only cares about drops from the *current* high.
  - A "flush" is recorded once some bar's low sits at least FLUSH_MIN_DROP_PCT
    below the running peak; the lowest low seen while still below that peak
    becomes flush_low.
  - A "reload" entry fires on the first subsequent bar whose close is at/above
    max(flush_low * (1 + RELOAD_MIN_PCT / 100), MIN_ENTRY_PRICE) - the price
    floor is applied via max() rather than as a separate reject, because a
    flush low of $1-2 reloading 30% is still under $5 and shouldn't trigger
    until the price is actually at a tradeable level.
  - MIN_ENTRY_PRICE is deliberately lower than flat_spike's $5: backtesting
    flat_spike showed sub-$5 entries underperformed, but this pattern's
    reload leg often starts from a flush low of $1-3, and gating entry at $5
    here means buying only after the real peak has typically already passed
    (validated against a real trade: entering at $5 landed 5 minutes after the
    peak for a -12.7% loss, while a $2 floor caught the reload for +113.9%).
  - Liquidity and exit rules are unchanged from flat_spike - reused directly
    from flat_spike_strategy rather than redefined here.
"""

from flat_spike_strategy import (  # noqa: F401 - re-exported for callers
    Bar,
    OpenPosition,
    open_position,
    check_exit,
    build_trade_result,
    replay_to_exit,
    simulate_trade,
    has_sufficient_liquidity,
    MIN_PRE_ENTRY_DOLLAR_VOL,
    MARKET_OPEN_ET,
    MARKET_CLOSE_ET,
    PREMARKET_END_ET,
    RANGE_DRAWDOWN_PCT,
    TRAILING_RECOVERY_MINUTES,
    POSITION_SIZE,
    INITIAL_BALANCE,
)

from typing import Optional, Sequence

FLUSH_MIN_DROP_PCT = 20.0
RELOAD_MIN_PCT = 30.0
MIN_ENTRY_PRICE = 2.0
MAX_ENTRY_PRICE = 20.0


def find_flush_reload_start(bars_asc: Sequence[Bar],
                             flush_min_drop_pct: float = FLUSH_MIN_DROP_PCT,
                             reload_min_pct: float = RELOAD_MIN_PCT,
                             min_entry_price: float = MIN_ENTRY_PRICE) -> Optional[Bar]:
    """
    Scan bars_asc (sorted ascending) for the first flush-then-reload entry: a
    running peak, a subsequent low at least flush_min_drop_pct below that peak
    (the flush), then the first later bar whose close reloads at least
    reload_min_pct off that flush low - and is also at/above min_entry_price,
    whichever threshold is higher. Returns None if no such cycle completes in
    bars_asc.

    Checks the entry condition against the flush_low established by *prior*
    bars before updating peak/flush state with the current bar, so the exact
    bottom tick can't both define the flush and trigger its own entry - a
    genuine bounce is required first.
    """
    if not bars_asc:
        return None

    peak = None
    flush_low = None

    for bar in bars_asc:
        if flush_low is not None:
            threshold = max(flush_low * (1 + reload_min_pct / 100), min_entry_price)
            if bar.close >= threshold:
                return bar

        if peak is None or bar.high > peak:
            peak = bar.high
            flush_low = None  # a fresh high invalidates whatever flush leg was tracked
            continue

        if flush_low is None or bar.low < flush_low:
            drop_pct = (peak - bar.low) / peak * 100
            if drop_pct >= flush_min_drop_pct:
                flush_low = bar.low

    return None
