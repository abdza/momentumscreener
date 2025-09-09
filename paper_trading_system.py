#!/usr/bin/env python3
"""
Paper Trading System for Alert-Based Strategy Backtesting

Strategy Rules:
1. BUY: When alert triggers AND current price > 5min 9 EMA
2. SELL: When current price < 5min 25 EMA
3. Position Size: $100 per trade
4. Track all trades for profitability analysis

This system simulates trades to evaluate the effectiveness of momentum alerts
without risking real money.
"""

import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import logging
from collections import defaultdict, deque
import requests
import time
import pytz

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PaperTradingSystem:
    def __init__(self, initial_balance=10000, position_size=100, data_dir="paper_trades"):
        """
        Initialize the paper trading system
        
        Args:
            initial_balance (float): Starting virtual balance
            position_size (float): Dollar amount per trade ($100 default)
            data_dir (str): Directory to save trade data
        """
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.position_size = position_size
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        # Active positions: {ticker: position_info}
        self.active_positions = {}
        
        # Trade history
        self.trade_history = []
        
        # Price data storage for EMA calculations
        # {ticker: deque of price data}
        self.price_history = defaultdict(lambda: deque(maxlen=50))  # Keep 50 5-min candles
        
        # Performance tracking
        self.daily_balances = []
        self.win_rate = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        
        # Load existing data
        self._load_trade_history()
        self._load_active_positions()
        
    def calculate_ema(self, prices, period):
        """
        Calculate Exponential Moving Average
        
        Args:
            prices (list): List of prices (oldest first)
            period (int): EMA period (9 or 25)
            
        Returns:
            float: Current EMA value, None if insufficient data
        """
        if len(prices) < period:
            return None
        
        # Convert to pandas Series for easier calculation
        prices_series = pd.Series(prices)
        ema = prices_series.ewm(span=period, adjust=False).mean()
        return float(ema.iloc[-1])  # Return the latest EMA value
    
    def update_price_data(self, ticker, price, timestamp=None):
        """
        Update price history for EMA calculations
        
        Args:
            ticker (str): Stock symbol
            price (float): Current price
            timestamp (datetime): Price timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        # Add to price history
        self.price_history[ticker].append({
            'timestamp': timestamp,
            'price': price
        })
        
        # Clean old data (keep only last hour of 5-min data)
        cutoff_time = timestamp - timedelta(hours=1)
        while (self.price_history[ticker] and 
               self.price_history[ticker][0]['timestamp'] < cutoff_time):
            self.price_history[ticker].popleft()
    
    def get_current_emas(self, ticker):
        """
        Calculate current 9 and 25 EMAs for a ticker
        
        Args:
            ticker (str): Stock symbol
            
        Returns:
            tuple: (ema_9, ema_25) or (None, None) if insufficient data
        """
        if ticker not in self.price_history or len(self.price_history[ticker]) < 9:
            return None, None
        
        prices = [entry['price'] for entry in self.price_history[ticker]]
        
        ema_9 = self.calculate_ema(prices, 9)
        ema_25 = self.calculate_ema(prices, 25)
        
        return ema_9, ema_25
    
    def should_enter_trade(self, ticker, current_price, alert_type):
        """
        Determine if we should enter a trade based on strategy rules
        
        Args:
            ticker (str): Stock symbol
            current_price (float): Current stock price
            alert_type (str): Type of alert triggered
            
        Returns:
            bool: True if we should enter trade
        """
        # Don't enter if we already have a position
        if ticker in self.active_positions:
            return False
        
        # Don't enter if insufficient funds
        if self.current_balance < self.position_size:
            logger.warning(f"Insufficient balance for new trade: ${self.current_balance:.2f}")
            return False
        
        # Calculate EMAs
        ema_9, ema_25 = self.get_current_emas(ticker)
        
        if ema_9 is None:
            logger.debug(f"Insufficient data for EMA calculation: {ticker}")
            return False
        
        # Strategy rule: Enter if price > 9 EMA
        should_enter = current_price > ema_9
        
        if should_enter:
            logger.info(f"✅ ENTRY SIGNAL: {ticker} at ${current_price:.4f} > 9EMA ${ema_9:.4f}")
        else:
            logger.debug(f"❌ NO ENTRY: {ticker} at ${current_price:.4f} <= 9EMA ${ema_9:.4f}")
        
        return should_enter
    
    def should_exit_trade(self, ticker, current_price):
        """
        Determine if we should exit a trade based on strategy rules
        
        Args:
            ticker (str): Stock symbol
            current_price (float): Current stock price
            
        Returns:
            bool: True if we should exit trade
        """
        # Only exit if we have a position
        if ticker not in self.active_positions:
            return False
        
        # Calculate EMAs
        ema_9, ema_25 = self.get_current_emas(ticker)
        
        if ema_25 is None:
            logger.debug(f"Insufficient data for 25 EMA exit calculation: {ticker}")
            return False
        
        # Strategy rule: Exit if price < 25 EMA
        should_exit = current_price < ema_25
        
        if should_exit:
            logger.info(f"🚨 EXIT SIGNAL: {ticker} at ${current_price:.4f} < 25EMA ${ema_25:.4f}")
        
        return should_exit
    
    def should_force_exit_eod(self, current_time=None):
        """
        Check if we should force exit all positions due to end of day (3:45 PM ET)
        
        Only applies during regular trading session (9:30 AM - 4:00 PM ET).
        After-hours alerts should not trigger immediate EOD exits.
        
        Args:
            current_time (datetime): Current time (defaults to now)
            
        Returns:
            bool: True if we should force exit all positions
        """
        if current_time is None:
            current_time = datetime.now()
        
        # Convert to Eastern Time
        et_tz = pytz.timezone('US/Eastern')
        
        # If current_time is naive, assume it's in local system timezone and convert properly
        if current_time.tzinfo is None:
            # Get the system's local timezone and localize the naive datetime
            local_tz = pytz.timezone('Asia/Kuala_Lumpur')  # Change this to your actual timezone
            current_time = local_tz.localize(current_time)
            # Then convert to Eastern Time
            current_time = current_time.astimezone(et_tz)
        else:
            # Convert to ET if it has timezone info
            current_time = current_time.astimezone(et_tz)
        
        # Only apply EOD logic on weekdays
        is_weekday = current_time.weekday() < 5  # 0-4 are Mon-Fri
        if not is_weekday:
            return False
        
        # Define trading session boundaries
        market_open = current_time.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = current_time.replace(hour=16, minute=0, second=0, microsecond=0)
        eod_cutoff = current_time.replace(hour=15, minute=45, second=0, microsecond=0)
        
        # Only trigger EOD exit if:
        # 1. We're during regular trading hours (9:30 AM - 4:00 PM ET)
        # 2. Current time is past the 3:45 PM cutoff
        # This prevents after-hours alerts from triggering immediate EOD exits
        is_during_trading_hours = market_open <= current_time <= market_close
        is_past_eod_cutoff = current_time >= eod_cutoff
        
        return is_during_trading_hours and is_past_eod_cutoff
    
    def force_exit_all_positions(self, current_prices=None, timestamp=None, reason="EOD_CUTOFF"):
        """
        Force exit all active positions (e.g., end of day cutoff)
        
        Args:
            current_prices (dict): {ticker: current_price} - if None, will try to fetch
            timestamp (datetime): Exit timestamp
            reason (str): Reason for forced exit
            
        Returns:
            list: List of completed trades
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        if not self.active_positions:
            return []
        
        logger.info(f"🚨 FORCE EXITING ALL {len(self.active_positions)} POSITIONS - {reason}")
        
        completed_trades = []
        
        for ticker in list(self.active_positions.keys()):
            # Use provided price or last entry price as fallback
            if current_prices and ticker in current_prices:
                exit_price = current_prices[ticker]
            else:
                # Fallback to entry price if no current price available
                exit_price = self.active_positions[ticker]['entry_price']
                logger.warning(f"No current price for {ticker}, using entry price ${exit_price:.4f}")
            
            exit_result = self.exit_trade(ticker, exit_price, timestamp, reason)
            if exit_result:
                completed_trades.append(exit_result)
        
        logger.info(f"✅ FORCE EXIT COMPLETE - {len(completed_trades)} positions closed")
        return completed_trades
    
    def check_eod_exit(self, current_prices=None, current_time=None):
        """
        Check and execute end-of-day exits if needed
        
        Args:
            current_prices (dict): {ticker: current_price}
            current_time (datetime): Current time
            
        Returns:
            list: List of completed trades if EOD exit was triggered, empty list otherwise
        """
        if self.should_force_exit_eod(current_time):
            return self.force_exit_all_positions(current_prices, current_time, "EOD_CUTOFF_3:45PM_ET")
        return []
    
    def enter_trade(self, ticker, price, alert_type, timestamp=None):
        """
        Execute a paper trade entry
        
        Args:
            ticker (str): Stock symbol
            price (float): Entry price
            alert_type (str): Type of alert that triggered entry
            timestamp (datetime): Trade timestamp
            
        Returns:
            dict: Trade entry details or None if trade not executed
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        if not self.should_enter_trade(ticker, price, alert_type):
            return None
        
        # Calculate shares (fractional shares allowed)
        shares = self.position_size / price
        
        # Create position
        position = {
            'ticker': ticker,
            'entry_price': price,
            'shares': shares,
            'entry_timestamp': timestamp,
            'alert_type': alert_type,
            'entry_emas': self.get_current_emas(ticker)
        }
        
        # Update balances
        self.active_positions[ticker] = position
        self.current_balance -= self.position_size
        
        logger.info(f"📈 ENTERED TRADE: {ticker} - {shares:.4f} shares at ${price:.4f} (${self.position_size})")
        
        return position
    
    def exit_trade(self, ticker, price, timestamp=None, reason="EMA_EXIT"):
        """
        Execute a paper trade exit
        
        Args:
            ticker (str): Stock symbol
            price (float): Exit price
            timestamp (datetime): Trade timestamp
            reason (str): Reason for exit
            
        Returns:
            dict: Completed trade details or None if no position
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        if ticker not in self.active_positions:
            return None
        
        position = self.active_positions[ticker]
        
        # Calculate P&L
        exit_value = position['shares'] * price
        profit_loss = exit_value - self.position_size
        profit_pct = (profit_loss / self.position_size) * 100
        
        # Calculate holding time - handle timezone aware/naive datetime differences
        entry_time = position['entry_timestamp']
        if timestamp.tzinfo is not None and entry_time.tzinfo is None:
            # If exit timestamp has timezone but entry doesn't, assume entry is in same timezone
            entry_time = pytz.timezone('US/Eastern').localize(entry_time)
        elif timestamp.tzinfo is None and entry_time.tzinfo is not None:
            # If entry has timezone but exit doesn't, convert exit to entry's timezone
            if entry_time.tzinfo:
                timestamp = entry_time.tzinfo.localize(timestamp)
        
        holding_time = timestamp - entry_time
        
        # Create completed trade record
        completed_trade = {
            'ticker': ticker,
            'entry_price': position['entry_price'],
            'exit_price': price,
            'shares': position['shares'],
            'entry_timestamp': position['entry_timestamp'].isoformat(),
            'exit_timestamp': timestamp.isoformat(),
            'holding_time_minutes': holding_time.total_seconds() / 60,
            'position_size': self.position_size,
            'exit_value': exit_value,
            'profit_loss': profit_loss,
            'profit_pct': profit_pct,
            'alert_type': position['alert_type'],
            'exit_reason': reason,
            'entry_emas': position['entry_emas'],
            'exit_emas': self.get_current_emas(ticker)
        }
        
        # Update balances
        self.current_balance += exit_value
        
        # Update statistics
        self.total_trades += 1
        if profit_loss > 0:
            self.winning_trades += 1
        self.win_rate = (self.winning_trades / self.total_trades) * 100 if self.total_trades > 0 else 0
        
        # Add to history
        self.trade_history.append(completed_trade)
        
        # Remove from active positions
        del self.active_positions[ticker]
        
        # Log trade result
        result_emoji = "🟢" if profit_loss > 0 else "🔴"
        logger.info(f"{result_emoji} EXITED TRADE: {ticker} - ${profit_loss:.2f} ({profit_pct:+.2f}%) in {holding_time}")
        
        # Save trade data
        self._save_trade_history()
        self._save_active_positions()
        
        return completed_trade
    
    def process_alert(self, ticker, current_price, alert_type, timestamp=None):
        """
        Process an alert and potentially enter/exit trades
        
        Args:
            ticker (str): Stock symbol
            current_price (float): Current price
            alert_type (str): Type of alert
            timestamp (datetime): Alert timestamp
            
        Returns:
            dict: Trade actions taken
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        # Update price data for EMA calculations
        self.update_price_data(ticker, current_price, timestamp)
        
        actions = {
            'entry': None,
            'exit': None,
            'eod_exits': None,
            'price_update': True
        }
        
        # Check for EOD cutoff first - this takes priority over everything
        eod_exits = self.check_eod_exit({ticker: current_price}, timestamp)
        if eod_exits:
            actions['eod_exits'] = eod_exits
            return actions  # Return immediately if EOD exit occurred
        
        # Check for exit signals on active positions
        if ticker in self.active_positions:
            if self.should_exit_trade(ticker, current_price):
                actions['exit'] = self.exit_trade(ticker, current_price, timestamp)
        
        # Check for entry signals (only if not currently holding)
        if ticker not in self.active_positions:
            entry_result = self.enter_trade(ticker, current_price, alert_type, timestamp)
            if entry_result:
                actions['entry'] = entry_result
        
        return actions
    
    def check_all_positions_for_exits(self, price_data, current_time=None):
        """
        Check all active positions for exit signals including EOD cutoff
        
        Args:
            price_data (dict): {ticker: current_price}
            current_time (datetime): Current time for EOD check
        """
        exits_executed = []
        
        # First check for EOD cutoff - this takes priority
        eod_exits = self.check_eod_exit(price_data, current_time)
        if eod_exits:
            return eod_exits  # Return EOD exits immediately
        
        # Regular exit checks for individual positions
        for ticker in list(self.active_positions.keys()):
            if ticker in price_data:
                current_price = price_data[ticker]
                self.update_price_data(ticker, current_price)
                
                if self.should_exit_trade(ticker, current_price):
                    exit_result = self.exit_trade(ticker, current_price)
                    if exit_result:
                        exits_executed.append(exit_result)
        
        return exits_executed
    
    def get_performance_summary(self):
        """
        Get comprehensive performance statistics
        
        Returns:
            dict: Performance metrics
        """
        if not self.trade_history:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'average_profit_pct': 0
            }
        
        profits = [trade['profit_loss'] for trade in self.trade_history]
        profit_pcts = [trade['profit_pct'] for trade in self.trade_history]
        holding_times = [trade['holding_time_minutes'] for trade in self.trade_history]
        
        return {
            'total_trades': len(self.trade_history),
            'win_rate': self.win_rate,
            'total_pnl': sum(profits),
            'average_profit_pct': np.mean(profit_pcts),
            'median_profit_pct': np.median(profit_pcts),
            'best_trade': max(profits),
            'worst_trade': min(profits),
            'average_holding_time_min': np.mean(holding_times),
            'current_balance': self.current_balance,
            'total_return': ((self.current_balance / self.initial_balance) - 1) * 100,
            'active_positions': len(self.active_positions),
            'winning_trades': self.winning_trades,
            'losing_trades': self.total_trades - self.winning_trades
        }
    
    def _save_trade_history(self):
        """Save trade history to file"""
        history_file = self.data_dir / "trade_history.json"
        with open(history_file, 'w') as f:
            json.dump(self.trade_history, f, indent=2, default=str)
    
    def _load_trade_history(self):
        """Load trade history from file"""
        history_file = self.data_dir / "trade_history.json"
        if history_file.exists():
            try:
                with open(history_file, 'r') as f:
                    self.trade_history = json.load(f)
                
                # Update statistics
                self.total_trades = len(self.trade_history)
                self.winning_trades = sum(1 for trade in self.trade_history if trade['profit_loss'] > 0)
                self.win_rate = (self.winning_trades / self.total_trades) * 100 if self.total_trades > 0 else 0
                
                # Recalculate balance from trades
                total_pnl = sum(trade['profit_loss'] for trade in self.trade_history)
                active_capital = len(self.active_positions) * self.position_size
                self.current_balance = self.initial_balance + total_pnl - active_capital
                
                logger.info(f"Loaded {len(self.trade_history)} historical trades")
            except Exception as e:
                logger.error(f"Failed to load trade history: {e}")
    
    def _save_active_positions(self):
        """Save active positions to file"""
        positions_file = self.data_dir / "active_positions.json"
        
        # Convert positions to serializable format
        serializable_positions = {}
        for ticker, position in self.active_positions.items():
            serializable_positions[ticker] = {
                **position,
                'entry_timestamp': position['entry_timestamp'].isoformat()
            }
        
        with open(positions_file, 'w') as f:
            json.dump(serializable_positions, f, indent=2, default=str)
    
    def _load_active_positions(self):
        """Load active positions from file"""
        positions_file = self.data_dir / "active_positions.json"
        if positions_file.exists():
            try:
                with open(positions_file, 'r') as f:
                    loaded_positions = json.load(f)
                
                # Convert back to proper format
                for ticker, position in loaded_positions.items():
                    position['entry_timestamp'] = datetime.fromisoformat(position['entry_timestamp'])
                    self.active_positions[ticker] = position
                
                logger.info(f"Loaded {len(self.active_positions)} active positions")
            except Exception as e:
                logger.error(f"Failed to load active positions: {e}")
    
    def generate_performance_report(self):
        """
        Generate a detailed performance report
        
        Returns:
            str: Formatted report
        """
        stats = self.get_performance_summary()
        
        report = f"""
