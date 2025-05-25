# TradingView Small Caps Momentum Tracker

A Python-based real-time momentum tracking system for small cap stocks using TradingView's screener data. Automatically detects volume surges, price spikes, and ranking improvements to identify emerging momentum plays.

## 🎯 Features

### Static Screener (`tradingview_screener_bot.py`)
- **9 Key Metrics**: Relative volume, volume, price×volume, change from open %, change %, price, float, pre-market change %, sector
- **Smart Filtering**: Price < $20, excludes OTC exchanges
- **Multiple Export Formats**: JSON and CSV output
- **Authenticated Access**: Uses browser cookies for TradingView data

### Live Momentum Tracker (`volume_momentum_tracker.py`)
- **Real-time Monitoring**: Scans every 2 minutes during market hours
- **Volume Climbers**: Detects stocks moving up volume rankings
- **Price Spike Alerts**: Identifies significant price increases
- **Volume Newcomers**: Spots new entries in high-volume rankings
- **Historical Comparison**: Tracks changes between scan cycles

### Field Discovery (`field_discovery.py`)
- **API Exploration**: Discovers available TradingView data fields
- **Field Validation**: Tests column names for compatibility
- **Debug Tool**: Helps troubleshoot data access issues

## 📋 Requirements

```
Python 3.7+
pandas
rookiepy
tradingview-screener
schedule (for static screener automation)
```

## 🚀 Installation

1. **Clone the repository**:
```bash
git clone https://github.com/yourusername/tradingview-momentum-tracker.git
cd tradingview-momentum-tracker
```

2. **Install dependencies**:
```bash
pip install pandas rookiepy tradingview-screener schedule
```

3. **Install rookiepy** (may require environment variable on Python 3.13+):
```bash
# If installation fails on Python 3.13+
export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1  # Linux/macOS
# OR
set PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1     # Windows
pip install rookiepy
```

4. **Ensure TradingView access**: Log into TradingView in your browser (Firefox/Chrome) before running scripts.

## 📊 Usage

### Static Screener
```bash
python tradingview_screener_bot.py
```
- Generates timestamped CSV/JSON files with small cap data
- Sorted by relative volume (descending)
- Filters: price < $20, no OTC exchanges

### Live Momentum Tracker
```bash
python volume_momentum_tracker.py
```
- Choose **[S]ingle scan** for testing
- Choose **[C]ontinuous monitoring** for live tracking
- Outputs real-time alerts to console and files

### Field Discovery (Troubleshooting)
```bash
python field_discovery.py
```
- Tests TradingView API field compatibility
- Useful for debugging data access issues

## 📁 Output Files

### Static Screener
- `small_caps_screener_YYYYMMDD_HHMMSS.csv` - Screener data in spreadsheet format
- `small_caps_screener_YYYYMMDD_HHMMSS.json` - Screener data in JSON format

### Momentum Tracker
- `alerts_YYYYMMDD_HHMMSS.json` - Detailed momentum alerts
- `latest_alerts.json` - Most recent alerts (overwritten each scan)
- `raw_data_YYYYMMDD_HHMMSS.json` - Raw screener data
- `volume_momentum_tracker.log` - Detailed operation logs

## 🔧 Configuration

### Browser Selection
Both scripts default to Firefox but support other browsers:
```python
BROWSER = "firefox"  # Options: "firefox", "chrome", "edge", "safari"
```

### Monitoring Settings
Momentum tracker configuration:
```python
monitor_interval = 120  # Scan every 2 minutes
max_history = 50       # Keep last 50 data points
limit = 200           # Number of stocks to analyze
```

### Alert Thresholds
```python
# Volume climbers: stocks moving up positions in rankings
rank_change > 0

# Price spikes: stocks with significant price increases  
change_pct > 5 or price_change > 5

# Newcomers: new stocks entering top 50 volume rankings
current_rank < 50
```

## 📋 Sample Output

### Console Alerts
```
🚨 MOMENTUM ALERTS - 14:32:15
================================================================================

📈 VOLUME CLIMBERS (3 found):
  ABCD   | Rank: 45 → 12 (+33) | Vol: 15,234,567 | $8.45 (+12.3%) | Technology

🆕 NEW HIGH VOLUME (2 found):  
  WXYZ   | NEW → Rank 8 | Vol: 23,456,789 | $15.67 (+8.9%) | Healthcare

🔥 PRICE SPIKES (4 found):
  EFGH   | $3.21 (+18.5%) | Vol: 8,765,432 | RelVol: 4.2x | Energy
```

### CSV Data Columns
```csv
ticker,relative_volume_10d_calc,volume,Value.Traded,change_from_open,change|5,close,float_shares_outstanding,premarket_change,sector,exchange
ABCD,4.2,15234567,129876543,12.3,8.9,8.45,45000000,2.1,Technology,NASDAQ
```

## ⚠️ Important Notes

### Authentication
- Scripts use browser cookies via `rookiepy` for TradingView access
- Requires active TradingView session in browser
- Cookies may expire - refresh browser session if authentication fails

### Market Hours
- Best results during regular market hours (9:30 AM - 4:00 PM ET)
- Pre-market and after-hours data may be limited
- Weekend/holiday data will be minimal

### Rate Limiting
- Default 2-minute intervals respect TradingView's usage policies
- Avoid running multiple instances simultaneously
- Consider longer intervals for extended monitoring

### Data Accuracy
- Data sourced from TradingView's public screener
- Real-time delays may apply
- Always verify critical data with primary sources

## 🐛 Troubleshooting

### Common Issues

**"Failed to extract cookies"**
- Ensure you're logged into TradingView in your browser
- Try different browser (Firefox recommended)
- Clear browser cache and re-login

**"400 Client Error: Bad Request"**  
- Usually caused by invalid field names in API query
- Run `field_discovery.py` to identify working fields
- Check TradingView API changes

**"No data returned"**
- Verify TradingView session is active
- Check market hours (data limited outside trading hours)
- Ensure filters aren't too restrictive

## 📜 Legal Disclaimer

**This project is for educational and research purposes only.**

- Not financial advice or investment recommendations
- Historical performance does not guarantee future results  
- Always conduct your own research before making investment decisions
- Respect TradingView's Terms of Service and rate limits
- Users are responsible for compliance with applicable laws and regulations

## 🤝 Contributing

Contributions welcome! Please:
- Fork the repository
- Create a feature branch
- Submit pull requests with clear descriptions
- Report bugs via GitHub issues

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [TradingView](https://tradingview.com) for providing market data
- [tradingview-screener](https://pypi.org/project/tradingview-screener/) Python library
- [rookiepy](https://pypi.org/project/rookiepy/) for browser cookie extraction

---

**⚡ Happy trading and may your momentum plays be profitable! 📈**
