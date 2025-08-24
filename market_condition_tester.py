#!/usr/bin/env python3
"""
Market Condition Tester - Advanced Analysis
Tests specific hypotheses about market conditions and momentum success
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import statistics

class MarketConditionTester:
    def __init__(self):
        # Results from our previous analysis
        self.results = {
            '2025-08-15': {'success_rate': 25.0, 'winners': 2, 'total': 8, 'day_type': 'good'},
            '2025-08-18': {'success_rate': 50.0, 'winners': 3, 'total': 6, 'day_type': 'best'},  
            '2025-08-19': {'success_rate': 21.4, 'winners': 3, 'total': 14, 'day_type': 'poor'},
            '2025-08-23': {'success_rate': 0.0, 'winners': 0, 'total': 3, 'day_type': 'worst'}
        }
    
    def test_key_hypotheses(self):
        """Test key hypotheses about market conditions"""
        print("🧪 TESTING KEY MARKET CONDITION HYPOTHESES")
        print("=" * 60)
        
        # Fetch detailed market data
        market_data = self.fetch_detailed_market_data()
        
        # Test each hypothesis
        self.test_nasdaq_performance_hypothesis(market_data)
        self.test_biotech_sector_hypothesis(market_data)
        self.test_small_cap_outperformance_hypothesis(market_data)
        self.test_volatility_hypothesis(market_data)
        self.test_market_breadth_hypothesis(market_data)
        
    def fetch_detailed_market_data(self):
        """Fetch detailed market data with additional indicators"""
        print("📈 Fetching detailed market data...")
        
        symbols = {
            'SPY': 'S&P 500',
            'QQQ': 'NASDAQ',
            'IWM': 'Russell 2000', 
            'XLV': 'Healthcare ETF',
            'IBB': 'Biotech ETF',
            'XLK': 'Technology ETF',
            '^IXIC': 'NASDAQ Composite',
            '^GSPC': 'S&P 500 Index',
            'VXX': 'VIX ETF (Volatility)',
            'TLT': '20+ Yr Treasury (Risk-off indicator)'
        }
        
        data = {}
        start_date = '2025-08-10'
        end_date = '2025-08-25'
        
        for symbol, name in symbols.items():
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(start=start_date, end=end_date, interval='1d')
                
                if not hist.empty:
                    # Add technical indicators
                    hist['Daily_Return'] = hist['Close'].pct_change() * 100
                    hist['High_Low_Range'] = ((hist['High'] - hist['Low']) / hist['Low']) * 100
                    hist['Open_Close_Gap'] = ((hist['Open'] - hist['Close'].shift(1)) / hist['Close'].shift(1)) * 100
                    
                    data[symbol] = hist
                    print(f"  ✅ {symbol} ({name})")
                    
            except Exception as e:
                print(f"  ❌ {symbol}: {e}")
        
        return data
    
    def test_nasdaq_performance_hypothesis(self, market_data):
        """
        Hypothesis: Momentum stocks perform better when NASDAQ is flat to slightly negative
        (When growth stocks are selling off, money rotates to speculative momentum plays)
        """
        print(f"\n🧪 HYPOTHESIS 1: NASDAQ Performance vs Momentum Success")
        print("-" * 50)
        print("Theory: Momentum works better when QQQ is flat to slightly negative")
        print("Reason: Money rotates from big tech to small speculative plays")
        
        if 'QQQ' not in market_data:
            print("❌ No QQQ data available")
            return
        
        qqq_data = market_data['QQQ']
        
        for date_str, result in self.results.items():
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            day_data = qqq_data[qqq_data.index.date == date]
            
            if not day_data.empty:
                qqq_return = day_data['Daily_Return'].iloc[0]
                success_rate = result['success_rate']
                
                print(f"{date_str}: QQQ {qqq_return:+5.2f}% → Success Rate {success_rate:4.1f}%")
        
        # Calculate correlation
        qqq_returns = []
        success_rates = []
        
        for date_str, result in self.results.items():
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            day_data = qqq_data[qqq_data.index.date == date]
            
            if not day_data.empty:
                qqq_returns.append(day_data['Daily_Return'].iloc[0])
                success_rates.append(result['success_rate'])
        
        if len(qqq_returns) >= 3:
            # Simple correlation analysis
            correlation = self.calculate_correlation(qqq_returns, success_rates)
            print(f"\n📊 Correlation: {correlation:.3f}")
            
            if correlation < -0.3:
                print("✅ HYPOTHESIS SUPPORTED: Negative correlation found!")
                print("💡 Trade momentum when QQQ is flat to negative")
            elif correlation > 0.3:
                print("❌ HYPOTHESIS REJECTED: Positive correlation found")
                print("💡 Trade momentum when QQQ is rising")
            else:
                print("❓ INCONCLUSIVE: Weak correlation")
    
    def test_biotech_sector_hypothesis(self, market_data):
        """
        Hypothesis: Biotech ETF (IBB) performance correlates with our success
        (Since many of our winners were health/biotech stocks)
        """
        print(f"\n🧪 HYPOTHESIS 2: Biotech Sector Performance")
        print("-" * 50)
        print("Theory: Our success correlates with biotech sector strength")
        print("Reason: Many winners were health/biotech stocks (LASE, SNGX, GXAI, etc.)")
        
        if 'IBB' not in market_data:
            print("❌ No IBB (Biotech ETF) data available")
            return
        
        ibb_data = market_data['IBB']
        
        for date_str, result in self.results.items():
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            day_data = ibb_data[ibb_data.index.date == date]
            
            if not day_data.empty:
                ibb_return = day_data['Daily_Return'].iloc[0]
                success_rate = result['success_rate']
                
                print(f"{date_str}: IBB {ibb_return:+5.2f}% → Success Rate {success_rate:4.1f}%")
        
        # Calculate correlation
        ibb_returns = []
        success_rates = []
        
        for date_str, result in self.results.items():
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            day_data = ibb_data[ibb_data.index.date == date]
            
            if not day_data.empty:
                ibb_returns.append(day_data['Daily_Return'].iloc[0])
                success_rates.append(result['success_rate'])
        
        if len(ibb_returns) >= 3:
            correlation = self.calculate_correlation(ibb_returns, success_rates)
            print(f"\n📊 Correlation: {correlation:.3f}")
            
            if correlation > 0.5:
                print("✅ HYPOTHESIS SUPPORTED: Strong positive correlation!")
                print("💡 Trade momentum when biotech sector is strong")
            elif correlation < -0.5:
                print("❌ HYPOTHESIS REJECTED: Negative correlation found")  
            else:
                print("❓ INCONCLUSIVE: Weak correlation")
    
    def test_small_cap_outperformance_hypothesis(self, market_data):
        """
        Hypothesis: Small caps (IWM) outperforming large caps indicates good momentum day
        """
        print(f"\n🧪 HYPOTHESIS 3: Small Cap Outperformance")
        print("-" * 50)
        print("Theory: Momentum works when small caps (IWM) outperform large caps (SPY)")
        print("Reason: Risk-on sentiment favors small speculative stocks")
        
        if 'IWM' not in market_data or 'SPY' not in market_data:
            print("❌ No IWM or SPY data available")
            return
        
        iwm_data = market_data['IWM']
        spy_data = market_data['SPY']
        
        for date_str, result in self.results.items():
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            
            iwm_day = iwm_data[iwm_data.index.date == date]
            spy_day = spy_data[spy_data.index.date == date]
            
            if not iwm_day.empty and not spy_day.empty:
                iwm_return = iwm_day['Daily_Return'].iloc[0]
                spy_return = spy_day['Daily_Return'].iloc[0]
                outperformance = iwm_return - spy_return
                success_rate = result['success_rate']
                
                print(f"{date_str}: IWM {iwm_return:+5.2f}% vs SPY {spy_return:+5.2f}% (Diff: {outperformance:+5.2f}%) → Success: {success_rate:4.1f}%")
        
        # Test correlation with outperformance
        outperformances = []
        success_rates = []
        
        for date_str, result in self.results.items():
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            
            iwm_day = iwm_data[iwm_data.index.date == date]
            spy_day = spy_data[spy_data.index.date == date]
            
            if not iwm_day.empty and not spy_day.empty:
                iwm_return = iwm_day['Daily_Return'].iloc[0]
                spy_return = spy_day['Daily_Return'].iloc[0]
                outperformances.append(iwm_return - spy_return)
                success_rates.append(result['success_rate'])
        
        if len(outperformances) >= 3:
            correlation = self.calculate_correlation(outperformances, success_rates)
            print(f"\n📊 Correlation with IWM outperformance: {correlation:.3f}")
            
            if correlation > 0.4:
                print("✅ HYPOTHESIS SUPPORTED: Small cap outperformance helps!")
                print("💡 Trade momentum when IWM > SPY")
            else:
                print("❓ INCONCLUSIVE or hypothesis not supported")
    
    def test_volatility_hypothesis(self, market_data):
        """
        Hypothesis: Moderate volatility (not too low, not too high) is best for momentum
        """
        print(f"\n🧪 HYPOTHESIS 4: Optimal Volatility Range")
        print("-" * 50)
        print("Theory: Moderate volatility creates best momentum conditions")
        print("Reason: Need movement but not panic selling")
        
        # Use SPY volatility as proxy (since VIX data unavailable)
        if 'SPY' not in market_data:
            print("❌ No SPY data available")
            return
        
        spy_data = market_data['SPY']
        
        for date_str, result in self.results.items():
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            day_data = spy_data[spy_data.index.date == date]
            
            if not day_data.empty:
                high_low_range = day_data['High_Low_Range'].iloc[0]
                daily_return = abs(day_data['Daily_Return'].iloc[0])
                success_rate = result['success_rate']
                
                print(f"{date_str}: SPY Range {high_low_range:.2f}%, |Return| {daily_return:.2f}% → Success: {success_rate:4.1f}%")
        
        print("💡 Look for patterns: Too much volatility = fear, too little = no momentum")
    
    def test_market_breadth_hypothesis(self, market_data):
        """
        Hypothesis: Market breadth indicators help predict momentum success
        """
        print(f"\n🧪 HYPOTHESIS 5: Market Breadth Analysis")
        print("-" * 50)
        print("Theory: When multiple sectors move together, momentum is stronger")
        
        sector_etfs = ['XLV', 'XLK', 'IBB']
        available_sectors = [s for s in sector_etfs if s in market_data]
        
        if len(available_sectors) < 2:
            print("❌ Insufficient sector data")
            return
        
        for date_str, result in self.results.items():
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            
            sector_returns = []
            for sector in available_sectors:
                day_data = market_data[sector][market_data[sector].index.date == date]
                if not day_data.empty:
                    sector_returns.append(day_data['Daily_Return'].iloc[0])
            
            if sector_returns:
                positive_sectors = len([r for r in sector_returns if r > 0])
                avg_return = statistics.mean(sector_returns)
                success_rate = result['success_rate']
                
                print(f"{date_str}: {positive_sectors}/{len(sector_returns)} sectors positive, Avg: {avg_return:+5.2f}% → Success: {success_rate:4.1f}%")
    
    def calculate_correlation(self, x, y):
        """Calculate simple correlation coefficient"""
        if len(x) != len(y) or len(x) < 2:
            return 0
        
        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(x[i] * y[i] for i in range(n))
        sum_x2 = sum(x[i] ** 2 for i in range(n))
        sum_y2 = sum(y[i] ** 2 for i in range(n))
        
        numerator = n * sum_xy - sum_x * sum_y
        denominator = ((n * sum_x2 - sum_x ** 2) * (n * sum_y2 - sum_y ** 2)) ** 0.5
        
        if denominator == 0:
            return 0
        
        return numerator / denominator
    
    def generate_market_sentiment_score(self, market_data):
        """Generate a market sentiment score for momentum trading"""
        print(f"\n🎯 MARKET SENTIMENT SCORING SYSTEM")
        print("=" * 60)
        
        print("Based on analysis, creating scoring system for real-time use...")
        
        scoring_factors = [
            "✅ QQQ Performance: -2% to +1% (rotation from big tech)",
            "✅ IBB/Biotech Strength: >0% (sector momentum)", 
            "✅ IWM vs SPY: Small caps outperforming (risk-on)",
            "✅ Market Breadth: Multiple sectors positive",
            "✅ Moderate Volatility: Not too calm, not too panicked"
        ]
        
        for factor in scoring_factors:
            print(factor)
        
        print(f"\n💡 RECOMMENDED IMPLEMENTATION:")
        print("1. Check these conditions before sending alerts")
        print("2. Score each factor 0-20 points (total 100)")  
        print("3. Only send alerts when score > 60")
        print("4. Increase position sizes when score > 80")

def main():
    print("🧪 ADVANCED MARKET CONDITION TESTING")
    print("=" * 60)
    print("Testing specific hypotheses about market conditions and momentum success")
    print()
    
    tester = MarketConditionTester()
    tester.test_key_hypotheses()
    
    # Fetch market data for scoring system
    market_data = tester.fetch_detailed_market_data()
    tester.generate_market_sentiment_score(market_data)
    
    print(f"\n✅ Testing complete!")
    print("💡 Use these insights to create market condition filters")

if __name__ == "__main__":
    main()