#!/usr/bin/env python3
"""
Latest-news annotation for screener candidates, backed by Alpaca's News API.

Both trackers (premarket_top20_monitor.py and volume_momentum_tracker.py) call
NewsAnnotator.annotate() on the records they are about to snapshot to disk. Each
record whose symbol has a company-specific article within the backfill window
(see NEWS_MAX_SYMBOLS_PER_ARTICLE) gains:

    news_headline    headline of the symbol's most recent article
    news_source      e.g. "benzinga"
    news_url         article link (may be empty)
    news_created_at  publish time, tz-aware UTC ISO string
    news_at_et       publish time as a *naive* ET wall-clock string
                     ('YYYY-MM-DDTHH:MM:SS'), matching the convention the
                     dashboards already use for snapshot timestamps so the
                     browser can subtract the two directly

The dashboards use news_at_et to compute a decaying priority boost: a ticker
with a just-published article is ranked (and charted) above everything else,
sliding back to its volume-based position as the article ages.

All fields are stable per article on purpose - server.py drops consecutive
snapshots whose data compares equal, so nothing time-relative (e.g. a
"minutes ago" float) may be written into the records.

Fetch strategy: symbols seen for the first time get a 24h backfill query;
already-covered symbols are re-checked in one incremental sweep at most every
NEWS_REFRESH_SECONDS. Requests are batched 50 symbols at a time, so a scan
cycle normally costs zero or one News API call.

Degrades to a no-op when alpaca-py or the APCA_API_KEY_ID/APCA_API_SECRET_KEY
environment variables are missing.
"""

import logging
import os
from datetime import datetime, timedelta

import pytz

try:
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest
    NEWS_CLIENT_AVAILABLE = True
except ImportError:
    NEWS_CLIENT_AVAILABLE = False

logger = logging.getLogger(__name__)

ET_TZ = pytz.timezone('America/New_York')

NEWS_REFRESH_SECONDS = 120      # min gap between incremental sweeps
NEWS_BACKFILL_HOURS = 24        # how far back a symbol's first lookup reaches
NEWS_SYMBOL_BATCH = 50          # symbols per News API request
NEWS_ARTICLES_PER_BATCH = 50    # newest-first article cap per request
NEWS_SWEEP_OVERLAP_SECONDS = 300  # re-read a little history so no article slips

# Articles tagging a long list of symbols are market roundups ("12 Industrials
# Stocks Moving In Monday's Pre-Market Session", "Why <X> Shares Are Trading
# Higher" with 20 tickers attached), not news about any one company, and must
# not earn a ticker the freshness boost. A story about a single company does
# routinely pick up a few extra tags - sector ETFs that hold it, a peer named in
# passing - so the cap allows a handful instead of demanding an exact match.
NEWS_MAX_SYMBOLS_PER_ARTICLE = 6
# Admitting a ticker into a watch list on news alone is a stronger claim than
# labelling one that is already there, so the market-wide breaking-news query
# (no symbol filter) holds to a tighter line.
NEWS_BREAKING_MAX_SYMBOLS_PER_ARTICLE = 3


