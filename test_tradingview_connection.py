#!/usr/bin/env python3
"""
Test TradingView connection health.
Checks cookies, API reachability, and that live data is being returned.

Usage:
    ./venv/bin/python test_tradingview_connection.py
"""

import sys

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"

results = []

def check(label, status, detail=""):
    icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️ "}[status]
    msg = f"  {icon} {label}"
    if detail:
        msg += f": {detail}"
    print(msg)
    results.append((label, status))

# ── 0. Import check ───────────────────────────────────────────────────────────

print("\n[0] Dependencies")

try:
    import rookiepy
    ROOKIEPY_AVAILABLE = True
    check("rookiepy available", PASS)
except ImportError as e:
    ROOKIEPY_AVAILABLE = False
    check("rookiepy available", WARN,
          f"not installed ({e}) — cookie check skipped, running unauthenticated")

try:
    from tradingview_screener import Query
    check("tradingview-screener available", PASS)
except ImportError as e:
    check("tradingview-screener available", FAIL, str(e))
    print("\nCannot continue without tradingview-screener.")
    sys.exit(1)

# ── 1. Cookie extraction ───────────────────────────────────────────────────────

print("\n[1] Cookies")

cookies = {}

if ROOKIEPY_AVAILABLE:
    try:
        cookies_list = rookiepy.firefox(['.tradingview.com'])
        if cookies_list:
            for c in cookies_list:
                if isinstance(c, dict) and c.get('name') and c.get('value'):
                    cookies[c['name']] = c['value']

        if cookies:
            check("Extract Firefox cookies", PASS, f"{len(cookies)} cookies found")
        else:
            check("Extract Firefox cookies", WARN, "No tradingview.com cookies found")
    except Exception as e:
        check("Extract Firefox cookies", FAIL, str(e))

    # Check for session cookie
    SESSION_KEYS = ['sessionid', 'tv_ecuid', 'device_t']
    found_session = [k for k in SESSION_KEYS if k in cookies]
    if found_session:
        check("Session cookie present", PASS, f"found: {', '.join(found_session)}")
    else:
        check("Session cookie present", WARN,
              f"none of {SESSION_KEYS} found — may be logged out of TradingView in Firefox")

    if 'sessionid' in cookies:
        val = cookies['sessionid']
        if len(val) > 10:
            check("sessionid looks valid", PASS, f"{val[:6]}…")
        else:
            check("sessionid looks valid", WARN, f"very short value: '{val}'")
else:
    print("  ⏭  Skipped (rookiepy unavailable)")

# ── 2. API reachability ────────────────────────────────────────────────────────

print("\n[2] API reachability")

try:
    count, df = Query().select('name', 'close').limit(5).get_scanner_data(cookies=cookies)
    if count and count > 0 and df is not None and len(df) > 0:
        check("Scanner API responds", PASS, f"total_count={count:,}")
    else:
        check("Scanner API responds", FAIL, f"empty response (count={count})")
except Exception as e:
    check("Scanner API responds", FAIL, str(e))

# ── 3. Premarket screener data ────────────────────────────────────────────────

print("\n[3] Premarket screener data")

try:
    fields = ['name', 'premarket_volume', 'premarket_change', 'close', 'volume']
    count2, df2 = (Query()
                   .select(*fields)
                   .order_by('premarket_volume', ascending=False)
                   .limit(20)
                   .get_scanner_data(cookies=cookies))

    if count2 == 0 or df2 is None or len(df2) == 0:
        check("Premarket screener returns rows", WARN,
              "no results — market may be closed or unauthenticated")
    else:
        records = df2.to_dict('records')
        tickers_with_pm_vol = [r for r in records if (r.get('premarket_volume') or 0) > 0]
        check("Premarket screener returns rows", PASS,
              f"{len(records)} rows, {len(tickers_with_pm_vol)} with premarket volume > 0")

        # Warn if all premarket_change values are identical (stale/cached API data)
        pm_changes = [r.get('premarket_change') for r in records
                      if r.get('premarket_change') is not None]
        if pm_changes and len(set(pm_changes)) == 1:
            check("Premarket data looks fresh", WARN,
                  "all premarket_change values are identical — API may be returning cached/stale data")
        elif pm_changes:
            check("Premarket data looks fresh", PASS,
                  f"{len(set(pm_changes))} unique change% values across {len(pm_changes)} tickers")
        else:
            check("Premarket data has change values", WARN, "no premarket_change values present")

        # Show top 5 tickers
        print("\n  Top 5 by premarket volume:")
        for r in records[:5]:
            name   = r.get('name', '?')
            pm_vol = r.get('premarket_volume') or 0
            pm_chg = r.get('premarket_change')
            chg_str = f"{pm_chg:+.2f}%" if pm_chg is not None else "N/A"
            print(f"    {name:<10} pm_vol={pm_vol:>15,.0f}  pm_change={chg_str}")

except Exception as e:
    check("Premarket screener returns rows", FAIL, str(e))

# ── 4. Spot-check SPY ─────────────────────────────────────────────────────────

print("\n[4] Spot-check SPY (always-liquid reference ticker)")

try:
    count3, df3 = (Query()
                   .select('name', 'close', 'volume')
                   .set_tickers('AMEX:SPY')
                   .get_scanner_data(cookies=cookies))

    if df3 is not None and len(df3) > 0:
        row = df3.to_dict('records')[0]
        close  = row.get('close')
        volume = row.get('volume') or 0
        if close and close > 0:
            check("SPY quote received", PASS, f"close=${close:.2f}  volume={volume:,.0f}")
        else:
            check("SPY quote received", WARN, f"close is null/zero: {row}")
    else:
        check("SPY quote received", FAIL, "empty response")
except Exception as e:
    check("SPY quote received", FAIL, str(e))

# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'─'*45}")
passed = sum(1 for _, s in results if s == PASS)
warned = sum(1 for _, s in results if s == WARN)
failed = sum(1 for _, s in results if s == FAIL)
total  = len(results)
print(f"  {passed}/{total} passed   {warned} warnings   {failed} failures")

if not ROOKIEPY_AVAILABLE:
    print()
    print("  NOTE: rookiepy is not available (Python 3.14 not yet supported).")
    print("  Install python313 from AUR then recreate the venv:")
    print("    yay -S python313")
    print("    python3.13 -m venv venv")
    print("    venv/bin/pip install -r requirements.txt  # or reinstall manually")

if failed:
    print("  Connection has ISSUES — check failures above.")
    sys.exit(1)
elif warned:
    print("  Connection is DEGRADED — check warnings above.")
    sys.exit(0)
else:
    print("  Connection looks HEALTHY.")
    sys.exit(0)
