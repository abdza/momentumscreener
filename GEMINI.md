# Momentum Screener Project Knowledge & Architecture

## 1. Project Overview
This workspace (`/home/abdza/momentumscreener`) is a real-time **bullish (LONG-ONLY) small-cap stock momentum screening, tracking, alerting, and paper-trading system** focusing on US equities priced **under $20** (excluding OTC exchanges).

Originally built solely on TradingView's screener, the architecture has evolved into a **hybrid Alpaca SIP + TradingView + yfinance pipeline** with real-time WebSocket bar streaming, NBBO bid/ask quote stamping, breaking news annotation, automated premarket & regular-session strategy execution, and an interactive dual-dashboard web server.

All snapshot timestamps and filenames use **US Eastern Time (`America/New_York`, `YYYYMMDD_HHMMSS`)** so each trading day maps cleanly into a single date bucket regardless of the host machine's local timezone (`Asia/Kuala_Lumpur`).

---

## 2. Core Functional Pillars & Modules

### A. Real-Time Collectors & Screeners
1. **Premarket Top 20 Monitor (`premarket_top20_monitor.py` / `pretop20.sh`)**
   - **Schedule / Session**: Premarket (04:00–09:30 ET), scans every **1 minute**.
   - **Function**: Tracks the top 20 tickers by premarket volume and % change, plus **10-minute candle-spike promotions** (`CANDLE_SPIKE_RATIO_THRESHOLD = 3.0x` prior baseline buckets) and breaking-news promotions.
   - **Outputs**: Writes `pretop20/screener_YYYYMMDD_HHMMSS.json`, tracks rank shifts in `premarket_top20_positions.json`, and sends Telegram notifications (`pretop20/notification_*.txt`).

2. **Regular-Session Volume Momentum Tracker (`volume_momentum_tracker.py` / `screener.sh`)**
   - **Schedule / Session**: Regular market hours (09:30–16:00 ET), scans every **2 minutes** (`premarket_momentum_tracker.py` is an older premarket variant).
   - **Function**: Detects 5 bullish alert categories:
     1. *Price Spikes* (immediate alerts for 15%+ spikes, bypassing the 3-alert confirmation rule)
     2. *Flat-to-Spike Patterns* (≥12.1% change from open after ≥8 min of ≤3% volatility)
     3. *Volume Climbers* (rising up volume rankings with positive price action)
     4. *Volume Newcomers* (entering top 50 volume rankings)
     5. *Premarket Volume & Price Alerts*
   - **Scoring & Filtering**: Computes a composite momentum score `(price_change * 0.4) + (rel_volume * 0.3) + (change_from_open * 0.3)`, applies sector-specific multipliers (e.g., dampening noisy Finance/Health Tech, boosting Electronic Tech), enforces ticker concentration caps, and uses performance-tiered cooldowns (5 / 10 / 20 min).
   - **Outputs**: `momentum_data/raw_data_YYYYMMDD_HHMMSS.json`, `momentum_data/alerts_YYYYMMDD_HHMMSS.json`, `momentum_data/latest_alerts.json`, `momentum_data/ticker_counters.json`, `momentum_data/ticker_alert_history.json`.

3. **Opening Range Breakout Screener (`orb_screener.py` / `orb.sh`)**
   - **Schedule / Session**: Single-shot scans shortly after market open (e.g., 09:30 and 10:00 ET).
   - **Function**: Queries TradingView (via `tradingview-screener` + `rookiepy` browser cookies) for stocks < $20 with `change_from_open` between **1% and 5%**, sorted by volume (top 20), stamps NBBO quotes via Alpaca, saves to `orb_data/screener_YYYYMMDD_HHMMSS.json`, and sends Telegram summaries.

4. **Static TradingView Screener (`tradingview_screener_bot.py`)**
   - **Function**: Standalone snapshot exporter (CSV/JSON) for 9 key small-cap metrics using browser cookie authentication.

---

