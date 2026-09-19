#!/usr/bin/env python3
"""
Latest NBBO bid/ask capture for the screener collectors.

Both the premarket monitor and the market-session tracker already batch a
latest-trade call per scan cycle; these helpers add a latest-quote call to the
same batch so the bid/ask is sampled at the same instant as the price that goes
into the snapshot. Pure functions, no I/O state - the callers own their caches.

Why this exists: every backtest run off the snapshots so far has been gross of
spread, and on sub-$20 premarket names the spread is the same order of magnitude
as the edge being measured. Recording the quote alongside the trade is what makes
those backtests answerable.

Fields written onto a record (all optional - absent when the venue had no quote):
    bid, ask                  best bid/ask price at sample time
    bid_size, ask_size        displayed size, in round lots as Alpaca reports it
    mid                       (bid + ask) / 2
    spread                    ask - bid, in dollars
    spread_pct                spread as a percentage of mid
    quote_at                  ISO-8601 timestamp of the quote itself, in ET
"""

import logging

logger = logging.getLogger(__name__)

try:
    from alpaca.data.requests import StockLatestQuoteRequest
    from alpaca.data.enums import DataFeed
    QUOTES_AVAILABLE = True
except ImportError:
    QUOTES_AVAILABLE = False

# A quote wider than this is a placeholder, not a market - one side parked at a
# token price while the book is empty. Recording it as a real spread would poison
# any cost model built on these snapshots, so it is kept as bid/ask but denied a
# spread_pct. Premarket books on thin names legitimately reach 10-15%.
MAX_PLAUSIBLE_SPREAD_PCT = 50.0

QUOTE_KEYS = ('bid', 'ask', 'bid_size', 'ask_size', 'mid',
              'spread', 'spread_pct', 'quote_at')


def fetch_latest_quotes(client, symbols, feed=None, et_tz=None):
    """
    Fetch the latest NBBO quote for each symbol in one batched call.

    Returns {symbol: quote_fields_dict}. Symbols the feed has no quote for are
    simply absent. Never raises: a quote failure must not cost the caller its
    price update, so errors are logged and an empty dict comes back.

    Args:
        client: an alpaca StockHistoricalDataClient
        symbols: list of plain symbols (the caller's existing batch - Alpaca
                 rejects the whole request on TV-style class symbols like DCOM/P,
                 so the caller's .isalpha() filter must already have run)
        feed: DataFeed to use; defaults to SIP to match the price calls
        et_tz: tzinfo to stamp quote_at in; pass the caller's ET_TZ so the field
               matches the snapshot's own 'timestamp'. Defaults to whatever the
               API returned (UTC), which still carries an explicit offset.
    """
    if not QUOTES_AVAILABLE or not client or not symbols:
        return {}

    try:
        request = StockLatestQuoteRequest(
            symbol_or_symbols=list(symbols),
            feed=feed if feed is not None else DataFeed.SIP,
        )
        latest = client.get_stock_latest_quote(request)
    except Exception as e:
        logger.warning(f"Quote fetch failed for {len(symbols)} symbols: {e}")
        return {}

    out = {}
    for symbol in symbols:
        quote = latest.get(symbol) if hasattr(latest, 'get') else None
        if quote is None:
            continue
        fields = quote_fields(quote, et_tz=et_tz)
        if fields:
            out[symbol] = fields
    return out


def quote_fields(quote, et_tz=None):
    """
    Flatten one Alpaca Quote into the record fields, computing spread metrics.

    A one-sided or crossed book (bid >= ask, or either side at zero) keeps its raw
    bid/ask but gets no mid/spread - those would be fiction, and a None reads
    correctly in analysis where a 0.0 would silently average in.
    """
    if quote is None:
        return None

    try:
        bid = float(quote.bid_price) if quote.bid_price is not None else None
        ask = float(quote.ask_price) if quote.ask_price is not None else None
    except (TypeError, ValueError):
        return None

    fields = {
        'bid': bid,
        'ask': ask,
        'bid_size': int(quote.bid_size) if quote.bid_size is not None else None,
        'ask_size': int(quote.ask_size) if quote.ask_size is not None else None,
        'mid': None,
        'spread': None,
        'spread_pct': None,
        'quote_at': None,
    }

    ts = getattr(quote, 'timestamp', None)
    if ts is not None:
        try:
            fields['quote_at'] = (ts.astimezone(et_tz) if et_tz else ts).isoformat()
        except (AttributeError, ValueError):
            pass

    if bid and ask and bid > 0 and ask > 0 and ask >= bid:
        mid = (bid + ask) / 2
        spread = ask - bid
        fields['mid'] = mid
        fields['spread'] = spread
        if mid > 0:
            pct = (spread / mid) * 100
            if pct <= MAX_PLAUSIBLE_SPREAD_PCT:
                fields['spread_pct'] = pct

    return fields


def apply_quote(record, fields):
    """Copy quote fields onto a record, skipping the ones the venue didn't give."""
    if not fields:
        return False
    wrote = False
    for key in QUOTE_KEYS:
        value = fields.get(key)
        if value is not None:
            record[key] = value
            wrote = True
    return wrote
