#!/usr/bin/env python3
"""
Test the complete enhanced alert system with stop-loss recommendations
"""

def analyze_winning_patterns_complete(current_price, change_pct, relative_volume, sector, alert_type="price_spike"):
    """Complete enhanced pattern analysis with stop-loss recommendations"""
    flags = []
    score = 0
    probability_category = "LOW"
    
    # FLAT-TO-SPIKE PATTERN ANALYSIS (validated!)
    if alert_type == "price_spike":
        flags.append("⚡ SUDDEN SPIKE")
        score += 30  # 11.9% success rate vs 4.4% for premarket
        
        if change_pct >= 75:
            flags.append("🚀 BIG SUDDEN SPIKE")
            score += 20  # 28.1% success rate for 75-150% sudden spikes
    elif alert_type in ["premarket_price", "premarket_volume"]:
        score -= 15  # Penalty for premarket gaps (4.4% success rate)
    
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
    
    # Sector analysis
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
    
    # Calculate probability category
    if score >= 80:
        probability_category = "VERY HIGH"
        estimated_probability = 25.0
    elif score >= 60:
        probability_category = "HIGH"
        estimated_probability = 18.0
    elif score >= 40:
        probability_category = "MEDIUM"
        estimated_probability = 12.0
    elif score >= 20:
        probability_category = "LOW"
        estimated_probability = 8.0
    else:
        probability_category = "VERY LOW"
        estimated_probability = 4.0
    
    # Calculate stop-loss recommendation
    # Based on analysis: 87.9% of winners never dropped below alert price
    # Maximum drawdown: 12.0%, Optimal stop-loss: 15%
    
    if score >= 80:
        # Very high probability - can be more aggressive
        adjusted_stop_loss = 10.0
        confidence = "High confidence - tight stop"
    elif score >= 60:
        # High probability - standard recommendation
        adjusted_stop_loss = 12.0
        confidence = "Good confidence - moderate stop"
    elif score >= 40:
        # Medium probability - slightly more conservative
        adjusted_stop_loss = 15.0
        confidence = "Standard confidence - safe stop"
    else:
        # Low probability - more conservative
        adjusted_stop_loss = 20.0
        confidence = "Low confidence - wide stop"
    
    # Adjust for price characteristics
    if current_price < 1.0:
        adjusted_stop_loss += 5.0
        confidence += " (penny stock adjustment)"
    elif current_price > 20.0:
        adjusted_stop_loss -= 3.0
        confidence += " (high price adjustment)"
    
    # Ensure bounds
    adjusted_stop_loss = max(8.0, min(25.0, adjusted_stop_loss))
    
    recommended_stop_loss = {
        'percentage': adjusted_stop_loss,
        'confidence': confidence,
        'stop_price': current_price * (1 - adjusted_stop_loss / 100),
        'historical_note': "87.9% of winners never dropped below alert price"
    }
    
    return {
        'flags': flags,
        'score': score,
        'probability_category': probability_category,
        'estimated_probability': estimated_probability,
        'recommended_stop_loss': recommended_stop_loss
    }

