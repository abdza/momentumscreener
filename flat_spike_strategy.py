#!/usr/bin/env python3
"""
Flat-then-premarket-spike strategy: pure signal/simulation logic shared by the
historical backtester (flat_spike_backtester.py) and, later, a live paper-trading
daemon. No I/O here - just data-in/data-out functions so both callers stay in sync.

Strategy:
  - Ticker must have been flat over the preceding FLAT_LOOKBACK_DAYS trading days:
    each day's range under FLAT_MAX_DAILY_RANGE_PCT, net drift under
    FLAT_MAX_NET_DRIFT_PCT, AND the average daily range at/above
    FLAT_MIN_AVG_RANGE_PCT - dead-still tickers (near-zero daily movement, e.g.
    SPACs pinned at trust value) backtested worse than ones with some real but
    contained daily movement, so flatness needs a floor as well as a ceiling.
  - A spike must begin at/after SPIKE_EARLIEST_ET (5:00am ET) during premarket - not
    already elevated at the 4:00am premarket open, and not a 9:30 gap.
  - Entry price must be at/above MIN_ENTRY_PRICE - sub-$5 tickers backtested far
    worse (real, volume-backed reversals, not just illiquid noise) than $5+ ones.
  - Average dollar volume per minute in the premarket bars strictly before entry
    must be at/above MIN_PRE_ENTRY_DOLLAR_VOL - a spike made of thin, sparse prints
    isn't backed by real buying interest and tends to snap back immediately.
  - Premarket-only: exit on whichever comes first:
      * price falls back to/below today's premarket low seen so far (stop-loss)
      * price retraces RANGE_DRAWDOWN_PCT of the day's range (peak minus the
        premarket low seen so far) below the post-entry peak, and doesn't
        recover within TRAILING_RECOVERY_MINUTES (range-based trailing stop -
        the retracement is scaled by how wide the day's range has been instead
        of a fixed percentage of price, so a stock that's already run further
        gets more room before triggering)
      * PREMARKET_END_ET (9:20am ET) - force-close before the regular session
        opens, since this strategy only holds during the premarket hour
      * end of regular session (force-close - a backtest-only safety net,
        should be unreachable given the 9:20 cutoff above)
"""

from dataclasses import dataclass
from datetime import datetime, time as dt_time
from typing import List, Optional, Sequence

FLAT_LOOKBACK_DAYS = 5
FLAT_MAX_DAILY_RANGE_PCT = 8.0
FLAT_MAX_NET_DRIFT_PCT = 15.0
FLAT_MIN_AVG_RANGE_PCT = 2.0

SPIKE_MIN_PCT = 15.0
SPIKE_EARLIEST_ET = dt_time(5, 0)
MARKET_OPEN_ET = dt_time(9, 30)
MARKET_CLOSE_ET = dt_time(16, 0)
PREMARKET_END_ET = dt_time(9, 20)
MIN_ENTRY_PRICE = 5.0
MIN_PRE_ENTRY_DOLLAR_VOL = 12000.0

RANGE_DRAWDOWN_PCT = 5.0
TRAILING_RECOVERY_MINUTES = 20

POSITION_SIZE = 100.0
INITIAL_BALANCE = 10000.0


@dataclass
class Bar:
    ts: datetime  # tz-aware, America/New_York
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class DailyBar:
    date: object  # datetime.date
    open: float
    high: float
    low: float
    close: float


@dataclass
class OpenPosition:
    """Mutable state for one simulated trade in progress - shared by the backtest
    replay (simulate_trade) and a live daemon that only sees bars one tick at a
    time, so both apply the exact same exit logic via check_exit()."""
    ticker: str
    entry_price: float
    entry_time: datetime
    shares: float
    position_size: float
    premarket_low_so_far: float
    peak: float
    drawdown_started_at: Optional[datetime] = None


def open_position(ticker: str, entry_bar: Bar, premarket_low_so_far: float,
                   position_size: float = POSITION_SIZE) -> OpenPosition:
    return OpenPosition(
        ticker=ticker,
        entry_price=entry_bar.close,
        entry_time=entry_bar.ts,
        shares=position_size / entry_bar.close,
        position_size=position_size,
        premarket_low_so_far=premarket_low_so_far,
        peak=entry_bar.close,
    )


