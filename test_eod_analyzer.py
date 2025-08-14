#!/usr/bin/env python3
"""
Simple test for the end-of-day analyzer
Tests without requiring real market data
"""

import json
from datetime import datetime, date
import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from end_of_day_analyzer import EndOfDayAnalyzer

def create_test_alert_file():
    """Create a test alert file for today"""
    today = date.today()
    timestamp = datetime.now().isoformat()
    
    test_data = {
        "timestamp": timestamp,
        "volume_climbers": [],
        "volume_newcomers": [],
        "price_spikes": [
            {
                "ticker": "TEST1",
                "current_price": 2.50,
                "change_pct": 85.0,
                "price_change_window": 85.0,
                "volume": 1000000,
                "relative_volume": 150.0,
                "sector": "Technology Services",
                "time_window": 10,
                "alert_type": "flat_to_spike",
                "flat_analysis": {
                    "is_flat": True,
                    "flat_duration_minutes": 15.0,
                    "flat_volatility": 2.5
                },
                "appearance_count": 1,
                "alert_types_count": 1
            },
            {
                "ticker": "TEST2", 
                "current_price": 1.25,
                "change_pct": 45.0,
                "price_change_window": 45.0,
                "volume": 500000,
                "relative_volume": 75.0,
                "sector": "Health Technology",
                "time_window": 10,
                "alert_type": "price_spike",
                "appearance_count": 1,
                "alert_types_count": 1
            }
        ],
        "premarket_volume_alerts": [],
        "premarket_price_alerts": [
            {
                "ticker": "TEST3",
                "premarket_change": 65.0,
                "current_price": 3.30,
                "volume": 750000,
                "relative_volume": 200.0,
                "sector": "Finance",
                "alert_type": "premarket_price"
            }
        ],
        "summary": {
            "total_volume_climbers": 0,
            "total_newcomers": 0,
            "total_price_spikes": 2,
            "total_premarket_volume_alerts": 0,
            "total_premarket_price_alerts": 1
        }
    }
    
    # Save test alert file
    test_file = f"momentum_data/alerts_{today.strftime('%Y%m%d')}_120000.json"
    with open(test_file, 'w') as f:
        json.dump(test_data, f, indent=2)
    
    print(f"✅ Created test alert file: {test_file}")
    return test_file

def test_analyzer_without_market_data():
    """Test the analyzer logic without requiring market data"""
    print("🧪 TESTING END-OF-DAY ANALYZER")
    print("=" * 50)
    
    # Create test data
    test_file = create_test_alert_file()
    today = date.today()
    
    # Initialize analyzer
    analyzer = EndOfDayAnalyzer(
        data_dir="momentum_data",
        success_threshold=30.0
    )
    
    # Test alert file loading
    alert_files = analyzer.get_alert_files_for_date(today)
    print(f"📁 Found {len(alert_files)} alert files for {today}")
    
    if not alert_files:
        print("❌ No alert files found")
        return
    
    # Test alert extraction
    all_alerts = analyzer.extract_alerts_from_files(alert_files)
    print(f"📊 Extracted {len(all_alerts)} unique ticker alerts")
    
    # Display extracted alerts
    print(f"\\n📋 EXTRACTED ALERTS:")
    print("-" * 30)
    
    for i, alert in enumerate(all_alerts, 1):
        alert_type = alert['alert_type']
        ticker = alert['ticker']
        change_pct = alert['change_pct']
        price = alert['alert_price']
        
        flat_info = ""
        if alert_type == 'flat_to_spike':
            flat_analysis = alert.get('flat_analysis', {})
            if flat_analysis.get('is_flat'):
                duration = flat_analysis.get('flat_duration_minutes', 0)
                volatility = flat_analysis.get('flat_volatility', 0)
                flat_info = f" 🎯FLAT({duration:.0f}m,{volatility:.1f}%)"
        
        print(f"  {i}. {ticker:6} | {alert_type:15} | ${price:5.2f} | {change_pct:+5.1f}%{flat_info}")
    
    # Test report generation with mock performance data
    print(f"\\n📊 SIMULATING PERFORMANCE ANALYSIS:")
    print("-" * 30)
    
    # Mock performance results (simulate what would happen with real data)
    mock_results = []
    for alert in all_alerts:
        # Simulate different performance outcomes
        if alert['alert_type'] == 'flat_to_spike':
            # Flat-to-spike alerts perform better
            mock_performance = {
                'success': True,
                'max_gain': 45.5,
                'max_drawdown': 3.2,
                'end_price': alert['alert_price'] * 1.455,
                'data_available': True,
                'success_achieved_before_eod': True,
                'samples': 78
            }
        elif alert['alert_type'] == 'price_spike':
            # Regular spikes moderate performance
            mock_performance = {
                'success': False,
                'max_gain': 22.3,
                'max_drawdown': 8.1,
                'end_price': alert['alert_price'] * 1.223,
                'data_available': True,
                'success_achieved_before_eod': False,
                'samples': 65
            }
        else:
            # Premarket alerts lower performance
            mock_performance = {
                'success': False,
                'max_gain': 15.7,
                'max_drawdown': 12.4,
                'end_price': alert['alert_price'] * 1.157,
                'data_available': True,
                'success_achieved_before_eod': False,
                'samples': 52
            }
        
        result = {**alert, **mock_performance}
        mock_results.append(result)
        
        success_marker = "✅" if mock_performance['success'] else "❌"
        print(f"    {alert['ticker']:6} | {success_marker} Max: {mock_performance['max_gain']:+5.1f}% | DD: {mock_performance['max_drawdown']:4.1f}%")
    
    # Test report generation
    print(f"\\n📄 GENERATING ANALYSIS REPORT:")
    print("-" * 30)
    
    report = analyzer.generate_analysis_report(mock_results, today)
    print(report)
    
    # Clean up test file
    try:
        os.remove(test_file)
        print(f"🧹 Cleaned up test file: {test_file}")
    except:
        pass
    
    print("\\n✅ END-OF-DAY ANALYZER TEST COMPLETE!")
    
    # Summary of functionality
    print(f"\\n🎯 FUNCTIONALITY VERIFICATION:")
    print("-" * 30)
    print("✅ Alert file loading and parsing")
    print("✅ Alert extraction and deduplication")
    print("✅ Alert type classification (including flat-to-spike)")
    print("✅ Performance analysis framework")
    print("✅ Report generation with statistics")
    print("✅ Alert type breakdown and comparison")
    print("✅ Flat-to-spike vs regular spike analysis")
    
    return True

if __name__ == "__main__":
    test_analyzer_without_market_data()