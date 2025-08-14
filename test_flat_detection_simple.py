#!/usr/bin/env python3
"""
Simple test for flat-to-spike detection logic
Tests the core logic without requiring all dependencies
"""

import sys
from datetime import datetime, timedelta

def detect_flat_period(price_history, flat_volatility_threshold=3.0, min_flat_duration_minutes=8):
    """
    Simplified version of the flat detection logic
    
    Args:
        price_history: List of {'timestamp': datetime, 'price': float}
        flat_volatility_threshold: Max % volatility to consider "flat"
        min_flat_duration_minutes: Minimum duration in minutes
        
    Returns:
        dict with flat detection results
    """
    if len(price_history) < 3:
        return {
            'is_flat': False,
            'flat_duration_minutes': 0,
            'flat_volatility': 0,
            'reason': 'insufficient_data'
        }
    
    # Calculate price statistics
    prices = [entry['price'] for entry in price_history]
    avg_price = sum(prices) / len(prices)
    min_price = min(prices)
    max_price = max(prices)
    
    # Calculate volatility as percentage range
    if avg_price > 0:
        volatility = ((max_price - min_price) / avg_price) * 100
    else:
        volatility = 0
    
    # Calculate duration
    if len(price_history) >= 2:
        duration_seconds = (price_history[-1]['timestamp'] - price_history[0]['timestamp']).total_seconds()
        duration_minutes = duration_seconds / 60
    else:
        duration_minutes = 0
    
    # Determine if flat
    is_flat = (
        volatility <= flat_volatility_threshold and
        duration_minutes >= min_flat_duration_minutes
    )
    
    return {
        'is_flat': is_flat,
        'flat_duration_minutes': duration_minutes,
        'flat_volatility': volatility,
        'flat_avg_price': avg_price,
        'flat_price_range': (min_price, max_price),
        'reason': 'flat_detected' if is_flat else f'volatility_{volatility:.1f}%_duration_{duration_minutes:.1f}min'
    }

def analyze_winning_patterns_enhanced(current_price, change_pct, relative_volume, sector, alert_type="price_spike"):
    """Simplified version of the enhanced pattern analysis"""
    flags = []
    score = 0
    
    # Enhanced flat-to-spike scoring
    if alert_type == "flat_to_spike":
        flags.append("🎯 FLAT-TO-SPIKE")
        score += 50  # Premium for verified flat-to-spike pattern
        
        if change_pct >= 75:
            flags.append("🚀 BIG FLAT-TO-SPIKE")
            score += 30
    elif alert_type == "price_spike":
        flags.append("⚡ SUDDEN SPIKE")
        score += 30
        
        if change_pct >= 75:
            flags.append("🚀 BIG SUDDEN SPIKE")
            score += 20
    elif alert_type in ["premarket_price", "premarket_volume"]:
        score -= 15  # Penalty for premarket gaps
    
    # Price range analysis
    if current_price < 1:
        flags.append("🎯 Under $1")
        score += 20
    elif current_price < 2:
        flags.append("💎 Under $2")
        score += 15
    
    # Change percentage analysis
    if change_pct >= 200:
        flags.append("🚀 MEGA SPIKE 200%+")
        score += 50
    elif change_pct >= 100:
        flags.append("🔥 BIG SPIKE 100%+")
        score += 40
    elif change_pct >= 50:
        flags.append("⚡ STRONG 50%+")
        score += 25
    
    # Calculate probability category
    if score >= 80:
        probability_category = "VERY HIGH"
        estimated_probability = 30.0
    elif score >= 60:
        probability_category = "HIGH"
        estimated_probability = 22.0
    elif score >= 40:
        probability_category = "MEDIUM"
        estimated_probability = 15.0
    elif score >= 20:
        probability_category = "LOW"
        estimated_probability = 8.0
    else:
        probability_category = "VERY LOW"
        estimated_probability = 4.0
    
    return {
        'flags': flags,
        'score': score,
        'probability_category': probability_category,
        'estimated_probability': estimated_probability
    }

