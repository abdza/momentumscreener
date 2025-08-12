#!/usr/bin/env python3
"""
Test script for the pattern analysis function
"""

import sys
sys.path.append('.')

from volume_momentum_tracker import VolumeMomentumTracker

def test_pattern_analysis():
    """Test the pattern analysis with sample data"""
    tracker = VolumeMomentumTracker()
    
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
        
        analysis = tracker._analyze_winning_patterns(
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

if __name__ == "__main__":
    test_pattern_analysis()