def is_flat_before(daily_bars: Sequence[DailyBar], spike_date,
                    lookback_days: int = FLAT_LOOKBACK_DAYS,
                    max_daily_range_pct: float = FLAT_MAX_DAILY_RANGE_PCT,
                    max_net_drift_pct: float = FLAT_MAX_NET_DRIFT_PCT,
                    min_avg_range_pct: float = FLAT_MIN_AVG_RANGE_PCT) -> bool:
    """True if the `lookback_days` trading days strictly before spike_date were flat:
    each day's intraday range stayed under max_daily_range_pct, the net drift from
    the oldest to the most recent close in the window stayed under
    max_net_drift_pct, AND the average daily range was at least min_avg_range_pct -
    a dead-still ticker (no real trading, e.g. a SPAC pinned at trust value) is
    excluded just like an overly volatile one is."""
    prior = sorted((b for b in daily_bars if b.date < spike_date), key=lambda b: b.date)
    if len(prior) < lookback_days:
        return False
    window = prior[-lookback_days:]

    daily_range_pcts = []
    for bar in window:
        if bar.close <= 0:
            return False
        daily_range_pct = (bar.high - bar.low) / bar.close * 100
        if daily_range_pct > max_daily_range_pct:
            return False
        daily_range_pcts.append(daily_range_pct)

    if sum(daily_range_pcts) / len(daily_range_pcts) < min_avg_range_pct:
        return False

    first_close = window[0].close
    last_close = window[-1].close
    if first_close <= 0:
        return False
    net_drift_pct = abs(last_close - first_close) / first_close * 100
    if net_drift_pct > max_net_drift_pct:
        return False

    return True


def find_spike_start(premarket_bars_et: Sequence[Bar], baseline_price: float,
                      spike_min_pct: float = SPIKE_MIN_PCT,
                      spike_earliest_et: dt_time = SPIKE_EARLIEST_ET) -> Optional[Bar]:
    """
    Scan premarket bars (sorted ascending, one ET calendar day, ~4:00-9:30) for the
    first bar at/after `spike_earliest_et` whose close is at least `spike_min_pct`
    above baseline_price. Returns None if the ticker was already that far above
    baseline before spike_earliest_et (already spiking at the premarket open -
    disqualified by the "not at the very opening" rule) or if it never reaches the
    threshold.
    """
    if baseline_price <= 0:
        return None
    threshold = baseline_price * (1 + spike_min_pct / 100)

    for bar in premarket_bars_et:
        bar_time = bar.ts.time()
        if bar_time < spike_earliest_et:
            if bar.close >= threshold:
                return None  # already elevated before the earliest allowed spike time
            continue
        if bar.close >= threshold:
            return bar
    return None


def has_sufficient_liquidity(premarket_bars_et: Sequence[Bar], entry_bar: Bar,
                              min_avg_dollar_vol: float = MIN_PRE_ENTRY_DOLLAR_VOL) -> bool:
    """True if the average dollar volume per minute bar strictly before entry_bar
    is at least min_avg_dollar_vol. A spike built on a handful of thin, sparse
    prints (low dollar volume) tends to be a false signal that snaps back
    immediately rather than a real move backed by broad buying interest - this
    was the strongest differentiator found between winning and losing trades in
    a backtest of the strategy. Returns False if there are no bars before entry
    to judge liquidity from."""
    pre = [b for b in premarket_bars_et if b.ts < entry_bar.ts]
    if not pre:
        return False
    avg_dollar_vol = sum(b.volume * b.close for b in pre) / len(pre)
    return avg_dollar_vol >= min_avg_dollar_vol


def check_exit(position: OpenPosition, bar: Bar,
                range_drawdown_pct: float = RANGE_DRAWDOWN_PCT,
                trailing_recovery_minutes: int = TRAILING_RECOVERY_MINUTES,
                market_close_et: dt_time = MARKET_CLOSE_ET,
                premarket_end_et: dt_time = PREMARKET_END_ET):
    """
    Apply one new bar to an open position and report whether it triggers an exit.
    Mutates position.peak/drawdown_started_at in place so it can be called once
    per bar as bars arrive - by a full historical replay (simulate_trade) or by a
    live daemon that only has "now", one tick at a time. Both must call this same
    function so their exit behavior never drifts apart.

    Returns (exit_ts, exit_price, exit_reason) if bar triggers an exit, else None.
    Ignores bars at/before the entry bar (mirrors simulate_trade's original skip).
    """
    if bar.ts <= position.entry_time:
        return None

    if bar.high > position.peak:
        position.peak = bar.high
        position.drawdown_started_at = None  # a fresh peak clears any running recovery clock

    if bar.low <= position.premarket_low_so_far:
        return (bar.ts, position.premarket_low_so_far, 'STOP_PREMARKET_LOW')

    day_range = position.peak - position.premarket_low_so_far
    drawdown_level = position.peak - (range_drawdown_pct / 100) * day_range
    if bar.low <= drawdown_level:
        if position.drawdown_started_at is None:
            position.drawdown_started_at = bar.ts
        elapsed_minutes = (bar.ts - position.drawdown_started_at).total_seconds() / 60
        if elapsed_minutes >= trailing_recovery_minutes:
            return (bar.ts, drawdown_level, 'RANGE_DRAWDOWN_NO_RECOVERY')
    elif position.drawdown_started_at is not None and bar.close >= drawdown_level:
        position.drawdown_started_at = None  # recovered before the timer expired

    if bar.ts.time() >= premarket_end_et:
        return (bar.ts, bar.close, 'PREMARKET_END_FORCE_CLOSE')

    if bar.ts.time() >= market_close_et:
        return (bar.ts, bar.close, 'EOD_FORCE_CLOSE')

    return None


