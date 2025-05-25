#!/usr/bin/env python3
"""
Simple script to discover correct TradingView field names
"""

import rookiepy
from tradingview_screener import Query

def test_field_names():
    """Test different field name possibilities"""
    
    # Get cookies
    try:
        cookies_list = rookiepy.load()
        cookies = {}
        for cookie in cookies_list:
            if 'tradingview.com' in cookie.get('domain', ''):
                cookies[cookie['name']] = cookie['value']
        print(f"Loaded {len(cookies)} cookies")
    except Exception as e:
        print(f"Cookie error: {e}")
        cookies = {}
    
    # Field name candidates for each requested column
    field_candidates = {
        'relative_volume': [
            'relative_volume_10d_calc',
            'Relative Volume',
            'relative_volume',
            'rel_volume',
            'volume_ratio'
        ],
        'price_x_volume': [
            'Value.Traded',
            'value_traded', 
            'total_value_traded',
            'dollar_volume',
            'notional_volume'
        ],
        'change_from_open': [
            'change_from_open',
            'perf.1D',
            'performance_1d',
            'intraday_change',
            'open_to_current'
        ],
        'change_percent': [
            'change_percent',
            'change|5',
            'perf_1d',
            'percent_change'
        ],
        'float_shares': [
            'float_shares_outstanding',
            'shares_float',
            'Shares Float',
            'float',
            'floating_shares'
        ],
        'premarket_change': [
            'premarket_change',
            'premarket_change_abs',
            'pre_market_change',
            'extended_hours_change'
        ]
    }
    
    print("\nTesting individual field names...")
    
    working_fields = ['name', 'volume', 'close', 'change', 'sector', 'exchange']  # Known working fields
    
    for category, candidates in field_candidates.items():
        print(f"\n--- Testing {category} ---")
        for field in candidates:
            try:
                test_query = Query().select('name', field).limit(1)
                result = test_query.get_scanner_data(cookies=cookies)
                
                if isinstance(result, tuple) and len(result) == 2:
                    _, df = result
                    if hasattr(df, 'columns') and field in df.columns:
                        print(f"✅ {field} - WORKS")
                        working_fields.append(field)
                        break  # Found working field for this category
                    else:
                        print(f"❌ {field} - Not in columns")
                else:
                    print(f"❌ {field} - Unexpected result format")
                    
            except Exception as e:
                print(f"❌ {field} - Error: {str(e)[:50]}...")
    
    print(f"\n=== WORKING FIELDS ===")
    for field in working_fields:
        print(f"  '{field}',")
    
    # Test the working combination
    if len(working_fields) > 3:
        try:
            print(f"\nTesting combination of working fields...")
            combo_query = Query().select(*working_fields[:10]).limit(3)  # Limit to 10 fields max
            result = combo_query.get_scanner_data(cookies=cookies)
            
            if isinstance(result, tuple) and len(result) == 2:
                _, df = result
                if hasattr(df, 'columns'):
                    print("✅ Combination query works!")
                    print("Resulting columns:")
                    for col in df.columns:
                        print(f"  - {col}")
                    
                    print("\nSample data:")
                    print(df.head(2))
                        
        except Exception as e:
            print(f"❌ Combination query failed: {e}")

if __name__ == "__main__":
    test_field_names()