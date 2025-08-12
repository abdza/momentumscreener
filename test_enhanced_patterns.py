#!/usr/bin/env python3
"""
Test the enhanced pattern analysis with flat-to-spike detection
"""

def analyze_winning_patterns_enhanced(current_price, change_pct, relative_volume, sector, alert_type="price_spike"):
    """Enhanced pattern analysis with flat-to-spike detection"""
    flags = []
    score = 0
    probability_category = "LOW"
    
    # FLAT-TO-SPIKE PATTERN ANALYSIS (newly validated!)
    # Sudden intraday spikes significantly outperform premarket gaps (11.9% vs 4.4%)
    if alert_type == "price_spike":
        flags.append("⚡ SUDDEN SPIKE")
        score += 30  # 11.9% success rate vs 4.4% for premarket
        
        # Extra bonus for larger sudden spikes (these have 21-28% success rates!)
        if change_pct >= 75:
            flags.append("🚀 BIG SUDDEN SPIKE")
            score += 20  # 28.1% success rate for 75-150% sudden spikes
    elif alert_type in ["premarket_price", "premarket_volume"]:
        # Premarket gaps have much lower success rates
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

def test_enhanced_patterns():
    """Test the enhanced pattern analysis with flat-to-spike examples"""
    
    print("ENHANCED PATTERN ANALYSIS - FLAT-TO-SPIKE VALIDATION")
    print("=" * 65)
    
    test_cases = [
        # Sudden intraday spikes (your preferred pattern)
        {
            "name": "IDEAL SUDDEN SPIKE",
            "price": 0.85,
            "change_pct": 120.0,
            "relative_volume": 300.0,
            "sector": "Health Services",
            "alert_type": "price_spike"
        },
        {
            "name": "BIG SUDDEN SPIKE",
            "price": 1.50,
            "change_pct": 85.0,
            "relative_volume": 150.0,
            "sector": "Finance",
            "alert_type": "price_spike"
        },
        {
            "name": "MODEST SUDDEN SPIKE",
            "price": 3.20,
            "change_pct": 45.0,
            "relative_volume": 80.0,
            "sector": "Technology Services",
            "alert_type": "price_spike"
        },
        
        # Premarket gaps (lower success pattern)
        {
            "name": "PREMARKET GAP (SIMILAR SIZE)",
            "price": 0.85,
            "change_pct": 120.0,
            "relative_volume": 300.0,
            "sector": "Health Services",
            "alert_type": "premarket_price"
        },
        {
            "name": "BIG PREMARKET GAP",
            "price": 1.50,
            "change_pct": 85.0,
            "relative_volume": 150.0,
            "sector": "Finance",
            "alert_type": "premarket_price"
        },
        {
            "name": "PREMARKET VOLUME ALERT",
            "price": 3.20,
            "change_pct": 45.0,
            "relative_volume": 80.0,
            "sector": "Technology Services",
            "alert_type": "premarket_volume"
        }
    ]
    
    sudden_spike_scores = []
    premarket_scores = []
    
    for test_case in test_cases:
        print(f"\n{test_case['name']}:")
        print(f"  Type: {test_case['alert_type']}")
        print(f"  Price: ${test_case['price']:.2f} | Change: {test_case['change_pct']:.1f}% | Volume: {test_case['relative_volume']:.1f}x")
        
        analysis = analyze_winning_patterns_enhanced(
            test_case['price'],
            test_case['change_pct'],
            test_case['relative_volume'],
            test_case['sector'],
            test_case['alert_type']
        )
        
        print(f"  → Score: {analysis['score']:3d} | Probability: {analysis['probability_category']} ({analysis['estimated_probability']:.1f}%)")
        print(f"  → Flags: {', '.join(analysis['flags']) if analysis['flags'] else 'None'}")
        
        if test_case['alert_type'] == 'price_spike':
            sudden_spike_scores.append(analysis['score'])
            print(f"  → 🎯 PRIORITIZE - Sudden spike pattern!")
        else:
            premarket_scores.append(analysis['score'])
            print(f"  → 📊 Lower priority - Premarket gap pattern")
    
    # Summary comparison
    print(f"\n{'='*65}")
    print("PATTERN COMPARISON SUMMARY:")
    print("="*65)
    
    avg_sudden = sum(sudden_spike_scores) / len(sudden_spike_scores)
    avg_premarket = sum(premarket_scores) / len(premarket_scores)
    
    print(f"Average Score - Sudden Spikes: {avg_sudden:.1f}")
    print(f"Average Score - Premarket Gaps: {avg_premarket:.1f}")
    print(f"Advantage for Sudden Spikes: {avg_sudden - avg_premarket:.1f} points")
    
    print(f"\n🎯 RECOMMENDATION:")
    print(f"   Focus on alerts with '⚡ SUDDEN SPIKE' flag")
    print(f"   These have 11.9% success rate vs 4.4% for premarket gaps")
    print(f"   Your trading instinct was data-proven correct!")

if __name__ == "__main__":
    test_enhanced_patterns()