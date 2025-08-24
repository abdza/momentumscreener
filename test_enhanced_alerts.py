#!/usr/bin/env python3
"""
Test script to show enhanced alerts with position sizing recommendations
"""

import sys
sys.path.append('.')

def test_alert_format():
    """Test what the enhanced alert messages look like"""
    print("🧪 TESTING ENHANCED ALERT FORMAT")
    print("=" * 60)
    print("Simulating what alerts will look like with market sentiment integration")
    print()

    # Sample data based on a real winner (SNGX from Aug 18)
    ticker = "SNGX"
    current_price = 3.96
    change_pct = 57.4
    volume = 32718211
    relative_volume = 433.1
    sector = "Health Technology"
    alert_count = 1
    is_immediate_spike = True
    
    # Sample pattern analysis (simplified)
    probability_str = "HIGH (35.0%)"
    pattern_flags_str = "⚡ IMMEDIATE SPIKE 💰 Mid-Range ⚡ STRONG SPIKE 50%+ 🌊 EXTREME VOL 400x+ 💊 BIOTECH/HEALTH"
    stop_loss_str = "12.0% ($3.48)"
    target_str = "30.0% ($5.15)"
    
    # Sample market sentiment data (current excellent conditions)
    position_recommendation = "🚀 LARGE: Consider 1.5-2x normal position size"
    market_score = 83
    market_category = "EXCELLENT"
    
    # Format relative volume display
    rel_vol_str = f"{relative_volume:.1f}x"
    
    # TradingView link
    tradingview_link = f"https://www.tradingview.com/chart/?symbol={ticker}"
    
    # Create enhanced alert message
    enhanced_message = (
        f"🚨 IMMEDIATE BIG SPIKE ALERT! 🚨\n\n"
        f"📊 Ticker: {ticker}\n"
        f"⚡ MASSIVE SPIKE: {change_pct:+.1f}% (≥30%)\n"
        f"💰 Current Price: ${current_price:.2f}\n"
        f"📈 Volume: {volume:,}\n"
        f"📊 Relative Volume: {rel_vol_str}\n"
        f"🏭 Sector: {sector}\n\n"
        f"🎯 WIN PROBABILITY: {probability_str}\n"
        f"🚀 PATTERN FLAGS: {pattern_flags_str}\n"
        f"🛑 RECOMMENDED STOP: {stop_loss_str}\n"
        f"🎯 TARGET PRICE: {target_str}\n"
        f"💰 POSITION SIZE: {position_recommendation}\n"
        f"📊 MARKET CONDITIONS: {market_score}/100 ({market_category})\n\n"
        f"🔥 This ticker just spiked {change_pct:+.1f}% - immediate alert triggered!\n"
        f"📈 Previous alerts: {alert_count}\n\n"
        f"📊 View Chart: {tradingview_link}"
    )
    
    print("🚀 SAMPLE ENHANCED ALERT (Excellent Market Conditions):")
    print("-" * 60)
    print(enhanced_message)
    print()
    
    # Now show what it looks like in poor market conditions
    print("🛑 SAMPLE ENHANCED ALERT (Poor Market Conditions):")
    print("-" * 60)
    
    poor_market_message = enhanced_message.replace(
        "💰 POSITION SIZE: 🚀 LARGE: Consider 1.5-2x normal position size",
        "💰 POSITION SIZE: 🛑 MINIMAL: Avoid or paper trade only"
    ).replace(
        "📊 MARKET CONDITIONS: 83/100 (EXCELLENT)",
        "📊 MARKET CONDITIONS: 35/100 (POOR)"
    )
    
    print(poor_market_message)
    print()
    
    print("💡 KEY ENHANCEMENTS:")
    print("✅ Position sizing recommendations based on real-time market conditions")
    print("✅ Market sentiment score (0-100) with category")  
    print("✅ Dynamic position sizing: MINIMAL → SMALL → NORMAL → LARGE")
    print("✅ Based on 0.988 correlation with small cap outperformance")
    print("✅ Helps manage risk and optimize position sizing")

def test_market_conditions_scenarios():
    """Show different scenarios based on market conditions"""
    print("\n🎯 POSITION SIZING SCENARIOS")
    print("=" * 60)
    
    scenarios = [
        {"score": 85, "category": "EXCELLENT", "recommendation": "🚀 LARGE: Consider 1.5-2x normal position size"},
        {"score": 70, "category": "GOOD", "recommendation": "✅ NORMAL: Standard position size"},
        {"score": 55, "category": "FAIR", "recommendation": "⚠️  SMALL: Reduce to 0.5x position size"},
        {"score": 30, "category": "POOR", "recommendation": "🛑 MINIMAL: Avoid or paper trade only"},
    ]
    
    for scenario in scenarios:
        print(f"Score {scenario['score']:2d}/100 ({scenario['category']:9}) → {scenario['recommendation']}")
    
    print(f"\n📊 Current Real Market Conditions:")
    try:
        from market_sentiment_scorer import MarketSentimentScorer
        scorer = MarketSentimentScorer()
        current_score = scorer.get_current_market_sentiment_score()
        print(f"Score: {current_score['score']}/100 ({current_score['category']})")
        print(f"Recommendation: {current_score['recommendation']}")
    except Exception as e:
        print(f"Unable to get current conditions: {e}")

if __name__ == "__main__":
    test_alert_format()
    test_market_conditions_scenarios()
    
    print(f"\n✅ Enhanced alerts are now ready!")
    print("🚀 Run volume_momentum_tracker.py to see live alerts with position sizing")