class NewsAnnotator:
    """Caches each symbol's latest Alpaca news article and stamps it onto records."""

    def __init__(self, api_key=None, api_secret=None):
        self.client = None
        self._latest = {}       # symbol -> {'headline','source','url','created_at'}
        self._covered = set()   # symbols already backfilled this session
        self._last_sweep = None  # tz-aware UTC datetime of last incremental sweep
        self._breaking = {}     # symbol -> article dict, from market-wide queries
        self._breaking_fetched_at = None

        api_key = api_key or os.environ.get('APCA_API_KEY_ID')
        api_secret = api_secret or os.environ.get('APCA_API_SECRET_KEY')
        if not NEWS_CLIENT_AVAILABLE:
            logger.warning("⚠️  alpaca-py not installed - news annotation disabled")
        elif not api_key or not api_secret:
            logger.warning("⚠️  Alpaca API keys not found - news annotation disabled")
        else:
            self.client = NewsClient(api_key, api_secret)
            logger.info("📰 Alpaca news annotator initialized")

    @property
    def available(self):
        return self.client is not None

    # ------------------------------------------------------------------ public

    def refresh(self, symbols):
        """Make sure the latest-article cache covers `symbols`.

        New symbols are backfilled immediately; known ones are re-swept at most
        every NEWS_REFRESH_SECONDS. Safe to call every scan cycle.
        """
        if not self.client:
            return
        wanted = {s for s in symbols if s and s.isalpha()}
        if not wanted:
            return
        now = datetime.now(pytz.UTC)

        new_syms = sorted(wanted - self._covered)
        if new_syms:
            self._fetch(new_syms, now - timedelta(hours=NEWS_BACKFILL_HOURS))
            self._covered.update(new_syms)

        due = (self._last_sweep is None
               or (now - self._last_sweep).total_seconds() >= NEWS_REFRESH_SECONDS)
        if due:
            if self._last_sweep is not None:
                sweep = sorted((wanted & self._covered) - set(new_syms))
                if sweep:
                    start = self._last_sweep - timedelta(seconds=NEWS_SWEEP_OVERLAP_SECONDS)
                    self._fetch(sweep, start)
            self._last_sweep = now

    def annotate(self, records, symbol_key='name'):
        """Stamp news_* fields onto every record whose symbol has a cached article."""
        if not self.client or not records:
            return records
        try:
            self.refresh([r.get(symbol_key) for r in records])
        except Exception as e:
            logger.warning(f"⚠️  News refresh failed: {e}")

        tagged = 0
        for record in records:
            art = self._latest.get(record.get(symbol_key))
            if not art:
                continue
            record['news_headline'] = art['headline']
            record['news_source'] = art['source']
            record['news_url'] = art['url'] or ''
            record['news_created_at'] = art['created_at'].isoformat()
            record['news_at_et'] = art['created_at'].astimezone(ET_TZ).strftime('%Y-%m-%dT%H:%M:%S')
            tagged += 1
        if tagged:
            logger.info(f"📰 Tagged {tagged}/{len(records)} records with latest news")
        return records

    def age_minutes(self, symbol):
        """Minutes since `symbol`'s latest cached article, or None if it has none."""
        art = self._latest.get(symbol)
        if not art:
            return None
        return max(0.0, (datetime.now(pytz.UTC) - art['created_at']).total_seconds() / 60)

    def breaking_symbols(self, max_age_minutes=60,
                         max_symbols_per_article=NEWS_BREAKING_MAX_SYMBOLS_PER_ARTICLE):
        """Symbols with a company-specific article published in the last
        `max_age_minutes`, from a market-wide (no symbol filter) news query.
        Returns {symbol: article dict}. Used to *admit* tickers into a watch
        list before their volume would surface them; refreshed at most every
        NEWS_REFRESH_SECONDS, so calling every scan cycle is cheap.
        """
        if not self.client:
            return {}
        now = datetime.now(pytz.UTC)
        due = (self._breaking_fetched_at is None
               or (now - self._breaking_fetched_at).total_seconds() >= NEWS_REFRESH_SECONDS)
        if due:
            try:
                news_set = self.client.get_news(NewsRequest(
                    start=now - timedelta(minutes=max_age_minutes),
                    sort='desc',
                    limit=NEWS_ARTICLES_PER_BATCH,
                    include_content=False,
                ))
                breaking = {}
                for art in news_set.data.get('news', []):
                    syms = [s for s in art.symbols if s.isalpha()]
                    if not syms or len(syms) > max_symbols_per_article:
                        continue
                    created = art.created_at
                    if created.tzinfo is None:
                        created = pytz.UTC.localize(created)
                    entry = {
                        'headline': art.headline,
                        'source': art.source,
                        'url': art.url,
                        'created_at': created,
                    }
                    for sym in syms:
                        cur = breaking.get(sym)
                        if cur is None or created > cur['created_at']:
                            breaking[sym] = entry
                        # Feed the latest-article cache too, so annotate() can
                        # stamp an admitted ticker without a second fetch.
                        latest = self._latest.get(sym)
                        if latest is None or created > latest['created_at']:
                            self._latest[sym] = entry
                self._breaking = breaking
                self._breaking_fetched_at = now
            except Exception as e:
                logger.warning(f"⚠️  Breaking-news fetch failed: {e}")

        cutoff = now - timedelta(minutes=max_age_minutes)
        return {s: a for s, a in self._breaking.items() if a['created_at'] >= cutoff}

    # ----------------------------------------------------------------- private

    def _fetch(self, symbols, start):
        for i in range(0, len(symbols), NEWS_SYMBOL_BATCH):
            batch = symbols[i:i + NEWS_SYMBOL_BATCH]
            try:
                news_set = self.client.get_news(NewsRequest(
                    symbols=','.join(batch),
                    start=start,
                    sort='desc',
                    limit=NEWS_ARTICLES_PER_BATCH,
                    include_content=False,
                ))
            except Exception as e:
                logger.warning(f"⚠️  News fetch failed for {len(batch)} symbols: {e}")
                continue
            batch_set = set(batch)
            for art in news_set.data.get('news', []):
                if len([s for s in art.symbols if s.isalpha()]) > NEWS_MAX_SYMBOLS_PER_ARTICLE:
                    continue  # market roundup, not a story on any one ticker
                created = art.created_at
                if created.tzinfo is None:
                    created = pytz.UTC.localize(created)
                for sym in art.symbols:
                    if sym not in batch_set:
                        continue
                    cur = self._latest.get(sym)
                    if cur is None or created > cur['created_at']:
                        self._latest[sym] = {
                            'headline': art.headline,
                            'source': art.source,
                            'url': art.url,
                            'created_at': created,
                        }


if __name__ == '__main__':
    # Smoke test: python alpaca_news_feed.py AAPL TSLA
    import sys
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    syms = [s.upper() for s in sys.argv[1:]] or ['AAPL', 'TSLA', 'NVDA']
    annotator = NewsAnnotator()
    records = [{'name': s} for s in syms]
    annotator.annotate(records)
    for r in records:
        if 'news_headline' in r:
            age = annotator.age_minutes(r['name'])
            print(f"{r['name']:<6} {age:8.1f} min ago  [{r['news_source']}] "
                  f"{r['news_headline'][:70]}\n       ET {r['news_at_et']}  {r['news_url']}")
        else:
            print(f"{r['name']:<6} no news in the last {NEWS_BACKFILL_HOURS}h")
