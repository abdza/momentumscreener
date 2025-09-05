#!/usr/bin/env python3
"""
Quick test script for the paper trading system
"""

from paper_trading_system import PaperTradingSystem
import time

def test_paper_trading():
    print("🧪 Testing Paper Trading System...")
    
    # Initialize system
    trader = PaperTradingSystem(initial_balance=10000, position_size=100)
    
    # Test scenario: ABCD stock alert
    print("\n📊 Test Scenario: ABCD stock with momentum pattern")
    
    # Build up price history for EMA calculation
    print("Building price history for EMA calculations...")
    base_price = 10.0
    
    # Add 20 data points to build EMA history
    for i in range(20):
        price = base_price + (i * 0.05)  # Gradual uptrend
        trader.update_price_data("ABCD", price)
        time.sleep(0.01)  # Small delay to ensure different timestamps
    
    # Check EMAs
    ema_9, ema_25 = trader.get_current_emas("ABCD")
    ema_9_str = f"${ema_9:.4f}" if ema_9 else "N/A"
    ema_25_str = f"${ema_25:.4f}" if ema_25 else "N/A"
    print(f"Current EMAs: 9-period: {ema_9_str}, 25-period: {ema_25_str}")
    
    # Test Entry: Alert with price above 9 EMA
    entry_price = 11.00  # Above EMA
    print(f"\n📈 ENTRY TEST: Alert at ${entry_price:.4f} (above 9 EMA)")
    
    result = trader.process_alert("ABCD", entry_price, "price_spike")
    if result['entry']:
        print("✅ Entry successful!")
        print(f"   Position: {result['entry']['shares']:.4f} shares at ${result['entry']['entry_price']:.4f}")
    else:
        print("❌ Entry failed")
    
    # Simulate some price movement
    print("\n📊 Simulating price movement...")
    prices = [11.20, 11.50, 11.30, 10.80, 10.50, 10.20]  # Up then down
    
    for i, price in enumerate(prices):
        print(f"   Price update {i+1}: ${price:.4f}")
        trader.update_price_data("ABCD", price)
        
        # Check for exit
        result = trader.process_alert("ABCD", price, "price_update")
        if result['exit']:
            print(f"🚨 EXIT TRIGGERED at ${price:.4f}!")
            exit_info = result['exit']
            print(f"   P&L: ${exit_info['profit_loss']:+.2f} ({exit_info['profit_pct']:+.2f}%)")
            print(f"   Holding time: {exit_info['holding_time_minutes']:.1f} minutes")
            break
    
    # Generate performance report
    print("\n" + "="*50)
    print(trader.generate_performance_report())
    
    print("\n✅ Paper Trading System Test Complete!")

if __name__ == "__main__":
    test_paper_trading()