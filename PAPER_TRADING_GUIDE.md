# Paper Trading System Guide

## Overview
The paper trading system simulates automated trading based on your momentum alerts to evaluate strategy performance without risking real money. It implements a simple EMA-based strategy:

**Entry Rule:** Alert triggered + Current price > 5-minute 9 EMA  
**Exit Rule:** Current price < 5-minute 25 EMA  
**Position Size:** $100 per trade (configurable)

## Quick Start

### Enable Paper Trading
```bash
# Run with paper trading enabled
python volume_momentum_tracker.py --continuous --paper-trading --bot-token "YOUR_TOKEN" --chat-id "YOUR_CHAT_ID"

# Single scan with paper trading
python volume_momentum_tracker.py --single --paper-trading
```

### View Performance Report
```bash
# Generate performance report
python volume_momentum_tracker.py --paper-report
```

## How It Works

### 1. Alert Processing
- When an alert is triggered, the system checks if the current price is above the 5-minute 9 EMA
- If conditions are met, it simulates buying $100 worth of shares
- All alerts are processed for potential entries, regardless of alert type

### 2. Position Management  
- Tracks active positions with entry price, shares, and timing
- Continuously monitors price data to calculate EMAs
- Automatically exits when price drops below 5-minute 25 EMA

### 3. Data Storage
- Trade history saved to `momentum_data/paper_trades/trade_history.json`
- Active positions saved to `momentum_data/paper_trades/active_positions.json`
- Performance metrics calculated in real-time

## Strategy Logic

### Entry Conditions
1. **Alert Trigger**: Any momentum alert (price spike, volume climber, etc.)
2. **Price Check**: Current price > 5-minute 9 EMA
3. **Available Funds**: Sufficient balance for $100 position
4. **No Existing Position**: Not already holding the ticker

### Exit Conditions
1. **EMA Crossover**: Current price < 5-minute 25 EMA
2. **Automatic**: Checked every scan cycle (every 2 minutes)

### EMA Calculations
- **9 EMA**: Faster moving average for entry signals
- **25 EMA**: Slower moving average for exit signals
- **Calculation**: Exponential weighted moving average using pandas
- **Data Requirements**: Minimum 9 price points for 9 EMA, 25 for 25 EMA

## Performance Metrics

### Key Statistics
- **Total Trades**: Number of completed buy/sell cycles
- **Win Rate**: Percentage of profitable trades
- **Total P&L**: Net profit/loss in dollars
- **Average Return**: Mean percentage return per trade
- **Holding Time**: Average time between entry and exit

### Risk Metrics
- **Best/Worst Trade**: Highest profit and loss amounts
- **Current Balance**: Virtual account balance
- **Active Positions**: Number of currently held positions

## Configuration Options

### Paper Trading System Parameters
```python
PaperTradingSystem(
    initial_balance=10000,    # Starting virtual balance
    position_size=100,        # Dollar amount per trade
    data_dir="paper_trades"   # Data storage directory
)
```

### Integration with Main System
- Automatically processes all approved alerts
- Respects existing alert filtering (momentum scoring, cooldowns)
- Runs alongside telegram notifications without interference

## Sample Output

```
📊 PAPER TRADE ENTRY: ABCD at $11.5000
📊 PAPER TRADE EXIT: ABCD - P&L: $+2.50 (+2.50%)
📊 AUTO EXIT: XYZ - P&L: $-1.20 (-1.20%)
```

### Performance Report Example
```
📊 PAPER TRADING PERFORMANCE REPORT
==================================================

💰 ACCOUNT SUMMARY:
   Initial Balance: $10,000.00
   Current Balance: $10,150.30
   Total Return: +1.50%
   
📈 TRADING STATISTICS:
   Total Trades: 25
   Win Rate: 64.0%
   Winning Trades: 16
   Losing Trades: 9
   
💵 PROFIT/LOSS:
   Total P&L: $+150.30
   Average Return: +0.60%
   Median Return: +0.80%
   Best Trade: $+15.20
   Worst Trade: $-8.50
   
⏰ TIMING:
   Avg Holding Time: 45.2 minutes
   Active Positions: 3
```

## Data Analysis

### Trade History Format
```json
{
  "ticker": "ABCD",
  "entry_price": 10.50,
  "exit_price": 10.80,
  "shares": 9.5238,
  "entry_timestamp": "2025-09-06T10:30:00",
  "exit_timestamp": "2025-09-06T11:15:00", 
  "holding_time_minutes": 45,
  "position_size": 100,
  "exit_value": 102.86,
  "profit_loss": 2.86,
  "profit_pct": 2.86,
  "alert_type": "price_spike",
  "exit_reason": "EMA_EXIT"
}
```

### Analysis Opportunities
- **Alert Type Performance**: Which alert types generate better trades
- **Sector Analysis**: Performance by sector
- **Holding Time Patterns**: Optimal exit timing
- **Market Condition Correlation**: Performance vs market volatility

## Best Practices

### 1. Data Collection Period
- Run for at least 2-4 weeks to get meaningful statistics
- Include various market conditions (trending, sideways, volatile)
- Monitor during active trading hours for realistic results

### 2. Strategy Validation
- Compare paper trading returns vs buy-and-hold
- Analyze risk-adjusted returns (Sharpe ratio)
- Consider transaction costs in real trading

### 3. Parameter Optimization
- Test different EMA periods (9/25 vs 12/26, etc.)
- Experiment with position sizing
- Evaluate different exit strategies

## Troubleshooting

### Common Issues

**No Trades Executing**
- Check EMA calculation (need sufficient price history)
- Verify alert filtering isn't too restrictive
- Ensure paper trading is enabled (`--paper-trading` flag)

**Frequent Whipsaws**
- Markets may be too choppy for EMA strategy
- Consider adding confirmation filters
- Adjust EMA periods for less sensitivity

**Poor Performance**
- EMA crossover strategies struggle in sideways markets
- Consider market condition filters
- Add momentum confirmation requirements

### Log Messages
```
📊 PAPER TRADE ENTRY: [ticker] at $[price]
📊 PAPER TRADE EXIT: [ticker] - P&L: $[amount] ([percent]%)
📊 AUTO EXIT: [ticker] - P&L: $[amount] ([percent]%)
✅ ENTRY SIGNAL: [ticker] at $[price] > 9EMA $[ema]
🚨 EXIT SIGNAL: [ticker] at $[price] < 25EMA $[ema]
❌ NO ENTRY: [ticker] at $[price] <= 9EMA $[ema]
```

## Strategy Enhancements

### Potential Improvements
1. **Multiple Exit Criteria**: Add stop-loss, profit targets, time-based exits
2. **Position Sizing**: Risk-based position sizing based on volatility
3. **Market Filter**: Only trade during favorable market conditions
4. **Confirmation Signals**: Require volume or momentum confirmation
5. **Portfolio Management**: Maximum positions, sector diversification

### Integration Ideas
- **Market Sentiment**: Use market sentiment scorer for trade sizing
- **News Impact**: Avoid trades during major news events
- **Volatility Filter**: Adjust position size based on ATR or VIX

## Files Created
- `paper_trading_system.py` - Core paper trading logic
- `test_paper_trading.py` - Test script and examples
- `PAPER_TRADING_GUIDE.md` - This documentation
- `momentum_data/paper_trades/` - Trade data storage directory

The paper trading system provides valuable insight into whether your alert-based momentum strategy can generate consistent profits. Use it to refine your approach before considering real money implementation.