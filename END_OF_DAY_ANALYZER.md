# End-of-Day Alert Success Analyzer

## Overview
The End-of-Day Alert Success Analyzer tracks and analyzes the performance of all alerts generated during a trading session, providing detailed statistics on success rates, maximum gains, and drawdowns before success.

## Features

### ✅ **Core Functionality**
- **Success Rate Tracking**: Measures how many alerts achieved ≥30% gains (configurable threshold)
- **Maximum Drawdown Analysis**: Calculates worst price drops before achieving success
- **Alert Type Breakdown**: Compares performance across different alert types
- **Enhanced Flat-to-Spike Analysis**: Validates flat-to-spike pattern effectiveness
- **Telegram Reporting**: Sends comprehensive analysis via Telegram

### ✅ **Alert Types Supported**
- **Flat-to-Spike**: Verified flat period followed by spike
- **Price Spike**: Regular intraday price spikes
- **Volume Climber**: Stocks moving up in volume rankings
- **Volume Newcomer**: New entries in top volume rankings
- **Premarket Price**: Premarket price movements
- **Premarket Volume**: Premarket volume surges

## Installation

### Required Dependencies
```bash
# Activate virtual environment
source venv/bin/activate

# Install required packages
pip install yfinance pytz python-telegram-bot
```

### Dependencies Included
- `yfinance`: Market data fetching
- `pytz`: Timezone handling
- `python-telegram-bot`: Telegram notifications
- `pandas`: Data processing
- `asyncio`: Async Telegram messaging

## Usage

### Basic Usage
```bash
# Analyze today's alerts
python end_of_day_analyzer.py

# Analyze specific date
python end_of_day_analyzer.py --date 2025-08-15

# Set custom success threshold
python end_of_day_analyzer.py --success-threshold 25
```

### With Telegram Notifications
```bash
# Send results via Telegram
python end_of_day_analyzer.py \
    --bot-token "YOUR_BOT_TOKEN" \
    --chat-id "YOUR_CHAT_ID" \
    --date 2025-08-15
```

### Command Line Options
```
--date YYYY-MM-DD              Analyze alerts for specific date (default: today)
--bot-token TOKEN              Telegram bot token for notifications  
--chat-id ID                   Telegram chat ID for notifications
--success-threshold PCT        Success threshold percentage (default: 30%)
--data-dir DIR                 Directory containing alert data (default: momentum_data)
--help                         Show help message
```

## Analysis Process

### 1. **Alert Collection**
- Scans all alert files for the target date
- Extracts unique ticker alerts (first alert per ticker)
- Supports all alert types from volume_momentum_tracker.py

### 2. **Market Data Fetching**
- Uses yfinance to get 5-minute price data
- Falls back to daily data if 5-minute unavailable
- Handles timezone conversions automatically
- Filters data to post-alert timeframe

### 3. **Performance Calculation**
```python
# Success criteria
success = max_gain >= success_threshold  # Default: 30%

# Maximum gain calculation
max_gain = ((highest_price - alert_price) / alert_price) * 100

# Maximum drawdown before success
max_drawdown = ((lowest_price_before_success - alert_price) / alert_price) * 100
```

### 4. **Statistical Analysis**
- Overall success rate
- Performance by alert type
- Average gains and drawdowns
- Flat-to-spike vs regular pattern comparison

## Sample Output

```
📊 END-OF-DAY ALERT ANALYSIS - 2025-08-15
============================================================

🎯 OVERALL PERFORMANCE
──────────────────────────────
Total Alerts Analyzed: 25
Successful (≥30.0%): 1
Success Rate: 4.0%

📈 PERFORMANCE METRICS
──────────────────────────────
Average Max Gain: +18.2%
Average Successful Gain: +45.5%
Average Drawdown: 11.2%
Average Successful Drawdown:  3.2%
Maximum Drawdown: 12.4%

🏷️  ALERT TYPE BREAKDOWN
──────────────────────────────
Flat To Spike        |  1/ 1 (100.0%) | Gain: +45.5% | DD:  3.2%
Price Spike          |  0/ 5 ( 0.0%) | Gain: +22.3% | DD:  8.1%
Volume Climber       |  0/ 8 ( 0.0%) | Gain: +15.7% | DD: 12.4%
Premarket Alerts     |  0/ 4 ( 0.0%) | Gain: +15.7% | DD: 12.4%

🎯 FLAT-TO-SPIKE ANALYSIS
──────────────────────────────
Verified Flat-to-Spike: 1/1 (100.0%) | Gain: +45.5% | DD:  3.2%
Regular Price Spikes:   0/5 (0.0%) | Gain: +22.3% | DD:  8.1%
Premarket Alerts:       0/4 (0.0%) | Gain: +15.7% | DD: 12.4%

🏆 TOP PERFORMERS
──────────────────────────────
1. TEST1  |  +45.5% | DD:  3.2% | Flat To Spike

📉 LARGEST DRAWDOWNS
──────────────────────────────
1. MSN    | DD: 12.4% | Gain: +15.7% ❌ | Volume Climber
2. APWC   | DD: 12.4% | Gain: +15.7% ❌ | Volume Climber

📊 ANALYSIS COMPLETE
Generated: 2025-08-15 06:02:40
```