📊 PAPER TRADING PERFORMANCE REPORT
{'='*50}

💰 ACCOUNT SUMMARY:
   Initial Balance: ${self.initial_balance:,.2f}
   Current Balance: ${stats['current_balance']:,.2f}
   Total Return: {stats['total_return']:+.2f}%
   
📈 TRADING STATISTICS:
   Total Trades: {stats['total_trades']}
   Win Rate: {stats['win_rate']:.1f}%
   Winning Trades: {stats['winning_trades']}
   Losing Trades: {stats['losing_trades']}
   
💵 PROFIT/LOSS:
   Total P&L: ${stats['total_pnl']:+,.2f}
   Average Return: {stats['average_profit_pct']:+.2f}%
   Median Return: {stats['median_profit_pct']:+.2f}%
   Best Trade: ${stats['best_trade']:+,.2f}
   Worst Trade: ${stats['worst_trade']:+,.2f}
   
⏰ TIMING:
   Avg Holding Time: {stats['average_holding_time_min']:.1f} minutes
   Active Positions: {stats['active_positions']}
   
🎯 STRATEGY EFFECTIVENESS:
   Position Size: ${self.position_size}
   Entry: Price > 9 EMA
   Exit: Price < 25 EMA
"""
        
        if self.active_positions:
            report += "\n🔄 ACTIVE POSITIONS:\n"
            for ticker, position in self.active_positions.items():
                entry_time = position['entry_timestamp']
                holding_time = datetime.now() - entry_time
                report += f"   {ticker}: ${position['entry_price']:.4f} ({holding_time})\n"
        
        return report

# Example usage and testing
if __name__ == "__main__":
    # Initialize paper trading system
    paper_trader = PaperTradingSystem()
    
    # Simulate some price data and alerts
    print("Testing paper trading system...")
    
    # Test data - simulating an alert scenario
    test_scenarios = [
        {"ticker": "ABCD", "price": 10.00, "alert_type": "price_spike"},
        {"ticker": "ABCD", "price": 10.50, "alert_type": "price_update"},
        {"ticker": "ABCD", "price": 9.50, "alert_type": "price_update"},  # Should trigger exit
    ]
    
    for i, scenario in enumerate(test_scenarios):
        print(f"\n--- Scenario {i+1} ---")
        result = paper_trader.process_alert(
            scenario["ticker"], 
            scenario["price"], 
            scenario["alert_type"]
        )
        print(f"Actions taken: {result}")
        
        # Add some price history for EMA calculation
        for j in range(10):
            paper_trader.update_price_data(scenario["ticker"], scenario["price"] + (j * 0.1))
    
    # Test EOD functionality
    print("\n--- Testing EOD Functionality ---")
    
    # Add some positions for testing
    paper_trader.enter_trade("TEST1", 15.00, "test_alert")
    paper_trader.enter_trade("TEST2", 25.00, "test_alert")
    
    # Simulate 3:46 PM ET
    et_tz = pytz.timezone('US/Eastern')
    test_time = et_tz.localize(datetime.now().replace(hour=15, minute=46, second=0, microsecond=0))
    
    print(f"Active positions before EOD check: {len(paper_trader.active_positions)}")
    
    # Test EOD check
    eod_exits = paper_trader.check_eod_exit(
        current_prices={"TEST1": 15.50, "TEST2": 24.00},
        current_time=test_time
    )
    
    print(f"EOD exits executed: {len(eod_exits)}")
    print(f"Active positions after EOD check: {len(paper_trader.active_positions)}")
    
    # Generate report
    print(paper_trader.generate_performance_report())