def build_trade_result(position: OpenPosition, exit_ts: datetime, exit_price: float,
                        exit_reason: str) -> dict:
    """Shape a closed position into the trade dict paper_trading_system.py uses,
    so it can be written straight into trade_history.json and read by
    paper_trading_analyzer.py."""
    exit_value = position.shares * exit_price
    profit_loss = exit_value - position.position_size
    profit_pct = (exit_price - position.entry_price) / position.entry_price * 100
    holding_minutes = (exit_ts - position.entry_time).total_seconds() / 60
    return {
        'ticker': position.ticker,
        'entry_price': round(position.entry_price, 4),
        'exit_price': round(exit_price, 4),
        'shares': position.shares,
        'entry_timestamp': position.entry_time.isoformat(),
        'exit_timestamp': exit_ts.isoformat(),
        'holding_time_minutes': round(holding_minutes, 1),
        'position_size': position.position_size,
        'exit_value': round(exit_value, 4),
        'profit_loss': round(profit_loss, 4),
        'profit_pct': round(profit_pct, 4),
        'alert_type': 'flat_spike',
        'exit_reason': exit_reason,
        'peak_price': round(position.peak, 4),
        'premarket_low_at_entry': round(position.premarket_low_so_far, 4),
    }


def replay_to_exit(ticker: str, entry_bar: Bar, premarket_low_so_far: float,
                    bars_from_entry: Sequence[Bar],
                    position_size: float = POSITION_SIZE,
                    range_drawdown_pct: float = RANGE_DRAWDOWN_PCT,
                    trailing_recovery_minutes: int = TRAILING_RECOVERY_MINUTES,
                    market_close_et: dt_time = MARKET_CLOSE_ET,
                    premarket_end_et: dt_time = PREMARKET_END_ET):
    """
    Replay bars_from_entry (ascending, starting at-or-before entry_bar) through
    check_exit(). Unlike simulate_trade, this does NOT force a close just because
    bars ran out - bars_from_entry may only extend to "now" rather than to the end
    of the session, which is exactly the case for a live daemon that hasn't seen
    the rest of the day yet. Returns (position, exit_info), where exit_info is
    None if the position is still open after the given bars.
    """
    position = open_position(ticker, entry_bar, premarket_low_so_far, position_size)
    for bar in bars_from_entry:
        if bar.ts <= position.entry_time:
            continue
        exit_info = check_exit(position, bar, range_drawdown_pct, trailing_recovery_minutes,
                                market_close_et, premarket_end_et)
        if exit_info:
            return position, exit_info
    return position, None


def simulate_trade(ticker: str, entry_bar: Bar, premarket_low_so_far: float,
                    bars_from_entry: Sequence[Bar],
                    position_size: float = POSITION_SIZE,
                    range_drawdown_pct: float = RANGE_DRAWDOWN_PCT,
                    trailing_recovery_minutes: int = TRAILING_RECOVERY_MINUTES,
                    market_close_et: dt_time = MARKET_CLOSE_ET,
                    premarket_end_et: dt_time = PREMARKET_END_ET) -> dict:
    """
    Replay bars from entry onward (bars_from_entry must be sorted ascending and
    start at-or-after entry_bar, continuing through the regular session so a trade
    still open at 9:30 keeps simulating) and apply the exit rules. Unlike
    replay_to_exit, a backtest always has the full day available, so if no rule
    fires the position is force-closed at the last bar. Returns a trade dict
    shaped like paper_trading_system.py's trade-history schema so it can be
    written straight into trade_history.json and read by paper_trading_analyzer.py.
    """
    position, exit_info = replay_to_exit(ticker, entry_bar, premarket_low_so_far, bars_from_entry,
                                          position_size, range_drawdown_pct,
                                          trailing_recovery_minutes, market_close_et,
                                          premarket_end_et)
    if exit_info is None:
        last_bar = max(bars_from_entry, key=lambda b: b.ts, default=entry_bar)
        exit_info = (last_bar.ts, last_bar.close, 'EOD_FORCE_CLOSE')
    return build_trade_result(position, *exit_info)
