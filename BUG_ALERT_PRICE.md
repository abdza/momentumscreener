# Critical Bug: Incorrect Alert Price in Telegram Notifications [FIXED]

## Problem Summary

The `alert_price` being logged in `telegram_alerts_sent.jsonl` **was incorrect** for premarket alerts. It used the **previous day's close** instead of the **actual current premarket price**, leading to completely wrong gain calculations.

**STATUS: FIXED** - Both `volume_momentum_tracker.py` and `end_of_day_analyzer.py` have been updated.

## Example: BIYA on Nov 6, 2025

### What Was Logged:
- Alert time: 21:47:42 Malaysian time (08:47:42 AM ET - premarket)
- **Logged alert_price: $0.2759** ← This is Nov 5's close!
- Calculated gain: +128.3% (from $0.2759 to high $0.6300)

### Actual Reality:
- Nov 5 close: $0.2760
- **Actual premarket price at 8:47 AM: $0.60** (from yfinance data)
- Day's regular session high: $0.6300
- **Actual gain from alert: +5%** (from $0.60 to $0.63)

## Root Cause

In `volume_momentum_tracker.py`, premarket alerts use:

```python
# Line ~2645 (premarket_acceleration alerts)
premarket_price_alerts.append({
    'ticker': ticker,
    'premarket_change': current_pm_change,
    'current_price': current_record.get('close', 0),  # ← BUG: This is previous day's close!
    ...
})
```

The `current_record.get('close', 0)` field contains the **previous trading day's regular session close**, NOT the current premarket price.

## Impact

1. **End-of-day analysis is completely wrong** - showing fake +128% gains instead of real +5%
2. **All premarket alerts affected**: premarket_acceleration, new_premarket_move, premarket_volume_surge
3. **Win rate calculations are invalid** - measuring from wrong baseline
4. **Pattern analysis is corrupted** - identifying "winners" that aren't actually winners

## Affected Alert Types

Lines in `volume_momentum_tracker.py` with the bug:
- Line 2645: `premarket_acceleration`
- Line 2661: `premarket_volume_surge`
- Line 2674: `new_premarket_move`
- Line 2602: generic premarket price alerts
- Line 2615: generic premarket volume alerts

## Solution Implemented

**Fixed in `volume_momentum_tracker.py` (5 locations):**
All premarket alerts now calculate the actual current price:
```python
# Calculate actual current premarket price (not previous day's close)
close_price = current_record.get('close', 0)
current_premarket_price = close_price * (1 + current_pm_change / 100)
'current_price': current_premarket_price
```

Fixed locations:
1. Line 2641-2649: `premarket_acceleration` alerts
2. Line 2661-2669: `premarket_volume_surge` alerts
3. Line 2679-2686: `new_premarket_move` alerts
4. Line 2599-2606: Generic `significant_premarket_move` alerts
5. Line 2616-2623: Generic `high_premarket_volume` alerts

**Fixed in `end_of_day_analyzer.py`:**
Added backward-compatible fix to recalculate prices for historical data:
```python
# Detect and fix premarket alerts in historical logs
premarket_alert_types = ['premarket_acceleration', 'new_premarket_move', 'premarket_volume_surge',
                        'significant_premarket_move', 'high_premarket_volume']
if alert_type in premarket_alert_types:
    premarket_change = alert_data.get('change_pct', alert_data.get('premarket_change', 0))
    if premarket_change != 0:
        corrected_price = alert_price * (1 + premarket_change / 100)
        alert_price = corrected_price
```

This ensures historical analysis is accurate even for old log entries.

## Results After Fix

Running the analyzer on Nov 6, 2025 data:

**Before Fix:**
- BIYA: +128.3% gain (FALSE)
- Success rate: 42.9% (6/14 alerts)
- Premarket alerts: 100% success rate

**After Fix:**
```
⚠️  Correcting premarket alert price for BIYA: $0.2759 → $0.6132 (using +122.3% change)
⚠️  Correcting premarket alert price for AFJK: $19.5000 → $22.8819 (using +17.3% change)
```
- BIYA: +2.7% gain (ACCURATE - didn't reach 30% threshold)
- Success rate: 35.7% (5/14 alerts)
- Premarket alerts: 0% success rate (0/1)

The fix correctly identifies inflated gains and provides accurate performance metrics.

## Verification

Run this to test the fix:
```bash
python3 end_of_day_analyzer.py --date 2025-11-06
```

You should see warning messages about corrected premarket alert prices.