## Integration with Volume Momentum Tracker

### Data Source
- Reads alert files generated by `volume_momentum_tracker.py`
- Uses the same alert structure and types
- Supports enhanced flat-to-spike alerts

### Alert File Format
```json
{
  "timestamp": "2025-08-15T12:00:00",
  "price_spikes": [
    {
      "ticker": "AAPL",
      "current_price": 150.25,
      "change_pct": 35.5,
      "alert_type": "flat_to_spike",
      "flat_analysis": {
        "is_flat": true,
        "flat_duration_minutes": 15.0,
        "flat_volatility": 2.1
      }
    }
  ]
}
```

### Telegram Integration
- Uses same Telegram bot configuration as volume_momentum_tracker.py
- Sends formatted analysis reports
- Handles message length limits automatically
- Supports markdown formatting

## Key Metrics Explained

### Success Rate
- **Calculation**: (Alerts achieving ≥threshold) / (Total alerts) × 100
- **Purpose**: Overall effectiveness of alert system
- **Threshold**: Configurable (default: 30%)

### Maximum Gain
- **Calculation**: Highest price reached after alert vs alert price
- **Purpose**: Best possible outcome for each alert
- **Timeframe**: From alert time to end of trading day

### Maximum Drawdown
- **Calculation**: Worst price drop from alert price before achieving success
- **Purpose**: Risk assessment - how much loss before profit
- **Important**: Only calculated before success point, not overall

### Alert Type Performance
- **Comparison**: Success rates across different alert types
- **Validation**: Confirms flat-to-spike algorithm effectiveness
- **Optimization**: Identifies best-performing patterns

## Best Practices

### Daily Usage
```bash
# Run at end of trading day (after 4 PM ET)
python end_of_day_analyzer.py --bot-token "$TELEGRAM_BOT" --chat-id "$CHAT_ID"
```

### Historical Analysis
```bash
# Analyze past week
for date in 2025-08-11 2025-08-12 2025-08-13 2025-08-14 2025-08-15; do
    python end_of_day_analyzer.py --date $date
done
```

### Custom Thresholds
```bash
# Conservative analysis (20% threshold)
python end_of_day_analyzer.py --success-threshold 20

# Aggressive analysis (50% threshold)  
python end_of_day_analyzer.py --success-threshold 50
```

## Troubleshooting

### No Market Data Available
- **Issue**: yfinance cannot fetch data for ticker
- **Solution**: Check ticker symbol validity, market hours
- **Fallback**: Analyzer continues with available data

### Timezone Issues
- **Issue**: DateTime comparison errors
- **Solution**: Automatic timezone conversion to ET
- **Note**: Market data assumed to be in Eastern Time

### Empty Alert Files
- **Issue**: No alerts found for date
- **Solution**: Verify date format (YYYY-MM-DD) and data directory

### Telegram Errors
- **Issue**: Failed to send notifications
- **Solution**: Check bot token and chat ID validity
- **Fallback**: Analysis continues, report printed to console

## Files Created

### Core Script
- **`end_of_day_analyzer.py`**: Main analysis script

### Test Files  
- **`test_eod_analyzer.py`**: Testing framework with mock data

### Documentation
- **`END_OF_DAY_ANALYZER.md`**: This documentation file

## Performance Validation

### Test Results
✅ **Alert file loading and parsing**  
✅ **Alert extraction and deduplication**  
✅ **Alert type classification (including flat-to-spike)**  
✅ **Performance analysis framework**  
✅ **Report generation with statistics**  
✅ **Alert type breakdown and comparison**  
✅ **Flat-to-spike vs regular spike analysis**  

### Expected Outcomes
Based on flat-to-spike validation:
- **Flat-to-spike alerts**: Higher success rates, lower drawdowns
- **Regular price spikes**: Moderate performance
- **Premarket alerts**: Lower success rates (validated by historical data)

## Future Enhancements

### Potential Features
- **Multi-day analysis**: Track performance over multiple days
- **Risk-adjusted returns**: Include volume and volatility metrics
- **Pattern recognition**: Identify additional successful patterns
- **Portfolio simulation**: Calculate theoretical portfolio performance
- **Export functionality**: Save results to CSV/Excel

### Integration Options
- **Database storage**: Store results for long-term analysis
- **Web dashboard**: Real-time visualization of results
- **API endpoints**: Programmatic access to analysis results
- **Scheduling**: Automated daily analysis via cron jobs

The End-of-Day Alert Success Analyzer provides comprehensive performance tracking for your momentum trading alerts, validating the effectiveness of the enhanced flat-to-spike detection system!