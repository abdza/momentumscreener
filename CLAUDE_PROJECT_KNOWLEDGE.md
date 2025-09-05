# Momentum Screener Project Knowledge Base
*For Claude Code Assistant Reference*

## Project Overview
This is a real-time momentum trading alert system focused on **LONG TRADES ONLY** for small-cap stocks. The system continuously monitors TradingView screener data to detect bullish momentum patterns and sends optimized Telegram alerts.

## Key Components

### 1. Main Files
- **`volume_momentum_tracker.py`** - Core momentum tracking and alert system
- **`tradingview_screener_bot.py`** - TradingView data collection (small caps screener)
- **`market_sentiment_scorer.py`** - Market condition analysis
- **`end_of_day_analyzer.py`** - Post-market performance analysis
- **`alert_validator.py`** - Alert validation and pattern analysis

### 2. Data Storage
- **`momentum_data/`** - Alert files stored as JSON with timestamps
- **`volume_momentum_tracker.log`** - System logs
- Alert files format: `alerts_YYYYMMDD_HHMMSS.json`

## Alert System Architecture

### Alert Types (5 Categories)
1. **Price Spikes** (43% of alerts) - Significant positive price movements
2. **Premarket Price Alerts** (18.7%) - Pre-market price movements
3. **Volume Climbers** (14.1%) - Stocks climbing volume rankings
4. **Volume Newcomers** (13.3%) - New high-volume entries
5. **Premarket Volume Alerts** (10.8%) - Pre-market volume surges

### Alert Filtering System (Recently Enhanced)
**Momentum Scoring**: `(price_change × 0.4) + (rel_volume × 0.3) + (change_from_open × 0.3)`

**Priority Tiers**:
- **High Priority (>50)**: Immediate alerts, bypass cooldowns
- **Medium Priority (20-50)**: Standard processing  
- **Low Priority (<20)**: Extended cooldown periods

**Cooldown System**:
- High performers (>20% avg change): 5-minute cooldown
- Regular (5-20% avg change): 10-minute cooldown
- Poor performers (<5% avg change): 20-minute cooldown

## Key Thresholds & Parameters

### Current Settings (Post-Optimization)
- **Immediate Alert Threshold**: 15% (lowered from 25%)
- **Flat-to-Spike Threshold**: 12.1% change from open (lowered from 15%)
- **Flat Volatility Threshold**: 3% max volatility to consider "flat"
- **Minimum Flat Duration**: 8 minutes
- **Price Filter**: < $20 per share
- **Exchange Filter**: Excludes OTC

### Sector-Specific Tuning
```
Finance & Health Technology:
  - 1.5x relative volume multiplier (reduce noise)
Technology Services:
  - 0.9x multipliers (catch early momentum)
Electronic Technology:
  - 0.8x multipliers (prioritize high momentum)
Utilities:
  - 30% max ticker concentration (prevent PCG/PC dominance)
```

## Historical Performance Insights

### Top Pattern: Flat-to-Spike Detection
- **33.6% of alerts** show flat-to-spike patterns
- **47.21% average** change from open for flat-to-spike
- **High success rate** - prioritized in momentum scoring

### Common Issues (Addressed in Recent Updates)
1. **PCG/PC Over-Concentration**: 16.4% of all alerts from one ticker
   - *Solution*: Sector concentration limits
2. **Late Detection**: 25% threshold too high for early momentum
   - *Solution*: Lowered to 15%
3. **Sector Noise**: Finance/Health Tech generating false positives
   - *Solution*: Sector-specific multipliers

### Quality Metrics Benchmarks
- **83.6%** of alerts have >3x relative volume (excellent filtering)
- **44%** have >5% price moves (good capture rate)
- **26.6%** show flat-to-spike patterns (high success indicator)
- **3%** are massive moves (>25%) - suggests room for earlier detection

## Code Structure Deep Dive

### Key Classes
```python
class VolumeMomentumTracker:
    # Main tracker with enhanced filtering
    def should_send_alert() - NEW comprehensive filtering
    def calculate_momentum_score() - NEW scoring system
    def get_sector_adjusted_thresholds() - NEW sector tuning
```

### Alert Flow
1. **Data Collection** - TradingView screener every 2 minutes
2. **Pattern Detection** - Price spikes, flat-to-spike, volume changes
3. **Momentum Scoring** - Calculate composite score
4. **Filtering** - Apply cooldowns, sector adjustments, concentration limits
5. **Telegram Sending** - Rate-limited, markdown-formatted alerts
6. **Logging** - JSON files for analysis, performance tracking

