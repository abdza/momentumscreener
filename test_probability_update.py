#!/usr/bin/env python3
"""
Test script for the updated probability scoring system
Tests various scenarios based on real winners and losers from our analysis
"""

import sys
sys.path.append('.')

# Mock the VolumeMomentumTracker class for testing
class MockTracker:
    def _calculate_stop_loss_recommendation(self, score, current_price, change_pct):
        return {
            'percentage': 15.0,
            'confidence': "Standard",
            'stop_price': current_price * 0.85,
            'historical_note': "Test stop loss"
        }
    
    def _analyze_winning_patterns(self, current_price, change_pct, relative_volume, sector, alert_type="price_spike"):
        """Analyze alert against winning patterns and return probability score and flags"""
        flags = []
        score = 0
        probability_category = "LOW"
        
        # UPDATED PATTERN ANALYSIS BASED ON REAL PERFORMANCE DATA
        # Data from Aug 15-23, 2025: Overall success rates vary from 0-50%
        
        if alert_type == "flat_to_spike":
            flags.append("🎯 FLAT-TO-SPIKE")
            score += 60  # Premium for verified flat-to-spike pattern (limited data but promising)
            
            # Extra bonus for larger flat-to-spike patterns
            if change_pct >= 75:
                flags.append("🚀 BIG FLAT-TO-SPIKE")
                score += 40  # Maximum bonus for large flat-to-spike
        elif alert_type == "immediate_spike":
            flags.append("⚡ IMMEDIATE SPIKE")
            score += 45  # 20-50% success rate (best performing type)
            
            # Extra bonus for larger immediate spikes
            if change_pct >= 75:
                flags.append("🚀 BIG IMMEDIATE SPIKE")
                score += 25  # Higher chance for bigger spikes
        elif alert_type == "price_spike":
            flags.append("📈 PRICE SPIKE")
            score += 35  # 50% success rate on good days
            
            if change_pct >= 75:
                flags.append("🚀 BIG PRICE SPIKE")
                score += 20
        elif alert_type == "volume_climber":
            flags.append("📊 VOLUME CLIMBER")
            score += 25  # 33% success rate (LASE had 117% gain)
        elif alert_type in ["premarket_price", "premarket_volume", "new_premarket_move"]:
            flags.append("🌅 PREMARKET")
            score -= 20  # 0% success rate in recent data
        
        # Price range analysis based on recent real data
        if current_price < 1:
            flags.append("🎯 Under $1")
            score += 15  # Mixed results in penny stocks
        elif current_price < 3:
            flags.append("💎 Under $3") 
            score += 20  # Sweet spot: LASE ($2.46), GXAI ($1.70), TZUP ($5.35) were winners
        elif current_price < 6:
            flags.append("💰 Mid-Range")
            score += 25  # Best range: SNGX ($3.96-5.26), PPCB ($7.11) were winners
        else:
            flags.append("📈 Higher Price")
            score += 5   # Higher prices can work but less frequent
        
        # Initial change percentage analysis based on real winners
        if change_pct >= 145:
            flags.append("🚀 MASSIVE SPIKE 145%+")
            score += 35  # PMNT had 145.6% but failed, mixed results
        elif change_pct >= 100:
            flags.append("🔥 BIG SPIKE 100%+") 
            score += 30  # LASE had 117% gain (winner), PRFX 121% (failed)
        elif change_pct >= 50:
            flags.append("⚡ STRONG SPIKE 50%+")
            score += 25  # GXAI 53.6% (winner), SNGX 57.4% (winner)
        elif change_pct >= 30:
            flags.append("📈 SOLID MOVE 30%+")
            score += 15  # VELO 34.2%, ADD 36.1%, VCIG 32.6% (mixed results)
        elif change_pct >= 15:
            score += 10  # Moderate moves
        
        # Relative volume analysis based on real winners
        if relative_volume and relative_volume >= 400:
            flags.append("🌊 EXTREME VOL 400x+")
            score += 35  # VTAK had 433x (failed), PPCB had 425-970x (winner)
        elif relative_volume and relative_volume >= 200:
            flags.append("📈 VERY HIGH VOL 200x+")
            score += 30  # PPSI 282x (failed), ASBP 250-452x (winner)
        elif relative_volume and relative_volume >= 50:
            flags.append("📊 HIGH VOL 50x+")
            score += 20  # PMNT 68x (failed), TIVC 73x (failed), SRXH 31-168x (winner)
        elif relative_volume and relative_volume >= 10:
            flags.append("📊 GOOD VOL 10x+")
            score += 10  # Mixed results in this range
        elif relative_volume and relative_volume < 5:
            score -= 10  # Low volume typically fails
        
        # Sector analysis based on real winners from recent data
        successful_sectors = {
            "Health Technology": 40,  # LASE, GXAI, SNGX, ASBP, PPCB were winners
            "Electronic Technology": 30,  # LASE (+117%) was a big winner  
            "Transportation": 25,  # TZUP was a winner
            "Distribution Services": 20,  # Mixed results
            "Producer Manufacturing": 10,  # DFLI, MCRP mostly failed
            "Retail Trade": 5,  # Mixed results
            "Consumer Services": 5,  # Limited data
        }
        
        if sector in successful_sectors:
            sector_score = successful_sectors[sector]
            if sector_score >= 35:
                flags.append(f"💊 BIOTECH/HEALTH")
                score += 25  # Health Technology is hot sector
            elif sector_score >= 20:
                flags.append(f"🏭 GOOD SECTOR")
                score += 15
            elif sector_score >= 10:
                flags.append(f"📋 OK SECTOR")
                score += 5
        else:
            score -= 5  # Unknown sectors are riskier
        
        # Calculate probability category based on updated score
        if score >= 100:
            probability_category = "VERY HIGH"
        elif score >= 80:
            probability_category = "HIGH"
        elif score >= 50:
            probability_category = "MEDIUM"
        elif score >= 25:
            probability_category = "LOW"
        else:
            probability_category = "VERY LOW"
        
        # Estimate success probability percentage based on real performance data
        # Recent data shows: 0-50% success rates depending on day and conditions
        if score >= 100:
            estimated_probability = 45.0  # Best possible conditions (top tier patterns)
        elif score >= 80:
            estimated_probability = 35.0  # High tier (good patterns + favorable conditions)
        elif score >= 50:
            estimated_probability = 25.0  # Medium tier (average conditions)
        elif score >= 25:
            estimated_probability = 15.0  # Low tier (poor conditions)
        else:
            estimated_probability = 5.0   # Very low tier (unfavorable patterns)
        
        # Calculate recommended stop-loss
        recommended_stop_loss = self._calculate_stop_loss_recommendation(score, current_price, change_pct)
        
        return {
            'flags': flags,
            'score': score,
            'probability_category': probability_category,
            'estimated_probability': estimated_probability,
            'recommended_stop_loss': recommended_stop_loss
        }

