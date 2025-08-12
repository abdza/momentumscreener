#!/usr/bin/env python3
"""
Simple test for the pattern analysis function
"""

def analyze_winning_patterns(current_price, change_pct, relative_volume, sector, alert_type="price_spike"):
    """Analyze alert against winning patterns and return probability score and flags"""
    flags = []
    score = 0
    probability_category = "LOW"
    
    # Price range analysis
    if current_price < 1:
        flags.append("🎯 Under $1")
        score += 20  # 12.1% success rate
    elif current_price < 2:
        flags.append("💎 Under $2") 
        score += 15  # 8.8% success rate
    elif current_price < 5:
        score += 5
    else:
        score -= 10  # Higher prices have lower success rates
    
    # Initial change percentage analysis
    if change_pct >= 200:
        flags.append("🚀 MEGA SPIKE 200%+")
        score += 50  # 27.3% success rate
    elif change_pct >= 100:
        flags.append("🔥 BIG SPIKE 100%+")
        score += 40  # 25.0% success rate
    elif change_pct >= 50:
        flags.append("⚡ STRONG 50%+")
        score += 25  # 14.0% success rate
    elif change_pct >= 25:
        score += 10  # 10.9% success rate
    else:
        score -= 5   # Lower changes have poor success rates
    
    # Relative volume analysis
    if relative_volume and relative_volume >= 500:
        flags.append("🌊 EXTREME VOL 500x+")
        score += 40  # 29.2% success rate
    elif relative_volume and relative_volume >= 100:
        flags.append("📈 HIGH VOL 100x+")
        score += 30  # 18.1% success rate
    elif relative_volume and relative_volume >= 20:
        flags.append("📊 GOOD VOL 20x+")
        score += 15  # 7.8% success rate
    elif relative_volume and relative_volume < 5:
        score -= 15  # Low volume has poor success rates
    
    # Sector analysis (best performing sectors)
    high_success_sectors = {
        "Health Services": 25.0,
        "Utilities": 16.7,
        "Distribution Services": 15.0,
        "Consumer Durables": 14.3,
        "Finance": 12.0
    }
    
    if sector in high_success_sectors:
        success_rate = high_success_sectors[sector]
        if success_rate >= 20:
            flags.append(f"💼 TOP SECTOR")
            score += 25
        elif success_rate >= 15:
            flags.append(f"🏭 GOOD SECTOR")
            score += 15
        elif success_rate >= 12:
            flags.append(f"📋 OK SECTOR")
            score += 10
    
    # Alert type analysis
    if alert_type == "price_spike":
        score += 10  # 11.9% success rate (best type)
    else:
        score -= 5   # Premarket alerts have lower success rates
    
    # Calculate probability category based on score
    if score >= 80:
        probability_category = "VERY HIGH"
    elif score >= 60:
        probability_category = "HIGH"
    elif score >= 40:
        probability_category = "MEDIUM"
    elif score >= 20:
        probability_category = "LOW"
    else:
        probability_category = "VERY LOW"
    
    # Estimate success probability percentage
    if score >= 80:
        estimated_probability = 25.0  # Top tier
    elif score >= 60:
        estimated_probability = 18.0  # High tier
    elif score >= 40:
        estimated_probability = 12.0  # Medium tier  
    elif score >= 20:
        estimated_probability = 8.0   # Low tier
    else:
        estimated_probability = 4.0   # Very low tier
    
    return {
        'flags': flags,
        'score': score,
        'probability_category': probability_category,
        'estimated_probability': estimated_probability
    }

def test_pattern_analysis():
    """Test the pattern analysis with sample data"""
    
    print("Testing Pattern Analysis Function")
    print("=" * 50)
    
    # Test cases based on real successful examples
    test_cases = [
        # High probability cases
        {
            "name": "MEGA WINNER (CYN-like)",
            "price": 5.01,
            "change_pct": 300.0,
            "relative_volume": 600.0,
            "sector": "Technology Services",
            "alert_type": "price_spike"
        },
        {
            "name": "VERY HIGH PROBABILITY",
            "price": 0.79,
            "change_pct": 150.0,
            "relative_volume": 400.0,
            "sector": "Health Services",
            "alert_type": "price_spike"
        },
        {
            "name": "HIGH PROBABILITY",
            "price": 1.24,
            "change_pct": 80.0,
            "relative_volume": 200.0,
            "sector": "Finance",
            "alert_type": "price_spike"
        },
        # Medium probability case
        {
            "name": "MEDIUM PROBABILITY",
            "price": 3.29,
            "change_pct": 45.0,
            "relative_volume": 50.0,
            "sector": "Consumer Durables",
            "alert_type": "price_spike"
        },
        # Low probability cases
        {
            "name": "LOW PROBABILITY",
            "price": 12.50,
            "change_pct": 15.0,
            "relative_volume": 10.0,
            "sector": "Process Industries",
            "alert_type": "premarket_price"
        },
        {
            "name": "VERY LOW PROBABILITY",
            "price": 25.00,
            "change_pct": 8.0,
            "relative_volume": 3.0,
            "sector": "Producer Manufacturing",
            "alert_type": "premarket_volume"
        }
    ]
    
    for test_case in test_cases:
        print(f"\n{test_case['name']}:")
        print(f"  Price: ${test_case['price']:.2f}")
        print(f"  Change: {test_case['change_pct']:.1f}%")
        print(f"  Volume: {test_case['relative_volume']:.1f}x")
        print(f"  Sector: {test_case['sector']}")
        print(f"  Alert Type: {test_case['alert_type']}")
        
        analysis = analyze_winning_patterns(
            test_case['price'],
            test_case['change_pct'],
            test_case['relative_volume'],
            test_case['sector'],
            test_case['alert_type']
        )
        
        print(f"  → Score: {analysis['score']}")
        print(f"  → Probability: {analysis['probability_category']} ({analysis['estimated_probability']:.1f}%)")
        print(f"  → Flags: {', '.join(analysis['flags']) if analysis['flags'] else 'None'}")
        print(f"  → {'🎯 PRIORITY ALERT!' if analysis['score'] >= 60 else '📊 Standard alert'}")
    
    print(f"\n{'='*50}")
    print("SAMPLE TELEGRAM MESSAGE FORMAT:")
    print("="*50)
    
    # Show example message format
    example = test_cases[1]  # Very high probability case
    analysis = analyze_winning_patterns(
        example['price'], example['change_pct'], example['relative_volume'], 
        example['sector'], example['alert_type']
    )
    
    pattern_flags_str = " ".join(analysis['flags']) if analysis['flags'] else "📊 Standard Alert"
    probability_str = f"{analysis['probability_category']} ({analysis['estimated_probability']:.1f}%)"
    
    sample_message = f"""🔥 HIGH FREQUENCY MOMENTUM ALERT 🔥

📊 Ticker: EXAMPLE
⚡ Alert Count: 3 times
💰 Current Price: ${example['price']:.2f} ({example['change_pct']:+.1f}%)
📈 Volume: 45,761,891
📊 Relative Volume: {example['relative_volume']:.1f}x
🏭 Sector: {example['sector']}

🎯 WIN PROBABILITY: {probability_str}
🚀 PATTERN FLAGS: {pattern_flags_str}

📋 This ticker has triggered 3 momentum alerts, indicating sustained bullish activity!
🎯 Alert Types: price_spike

📊 View Chart: https://www.tradingview.com/chart/?symbol=EXAMPLE"""

    print(sample_message)

if __name__ == "__main__":
    test_pattern_analysis()