### Data Schema
```json
{
  "timestamp": "ISO format",
  "volume_climbers": [],
  "volume_newcomers": [],
  "price_spikes": [
    {
      "ticker": "SYMBOL",
      "current_price": float,
      "change_pct": float,
      "volume": int,
      "relative_volume": float,
      "sector": "string",
      "alert_type": "flat_to_spike|price_spike",
      "flat_analysis": {},
      "change_from_open": float
    }
  ],
  "premarket_volume_alerts": [],
  "premarket_price_alerts": []
}
```

## Analysis & Performance Tracking

### Weekly Analysis Script
Created `telegram_alert_analyzer.py` for comprehensive performance analysis:
- Alert distribution by type and sector
- Top performing tickers and patterns
- Time-based activity patterns
- Success rate metrics
- Threshold optimization recommendations

### Key Performance Indicators
1. **Alert-to-Move Conversion Rate** (track 1hr, 4hr, 1day post-alert)
2. **False Positive Rate** (alerts failing to sustain momentum)
3. **Sector Rotation Detection** (momentum shifts between sectors)
4. **Pattern Success Rate** (flat-to-spike vs regular spike performance)

## Market Context Understanding

### Current Market Characteristics
- **High Volatility**: 10.52% average price changes
- **Strong Volume Activity**: 83.6% alerts above 3x relative volume
- **Premarket Dominance**: 29.5% alerts in premarket (gap-play environment)
- **Technology Leadership**: Tech sectors showing consistent momentum

### Peak Activity Patterns
- **03:00-04:59**: Highest activity (premarket preparation)
- **22:00-23:59**: Secondary peak (after-hours momentum)
- **09:00-16:00**: Limited activity (missed intraday opportunities)

## Troubleshooting Guide

### Common Issues
1. **No Telegram Alerts**: Check bot token, chat ID, cookie extraction
2. **Over-Concentration**: Review sector limits and cooldown periods
3. **Missing Momentum**: Check if thresholds are too high
4. **False Positives**: Verify sector-specific multipliers

### Log Analysis
- Check `volume_momentum_tracker.log` for system status
- Monitor JSON alert files for pattern changes
- Use analysis scripts for performance insights

## Recent Optimizations (Sep 2025)

### Implemented Changes
1. **Threshold Optimization**: 25% → 15% immediate alerts
2. **Momentum Scoring**: Composite scoring system
3. **Smart Cooldowns**: Performance-based cooldown periods
4. **Sector Tuning**: Custom multipliers per sector
5. **Concentration Limits**: Prevent ticker dominance
6. **Enhanced Flat-to-Spike**: 15% → 12.1% threshold

### Expected Outcomes
- Earlier detection of significant moves
- Reduced noise from over-active tickers
- Better sector-specific filtering
- Improved flat-to-spike pattern capture
- Balanced alert distribution

## Future Enhancement Opportunities

### Recommended Improvements
1. **Dynamic Thresholds**: Adjust based on market volatility
2. **Multi-Timeframe Confirmation**: Require alignment across timeframes
3. **Volume Profile Analysis**: Time-of-day volume normalization
4. **Machine Learning**: Pattern recognition enhancement
5. **Risk Management**: Stop-loss optimization integration

### Performance Tracking
- Implement real-time success metrics
- Add sector rotation alerts
- Enhanced pattern analysis
- Market condition adaptability

## Quick Reference Commands

```bash
# Single scan
python volume_momentum_tracker.py --single

# Continuous with alerts (15%+ immediate threshold)
python volume_momentum_tracker.py --continuous --bot-token "TOKEN" --chat-id "ID"

# Custom threshold
python volume_momentum_tracker.py --continuous --immediate-threshold 20

# Reset counters
python volume_momentum_tracker.py --reset

# Analysis
python telegram_alert_analyzer.py
```

## Important Notes for Claude

1. **Always check recent alert files** in `momentum_data/` for current performance
2. **Review logs** for system health and filtering effectiveness  
3. **The system is LONG TRADES ONLY** - only bullish momentum matters
4. **Flat-to-spike patterns are highest priority** - they have best success rates
5. **PCG/PC over-concentration was a major issue** - now addressed with limits
6. **Sector-specific tuning is critical** - Finance/Health Tech are noisy
7. **Analysis scripts provide actionable insights** - use them for optimization recommendations

This knowledge base should be updated whenever significant changes are made to the system architecture, performance insights are discovered, or optimization strategies are implemented.