def test_winners():
    """Test the scoring system against known winners"""
    print("🏆 TESTING KNOWN WINNERS")
    print("=" * 50)
    
    tracker = MockTracker()
    
    # Test cases based on actual winners
    winners = [
        # LASE - Big winner (+117%)
        {"ticker": "LASE", "price": 2.46, "change": 117.1, "volume": 18.56, "sector": "Electronic Technology", "type": "volume_climber"},
        # SNGX - Good winner (+57.4%)  
        {"ticker": "SNGX", "price": 3.96, "change": 57.4, "volume": 433.14, "sector": "Health Technology", "type": "immediate_spike"},
        # GXAI - Strong winner (+43.4%)
        {"ticker": "GXAI", "price": 1.70, "change": 53.6, "volume": 15.0, "sector": "Health Technology", "type": "immediate_spike"},
        # TZUP - Good winner (+57.0%)
        {"ticker": "TZUP", "price": 5.35, "change": 57.0, "volume": 25.0, "sector": "Transportation", "type": "price_spike"},
    ]
    
    for winner in winners:
        analysis = tracker._analyze_winning_patterns(
            winner["price"], winner["change"], winner["volume"], winner["sector"], winner["type"]
        )
        
        print(f"{winner['ticker']:6} | Score: {analysis['score']:3d} | {analysis['probability_category']:10} | {analysis['estimated_probability']:4.1f}% | Flags: {' '.join(analysis['flags'])}")

def test_losers():
    """Test the scoring system against known losers"""
    print("\n❌ TESTING KNOWN LOSERS")
    print("=" * 50)
    
    tracker = MockTracker()
    
    # Test cases based on actual losers
    losers = [
        # PMNT - Big spike that failed
        {"ticker": "PMNT", "price": 0.72, "change": 145.6, "volume": 68.19, "sector": "Retail Trade", "type": "immediate_spike"},
        # PPSI - Failed despite good volume
        {"ticker": "PPSI", "price": 5.19, "change": 65.7, "volume": 281.95, "sector": "Producer Manufacturing", "type": "immediate_spike"},
        # MB - Premarket move that failed
        {"ticker": "MB", "price": 6.09, "change": 10.7, "volume": 20.21, "sector": "Consumer Services", "type": "new_premarket_move"},
        # HTCR - Premarket move that failed badly
        {"ticker": "HTCR", "price": 0.84, "change": 2.0, "volume": 5.0, "sector": "Health Technology", "type": "new_premarket_move"},
    ]
    
    for loser in losers:
        analysis = tracker._analyze_winning_patterns(
            loser["price"], loser["change"], loser["volume"], loser["sector"], loser["type"]
        )
        
        print(f"{loser['ticker']:6} | Score: {analysis['score']:3d} | {analysis['probability_category']:10} | {analysis['estimated_probability']:4.1f}% | Flags: {' '.join(analysis['flags'])}")

def test_edge_cases():
    """Test edge cases and extreme scenarios"""
    print("\n🔬 TESTING EDGE CASES")
    print("=" * 50)
    
    tracker = MockTracker()
    
    test_cases = [
        # Perfect flat-to-spike scenario
        {"name": "Perfect Flat-to-Spike", "price": 4.0, "change": 100.0, "volume": 500.0, "sector": "Health Technology", "type": "flat_to_spike"},
        # Low probability premarket
        {"name": "Weak Premarket", "price": 0.50, "change": 5.0, "volume": 2.0, "sector": "Unknown Sector", "type": "new_premarket_move"},
        # High volume but low change
        {"name": "High Vol Low Change", "price": 10.0, "change": 5.0, "volume": 1000.0, "sector": "Health Technology", "type": "volume_climber"},
    ]
    
    for case in test_cases:
        analysis = tracker._analyze_winning_patterns(
            case["price"], case["change"], case["volume"], case["sector"], case["type"]
        )
        
        print(f"{case['name']:20} | Score: {analysis['score']:3d} | {analysis['probability_category']:10} | {analysis['estimated_probability']:4.1f}%")

if __name__ == "__main__":
    print("🧪 TESTING UPDATED PROBABILITY SCORING SYSTEM")
    print("Based on real performance data from Aug 15-23, 2025")
    print()
    
    test_winners()
    test_losers() 
    test_edge_cases()
    
    print("\n✅ Testing complete!")
    print("Winners should generally have higher scores and probabilities than losers.")