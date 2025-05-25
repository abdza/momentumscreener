# MomentumScreener

MomentumScreener is a Python-based tool that leverages the TradingView Screener API to identify stocks exhibiting momentum characteristics. It provides functionalities to discover available fields, track volume momentum, and automate the screening process.

## Features

* **TradingView Screener Integration**: Connects to TradingView's screener to fetch real-time stock data.
* **Field Discovery**: Identifies and lists available fields from the TradingView screener.
* **Volume Momentum Tracking**: Monitors and analyzes volume-based momentum indicators.
* **Automated Screening**: Automates the process of screening stocks based on defined momentum criteria.

## Installation

1. **Clone the repository**:

   ```bash
   git clone https://github.com/abdza/momentumscreener.git
   cd momentumscreener
   ```

2. **Install the required dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

## Usage

### 1. Field Discovery

To discover available fields from the TradingView screener:

```bash
python field_discovery.py
```

### 2. Volume Momentum Tracking

To track volume-based momentum:

```bash
python volume_momentum_tracker.py
```

### 3. Automated Screening

To run the automated screener bot:

```bash
python tradingview_screener_bot.py
```

*Note: Ensure that you have the necessary configurations set up before running the scripts.*

## Configuration

Before running the scripts, you may need to configure certain parameters such as the exchange, symbols, and screening criteria. Please refer to the respective script files for configurable options and adjust them according to your requirements.

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).

---

If you need further customization or additional sections in the README, feel free to ask!