### B. Data Enrichment & Real-Time Feeds
- **`alpaca_stream_screener.py` (`StreamScreener`)**: Subscribes to `bars("*")` on Alpaca's live SIP WebSocket feed to maintain a rolling 90-minute window of 1-minute bars across all US equities in memory. Performs lazy batched previous-close lookups (`PREVCLOSE_MIN_DOLLAR_VOL = $25,000`) and mid-session REST backfills from 04:00 ET so universe discovery is real-time rather than delayed 15 minutes.
- **`quotes.py` (`fetch_latest_quotes`)**: Stamps every candidate record in `premarket_top20_monitor.py`, `volume_momentum_tracker.py`, and `orb_screener.py` with simultaneous NBBO quote metrics (`bid`, `ask`, `bid_size`, `ask_size`, `mid`, `spread`, `spread_pct`, `quote_at`). Nullifies `mid`/`spread`/`spread_pct` on crossed/one-sided books or placeholder spreads (`> 50%`).
- **`alpaca_news_feed.py` (`NewsAnnotator`)**: Queries Alpaca's News API (24h backfill + 120s incremental sweeps) and stamps company-specific headlines (`news_headline`, `news_source`, `news_url`, `news_created_at`, `news_at_et`) onto candidate records (ignoring multi-ticker roundups with >6 symbols).
- **`float_shares.py` & `float_shares.json`**: Provides free-float lookups (`float_shares_outstanding`) harvested from historical snapshots and refreshed asynchronously in a background thread via `yfinance` (7-day TTL).
- **`symbol_meta.py` & `symbol_meta.json`**: Maps `symbol -> {sector, exchange}` harvested from historical TradingView snapshots so Alpaca-sourced records retain sector/exchange classifications.

---

