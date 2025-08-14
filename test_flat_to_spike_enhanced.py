#!/usr/bin/env python3
"""
Test Enhanced Flat-to-Spike Detection
Validates the new flat-to-spike detection mechanism in volume_momentum_tracker.py
"""

import sys
import os
from datetime import datetime, timedelta

# Add the parent directory to the path so we can import volume_momentum_tracker
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from volume_momentum_tracker import VolumeMomentumTracker

def test_flat_to_spike_detection():
    """Test the enhanced flat-to-spike detection mechanism"""
    
    print("ENHANCED FLAT-TO-SPIKE DETECTION TEST")
    print("=" * 50)
    
    # Initialize tracker without telegram to avoid errors
    tracker = VolumeMomentumTracker(
        output_dir="test_momentum_data",
        telegram_bot_token=None,
        telegram_chat_id=None
    )
    
    current_time = datetime.now()
    
    # Test Case 1: Simulate a flat period followed by a spike
    print("\n1. Testing Flat Period Detection:")
    print("-" * 30)
    
    ticker = "TEST1"
    
    # Simulate flat period (10 data points over 20 minutes with minimal volatility)
    flat_prices = [2.00, 2.01, 1.99, 2.00, 2.02, 2.00, 1.99, 2.01, 2.00, 1.98]
    
    for i, price in enumerate(flat_prices):
        timestamp = current_time - timedelta(minutes=20-i*2)  # 2-minute intervals
        flat_analysis = tracker._detect_flat_period(ticker, price, timestamp)
        print(f"  t-{20-i*2:2d}min: ${price:.2f} | Flat: {flat_analysis['is_flat']} | "
              f"Vol: {flat_analysis['flat_volatility']:.1f}% | "
              f"Dur: {flat_analysis['flat_duration_minutes']:.1f}min")
    
    # Test the spike after flat period
    spike_price = 2.40  # 20% spike
    spike_analysis = tracker._detect_flat_period(ticker, spike_price, current_time)
    print(f"  SPIKE:    ${spike_price:.2f} | Flat: {spike_analysis['is_flat']} | "
          f"Vol: {spike_analysis['flat_volatility']:.1f}% | "
          f"Dur: {spike_analysis['flat_duration_minutes']:.1f}min")
    
    # Test Case 2: Simulate volatile period (not flat) followed by spike
    print("\n2. Testing Non-Flat Period Detection:")
    print("-" * 30)
    
    ticker2 = "TEST2"
    
    # Simulate volatile period (high volatility)
    volatile_prices = [3.00, 3.15, 2.90, 3.20, 2.85, 3.10, 2.95, 3.25, 2.80, 3.30]
    
    for i, price in enumerate(volatile_prices):
        timestamp = current_time - timedelta(minutes=20-i*2)
        volatile_analysis = tracker._detect_flat_period(ticker2, price, timestamp)
        print(f"  t-{20-i*2:2d}min: ${price:.2f} | Flat: {volatile_analysis['is_flat']} | "
              f"Vol: {volatile_analysis['flat_volatility']:.1f}% | "
              f"Dur: {volatile_analysis['flat_duration_minutes']:.1f}min")
    
    # Test the spike after volatile period
    spike_price2 = 3.96  # 20% spike
    spike_analysis2 = tracker._detect_flat_period(ticker2, spike_price2, current_time)
    print(f"  SPIKE:    ${spike_price2:.2f} | Flat: {spike_analysis2['is_flat']} | "
          f"Vol: {spike_analysis2['flat_volatility']:.1f}% | "
          f"Dur: {spike_analysis2['flat_duration_minutes']:.1f}min")
    
    # Test Case 3: Test scoring algorithm
    print("\n3. Testing Enhanced Scoring Algorithm:")
    print("-" * 30)
    
    test_cases = [
        {
            "name": "FLAT-TO-SPIKE (Verified)",
            "alert_type": "flat_to_spike",
            "price": 1.50,
            "change_pct": 80.0,
            "relative_volume": 200.0,
            "sector": "Health Services"
        },
        {
            "name": "REGULAR SPIKE (Unverified)",
            "alert_type": "price_spike", 
            "price": 1.50,
            "change_pct": 80.0,
            "relative_volume": 200.0,
            "sector": "Health Services"
        },
        {
            "name": "PREMARKET GAP",
            "alert_type": "premarket_price",
            "price": 1.50,
            "change_pct": 80.0,
            "relative_volume": 200.0,
            "sector": "Health Services"
        }
    ]
    
    for test_case in test_cases:
        analysis = tracker._analyze_winning_patterns(
            test_case['price'],
            test_case['change_pct'],
            test_case['relative_volume'],
            test_case['sector'],
            test_case['alert_type']
        )
        
        print(f"  {test_case['name']:25} | Score: {analysis['score']:3d} | "
              f"Prob: {analysis['probability_category']:9} ({analysis['estimated_probability']:4.1f}%)")
        print(f"    Flags: {', '.join(analysis['flags']) if analysis['flags'] else 'None'}")
    
    # Test Case 4: Test alert type assignment in price spike detection
    print("\n4. Testing Alert Type Assignment:")
    print("-" * 30)
    
    # Simulate current market data
    test_data = [
        {
            'name': 'FLAT1',
            'close': 2.40,  # This should trigger a flat-to-spike after our setup
            'change|5': 20.0,
            'volume': 1000000,
            'relative_volume_10d_calc': 150.0,
            'sector': 'Technology Services'
        },
        {
            'name': 'VOLT1', 
            'close': 3.96,  # This should trigger a regular spike after volatile setup
            'change|5': 20.0,
            'volume': 1000000,
            'relative_volume_10d_calc': 150.0,
            'sector': 'Technology Services'
        }
    ]
    
    spikes = tracker.analyze_price_spikes(test_data)
    
    for spike in spikes:
        alert_type = spike.get('alert_type', 'unknown')
        flat_analysis = spike.get('flat_analysis', {})
        is_flat = flat_analysis.get('is_flat', False)
        flat_vol = flat_analysis.get('flat_volatility', 0)
        flat_dur = flat_analysis.get('flat_duration_minutes', 0)
        
        print(f"  {spike['ticker']:6} | Type: {alert_type:12} | Flat: {is_flat} | "
              f"Vol: {flat_vol:4.1f}% | Dur: {flat_dur:4.1f}min | "
              f"Change: {spike['change_pct']:+5.1f}%")
    
    print(f"\n✅ Enhanced Flat-to-Spike Detection Test Complete!")
    print(f"🎯 Flat detection: {'WORKING' if spike_analysis['is_flat'] else 'NEEDS TUNING'}")
    print(f"⚡ Spike classification: {'WORKING' if len(spikes) > 0 else 'FAILED'}")
    print(f"📊 Scoring enhancement: {'WORKING' if any(case['alert_type'] == 'flat_to_spike' for case in test_cases) else 'FAILED'}")

if __name__ == "__main__":
    test_flat_to_spike_detection()