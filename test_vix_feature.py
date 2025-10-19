#!/usr/bin/env python3
"""
Test VIX feature for telegram notifications
"""

from volume_momentum_tracker import VolumeMomentumTracker

# Create tracker instance (without telegram credentials for testing)
tracker = VolumeMomentumTracker()

# Test VIX data fetching
print("Testing VIX data fetching...")
print("="*60)

vix_data = tracker._get_vix_data()

if vix_data:
    print(f"✅ VIX data fetched successfully!")
    print(f"\nVIX Details:")
    print(f"  Current Value: {vix_data['current']:.2f}")
    print(f"  Week Change: {vix_data['week_change']:+.1f}%")
    print(f"  Week Trend: {vix_data['week_trend']}")
    print(f"  Volatility Level: {vix_data['level']}")

    # Test emoji mapping
    vix_emoji = {
        'low': '🟢',
        'moderate': '🟡',
        'elevated': '🟠',
        'high': '🔴'
    }.get(vix_data['level'], '⚪')

    trend_emoji = '📈' if vix_data['week_trend'] == 'rising' else '📉'

    print(f"\n📊 Formatted for Telegram:")
    print(f"VIX: {vix_emoji} {vix_data['current']:.2f} "
          f"({trend_emoji} {vix_data['week_trend']} {vix_data['week_change']:+.1f}% this week, "
          f"{vix_data['level']} volatility)")

    # Test caching
    print(f"\n🔄 Testing cache...")
    vix_data2 = tracker._get_vix_data()
    if vix_data2 == vix_data:
        print("✅ Cache working correctly!")
    else:
        print("⚠️  Cache may not be working")

else:
    print("❌ Failed to fetch VIX data")

print("\n" + "="*60)
print("Test complete!")