### C. Automated Strategies, Backtesters & Live Paper Traders
1. **Flat-Then-Premarket-Spike Strategy (`flat_spike_strategy.py`, `flat_spike_backtester.py`, `flat_spike_live_trader.py` / `flat_spike_live.sh`)**
   - **Signal Logic**: Looks for stocks that were calm/flat over the prior 5 trading days (daily range < 8%, net drift < 15%, avg daily range ≥ 2%), then spike ≥ 15% at or after 05:00 ET in premarket, with entry price in `[$5, $20)` and pre-entry liquidity ≥ $12,000/min.
   - **Exit Logic**: Premarket-only (force-closes at **09:20 ET**). Exits earlier on:
     - Break below premarket low (stop-loss)
     - Range-based trailing stop (`RANGE_DRAWDOWN_PCT = 5%` of day's range below peak, with a 10-minute recovery timer)
     - Immediate hard floor (`HARD_STOP_RANGE_PCT = 60%` of day's range below peak, no timer)
   - **Manual Telegram Trade Tracking**: `flat_spike_live_trader.py` also polls Telegram for `/b TICKER [price]`, `/s TICKER`, `/positions`, and `/help` to monitor user-entered trades with the exact same exit rules (`manual_positions.json` / `manual_trades.json`).
   - **Data Dir**: `momentum_data/flat_spike_live_trades/` and `momentum_data/flat_spike_trades/`.

2. **Flush-Then-Reload Strategy (`flush_spike_strategy.py`, `flush_spike_backtester.py`, `flush_spike_live_trader.py` / `flush_spike_live.sh`)**
   - **Signal Logic**: Sibling premarket strategy capturing violent `peak -> flush (≥20% drop from running peak) -> reload (≥30% bounce off flush low)` cycles with entry price in `[$2, $20)`. Supports multiple trades per ticker per day and reuses `flat_spike_strategy`'s liquidity and exit rules.
   - **Data Dir**: `momentum_data/flush_spike_live_trades/` and `momentum_data/flush_spike_trades/`.

3. **Intraday EMA Paper Trading System (`paper_trading_system.py`, `paper_trading_analyzer.py` / `paper_trades.sh`)**
   - **Logic**: Integrated into `volume_momentum_tracker.py --paper-trading`. Enters ($100 base position size, scaled by market sentiment) when an alert triggers and price > 5-min 9 EMA; exits when price < 5-min 25 EMA.
   - **Data Dir**: `momentum_data/paper_trades/`.

---

### D. Web Dashboards (`server.py`, `index.html`, `index2.html`)
- **`server.py`**: Lightweight Python HTTP server listening on **port 5000** (`http://localhost:5000`).
  - `/` or `/pretop20/` -> serves `index.html` (Premarket Volume & Price Tracker dashboard backed by `/pretop20/api/{dates,data,latest}`).
  - `/markethour/` -> serves `index2.html` (Regular-Session Intraday Momentum Tracker dashboard backed by `/markethour/api/{dates,data,latest}`).
  - Deduplicates consecutive identical snapshots and strips `NaN`/`Infinity` for clean browser JSON parsing.

---

### E. Market Sentiment, Post-Market Analytics & AI Workflows
- **Market Sentiment (`market_sentiment_scorer.py`, `market_sentiment_analyzer.py`, `market_correlation_analyzer.py`, `market_condition_tester.py`)**: Scores SPY/QQQ/IWM/VIX conditions (0–100 score) to dynamically scale position sizing and filter alerts.
- **End-of-Day & Alert Analyzers (`end_of_day_analyzer.py` / `end_of_day.sh`, `telegram_alert_analyzer.py`, `enhanced_alert_performance_analyzer.py`, `drawdown_analyzer.py`, `pattern_analyzer.py`, `alert_validator.py`)**: Evaluate post-alert high-of-day (HOD), max drawdown, conversion rates, and pattern effectiveness.
- **Automated AI Ticker Analysis (`ticker_analysis.sh`, `ticker_analysis_log.md`)**: Cron-driven workflow that analyzes the current session's `momentum_data/raw_data_*.json` and `pretop20/screener_*.json` snapshots, selects a top momentum pick with Entry / Stop / Target and runners-up, logs to `ticker_analysis_log.md`, and dispatches HTML-linked `$TICKER` summaries to Telegram.

---

## 3. "Ticker Analysis" Workflow & Output Specification
Whenever the user asks for a **"ticker analysis"** (or via `ticker_analysis.sh`), execute the following workflow:

### Step 1: Analyze Session Data From Scratch
1. Inspect all available data for the **current session** (or the specific date/session mentioned by the user):
   - Premarket snapshots: `pretop20/screener_YYYYMMDD_*.json`
   - Regular-session snapshots & alerts: `momentum_data/raw_data_YYYYMMDD_*.json`, `momentum_data/alerts_YYYYMMDD_*.json`
   - Opening range snapshots (if applicable): `orb_data/screener_YYYYMMDD_*.json`
   - Float & metadata: `float_shares.json`, `symbol_meta.json`
   - Prior picks from earlier in the same session in `ticker_analysis_log.md` (to grade/update whether an earlier pick succeeded or failed).
2. Filter & evaluate candidates to find **the best ticker to ride momentum up before it turns back down**:
   - Focus on **bullish small-cap equities** (price < $20, exclude leveraged ETFs, test symbols, and illiquid/wide-spread traps; be cautious with sub-$0.20 names).
   - Trajectory across snapshots: look for **clean higher lows and higher highs**, breakout from a base, or post-halt/post-flush recovery with rising price near the high of day (avoid stocks steadily fading from an early spike).
   - Volume & Relative Volume: look for **accelerating volume and rising relative volume** across recent snapshots.
   - Microstructure & Catalyst: check **bid/ask spread** (tight spread preferred), **float** (`float_shares_outstanding` for squeeze potential vs. whip risk), and **news catalyst** (`news_headline` / `news_at_et`).

### Step 2: Append Entry to `ticker_analysis_log.md`
Append a structured markdown section to `ticker_analysis_log.md` matching the existing log format:
```markdown
## YYYY-MM-DD HH:MM ET (YYYY-MM-DD HH:MM MYT) — <Session description>

**Data examined:** <summary of snapshots/files and time range examined>

### Top pick: <TICKER> — $<price> at <HH:MM> ET
- **Entry:** <entry range / trigger>
- **Stop:** <stop level and rationale>
- **Target:** $<target> (+<pct>%); stretch $<stretch>
- **Why:**
  - <catalyst / pattern / higher-lows trajectory>
  - <volume and relative volume acceleration>
  - <float and spread>
- **Risk:** <key risks and sizing note>

### Runners-up
1. **<TICKER1>** $<price>: <concise summary>
2. **<TICKER2>** $<price>: <concise summary>
3. **<TICKER3>** $<price>: <concise summary or status of prior session pick>

**Passed on:** <tickers passed on and brief reasons>

### Outcome
_(to be filled after close: HOD after call, max drawdown after call, target/stop hit first, runner-up results)_

---
```

### Step 3: Reply to the User in the Exact Summary Format
Respond with a concise summary in this exact structure (note: if invoked via `ticker_analysis.sh` where the prompt asks for leading `$` on tickers for Telegram auto-linking, prefix tickers with `$`; otherwise in interactive chat follow the template below):

```text
Top pick: POM at $1.71 (10:13 ET)

Entry: $1.65–1.70 on a hold above $1.60, or a break of $1.77
Stop: $1.45
Target: $2.00 (+17%), stretch $2.30

Why:
- It came back from a trading halt on news. It spiked from $0.94 to $1.765, flushed to $1.22, then made higher lows: $1.22, $1.35, $1.48, $1.71.
- Volume went from 3.3M to 6.1M and is still rising. Relative volume went from 28x to 84x.
- Float is 3.7M and the spread is 1 cent.
- Risk: it is already +157% on the day and halt-prone, so size small.

Runners-up:
1. REED at $0.883: +101% from open, volume 4.2M and accelerating, float 3.7M. It is early, with relative volume only 2.6x.
2. SDEV at $1.09: steady climb on 15.7M volume, float 26.7M, but stalling around $1.10–1.15.
3. SPHL at $3.725: my 09:46 pick failed. It fell from $5.50 through my $4.85 stop.

The entry is appended to ticker_analysis_log.md.
```