def test_complete_system():
    """Test the complete enhanced system with real examples"""
    
    print("COMPLETE ENHANCED ALERT SYSTEM TEST")
    print("=" * 65)
    print("Features: Pattern Recognition + Flat-to-Spike Detection + Stop-Loss Recommendations")
    print("Based on analysis of 948 alerts with 7% success rate")
    print()
    
    test_cases = [
        {
            "name": "🏆 IDEAL WINNER PATTERN",
            "price": 0.85,
            "change_pct": 120.0,
            "relative_volume": 400.0,
            "sector": "Health Services",
            "alert_type": "price_spike"
        },
        {
            "name": "🔥 BIG SUDDEN SPIKE",
            "price": 1.50,
            "change_pct": 85.0,
            "relative_volume": 200.0,
            "sector": "Finance",
            "alert_type": "price_spike"
        },
        {
            "name": "📊 MODEST SUDDEN SPIKE",
            "price": 3.20,
            "change_pct": 35.0,
            "relative_volume": 50.0,
            "sector": "Technology Services",
            "alert_type": "price_spike"
        },
        {
            "name": "❌ PREMARKET GAP (AVOID)",
            "price": 8.50,
            "change_pct": 45.0,
            "relative_volume": 25.0,
            "sector": "Process Industries",
            "alert_type": "premarket_price"
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        analysis = analyze_winning_patterns_complete(
            test_case['price'],
            test_case['change_pct'],
            test_case['relative_volume'],
            test_case['sector'],
            test_case['alert_type']
        )
        
        print(f"{i}. {test_case['name']}")
        print(f"   Price: ${test_case['price']:.2f} | Change: {test_case['change_pct']:.1f}% | Vol: {test_case['relative_volume']:.0f}x")
        print(f"   Alert Type: {test_case['alert_type']} | Sector: {test_case['sector']}")
        print()
        print(f"   📊 ANALYSIS RESULTS:")
        print(f"   Score: {analysis['score']:3d} | Probability: {analysis['probability_category']} ({analysis['estimated_probability']:.1f}%)")
        print(f"   Flags: {', '.join(analysis['flags']) if analysis['flags'] else 'None'}")
        print()
        print(f"   🛑 STOP-LOSS RECOMMENDATION:")
        stop = analysis['recommended_stop_loss']
        print(f"   {stop['percentage']:.1f}% stop (${stop['stop_price']:.2f}) | {stop['confidence']}")
        print(f"   Historical: {stop['historical_note']}")
        
        # Generate sample telegram message
        pattern_flags_str = " ".join(analysis['flags']) if analysis['flags'] else "📊 Standard Alert"
        probability_str = f"{analysis['probability_category']} ({analysis['estimated_probability']:.1f}%)"
        stop_loss_str = f"{stop['percentage']:.1f}% (${stop['stop_price']:.2f})"
        
        print(f"\n   📱 TELEGRAM MESSAGE PREVIEW:")
        print("   " + "-" * 50)
        
        sample_message = f"""🔥 HIGH FREQUENCY MOMENTUM ALERT 🔥

📊 Ticker: EXAMPLE
⚡ Alert Count: 3 times
💰 Current Price: ${test_case['price']:.2f} ({test_case['change_pct']:+.1f}%)
📈 Volume: 15,234,567
📊 Relative Volume: {test_case['relative_volume']:.1f}x
🏭 Sector: {test_case['sector']}

🎯 WIN PROBABILITY: {probability_str}
🚀 PATTERN FLAGS: {pattern_flags_str}
🛑 RECOMMENDED STOP: {stop_loss_str}

📋 This ticker has triggered 3 momentum alerts!
📊 View Chart: https://www.tradingview.com/chart/?symbol=EXAMPLE"""

        # Indent the message
        for line in sample_message.split('\n'):
            print(f"   {line}")
        
        print(f"\n   🎯 RECOMMENDATION: {'🟢 PRIORITIZE' if analysis['score'] >= 60 else '🟡 STANDARD' if analysis['score'] >= 20 else '🔴 AVOID'}")
        print()
        print("=" * 65)
        print()
    
    print("KEY INSIGHTS FROM COMPLETE SYSTEM:")
    print("=" * 65)
    print("✅ Sudden spikes (⚡) have 11.9% success vs 4.4% for premarket gaps")
    print("✅ 87.9% of winners never dropped below alert price") 
    print("✅ Maximum observed drawdown: 12.0%")
    print("✅ Optimal stop-loss varies by pattern strength: 10-20%")
    print("✅ System automatically prioritizes highest probability alerts")
    print()
    print("🎯 TRADING WORKFLOW:")
    print("1. Receive alert with probability assessment")
    print("2. Check pattern flags for sudden spike indicators")
    print("3. Set stop-loss at recommended level")
    print("4. Target 30%+ gains based on historical success patterns")

if __name__ == "__main__":
    test_complete_system()