def test_flat_to_spike_detection():
    """Test the enhanced flat-to-spike detection"""
    
    print("ENHANCED FLAT-TO-SPIKE DETECTION TEST")
    print("=" * 50)
    
    current_time = datetime.now()
    
    # Test Case 1: True Flat Period
    print("\n1. Testing True Flat Period:")
    print("-" * 30)
    
    # Simulate flat period with low volatility
    flat_history = []
    base_price = 2.00
    
    for i in range(10):
        timestamp = current_time - timedelta(minutes=20-i*2)
        # Add small random variations (±1%)
        price_variation = [-0.02, -0.01, 0, 0.01, 0.02, 0, -0.01, 0.01, 0, -0.02][i]
        price = base_price + price_variation
        
        flat_history.append({
            'timestamp': timestamp,
            'price': price
        })
    
    flat_result = detect_flat_period(flat_history)
    print(f"Flat Detection Result:")
    print(f"  Is Flat: {flat_result['is_flat']}")
    print(f"  Duration: {flat_result['flat_duration_minutes']:.1f} minutes") 
    print(f"  Volatility: {flat_result['flat_volatility']:.2f}%")
    print(f"  Price Range: ${flat_result['flat_price_range'][0]:.2f} - ${flat_result['flat_price_range'][1]:.2f}")
    print(f"  Reason: {flat_result['reason']}")
    
    # Test Case 2: Volatile Period (Not Flat)
    print("\n2. Testing Volatile Period:")
    print("-" * 30)
    
    volatile_history = []
    base_price = 3.00
    
    for i in range(10):
        timestamp = current_time - timedelta(minutes=20-i*2)
        # Add large variations (±5-10%)
        price_variations = [0.15, -0.10, 0.20, -0.15, 0.10, -0.05, 0.25, -0.20, 0.30, -0.25]
        price = base_price + price_variations[i]
        
        volatile_history.append({
            'timestamp': timestamp,
            'price': price
        })
    
    volatile_result = detect_flat_period(volatile_history)
    print(f"Volatile Detection Result:")
    print(f"  Is Flat: {volatile_result['is_flat']}")
    print(f"  Duration: {volatile_result['flat_duration_minutes']:.1f} minutes")
    print(f"  Volatility: {volatile_result['flat_volatility']:.2f}%") 
    print(f"  Price Range: ${volatile_result['flat_price_range'][0]:.2f} - ${volatile_result['flat_price_range'][1]:.2f}")
    print(f"  Reason: {volatile_result['reason']}")
    
    # Test Case 3: Enhanced Scoring Comparison
    print("\n3. Testing Enhanced Scoring:")
    print("-" * 30)
    
    test_scenarios = [
        {
            "name": "VERIFIED FLAT-TO-SPIKE",
            "alert_type": "flat_to_spike",
            "price": 0.85,
            "change_pct": 120.0,
            "relative_volume": 300.0,
            "sector": "Health Services"
        },
        {
            "name": "REGULAR PRICE SPIKE",
            "alert_type": "price_spike",
            "price": 0.85,
            "change_pct": 120.0,
            "relative_volume": 300.0,
            "sector": "Health Services"
        },
        {
            "name": "PREMARKET GAP",
            "alert_type": "premarket_price",
            "price": 0.85,
            "change_pct": 120.0,
            "relative_volume": 300.0,
            "sector": "Health Services"
        }
    ]
    
    for scenario in test_scenarios:
        result = analyze_winning_patterns_enhanced(
            scenario['price'],
            scenario['change_pct'],
            scenario['relative_volume'],
            scenario['sector'],
            scenario['alert_type']
        )
        
        print(f"{scenario['name']:25} | Score: {result['score']:3d} | "
              f"{result['probability_category']:9} ({result['estimated_probability']:4.1f}%)")
        print(f"  Flags: {', '.join(result['flags']) if result['flags'] else 'None'}")
    
    # Summary
    print(f"\n4. Test Results Summary:")
    print("-" * 30)
    print(f"✅ Flat Detection: {'PASS' if flat_result['is_flat'] else 'FAIL'} "
          f"(Volatility: {flat_result['flat_volatility']:.2f}% ≤ 3.0%)")
    print(f"✅ Volatile Detection: {'PASS' if not volatile_result['is_flat'] else 'FAIL'} "
          f"(Volatility: {volatile_result['flat_volatility']:.2f}% > 3.0%)")
    
    # Check scoring differences
    flat_to_spike_score = test_scenarios[0]
    regular_spike_score = test_scenarios[1] 
    premarket_score = test_scenarios[2]
    
    flat_score = analyze_winning_patterns_enhanced(
        flat_to_spike_score['price'], flat_to_spike_score['change_pct'], 
        flat_to_spike_score['relative_volume'], flat_to_spike_score['sector'], 
        flat_to_spike_score['alert_type'])['score']
    
    regular_score = analyze_winning_patterns_enhanced(
        regular_spike_score['price'], regular_spike_score['change_pct'],
        regular_spike_score['relative_volume'], regular_spike_score['sector'],
        regular_spike_score['alert_type'])['score']
    
    premarket_score_val = analyze_winning_patterns_enhanced(
        premarket_score['price'], premarket_score['change_pct'],
        premarket_score['relative_volume'], premarket_score['sector'],
        premarket_score['alert_type'])['score']
    
    print(f"✅ Scoring Priority: {'PASS' if flat_score > regular_score > premarket_score_val else 'FAIL'} "
          f"({flat_score} > {regular_score} > {premarket_score_val})")
    
    print(f"\n🎯 FLAT-TO-SPIKE ENHANCEMENT: {'WORKING CORRECTLY' if all([flat_result['is_flat'], not volatile_result['is_flat'], flat_score > regular_score]) else 'NEEDS ADJUSTMENT'}")

if __name__ == "__main__":
    test_flat_to_spike_detection()