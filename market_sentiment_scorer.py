#!/usr/bin/env python3
"""
Market Sentiment Scorer
Real-time market condition scoring for momentum trading
Based on analysis of winning vs losing days
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import logging

class MarketSentimentScorer:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.cache = {}
        self.cache_expiry = 300  # 5 minutes cache
        
    def get_current_market_sentiment_score(self):
        """
        Get current market sentiment score (0-100)
        Based on analysis showing key factors for momentum success
        
        Returns:
            dict: {
                'score': int (0-100),
                'category': str ('EXCELLENT', 'GOOD', 'FAIR', 'POOR'),
                'factors': dict,
                'recommendation': str
            }
        """
        try:
            # Check cache first
            current_time = datetime.now()
            if 'market_score' in self.cache:
                cache_time, cached_data = self.cache['market_score']
                if (current_time - cache_time).seconds < self.cache_expiry:
                    self.logger.debug("Using cached market sentiment score")
                    return cached_data
            
            self.logger.info("🎯 Calculating real-time market sentiment score...")
            
            # Fetch current market data
            market_data = self._fetch_current_market_data()
            
            # Calculate individual factor scores
            factors = {}
            total_score = 0
            
            # Factor 1: Small Cap Outperformance (0-25 points)
            # STRONGEST CORRELATION: 0.988 with success rate
            iwm_spy_score, iwm_spy_detail = self._score_small_cap_outperformance(market_data)
            factors['small_cap_outperformance'] = {
                'score': iwm_spy_score,
                'detail': iwm_spy_detail,
                'weight': 25
            }
            total_score += iwm_spy_score
            
            # Factor 2: NASDAQ Performance (0-20 points)  
            # Contrary to hypothesis: positive correlation with QQQ strength
            qqq_score, qqq_detail = self._score_nasdaq_performance(market_data)
            factors['nasdaq_performance'] = {
                'score': qqq_score,
                'detail': qqq_detail,
                'weight': 20
            }
            total_score += qqq_score
            
            # Factor 3: Biotech Sector Strength (0-20 points)
            # Weak correlation but biotech is our main winner sector
            ibb_score, ibb_detail = self._score_biotech_strength(market_data)
            factors['biotech_strength'] = {
                'score': ibb_score,
                'detail': ibb_detail,
                'weight': 20
            }
            total_score += ibb_score
            
            # Factor 4: Volatility Range (0-20 points)
            # Moderate volatility is optimal
            vol_score, vol_detail = self._score_volatility_conditions(market_data)
            factors['volatility_conditions'] = {
                'score': vol_score,
                'detail': vol_detail,
                'weight': 20
            }
            total_score += vol_score
            
            # Factor 5: Market Breadth (0-15 points)
            # Multiple sectors moving together
            breadth_score, breadth_detail = self._score_market_breadth(market_data)
            factors['market_breadth'] = {
                'score': breadth_score,
                'detail': breadth_detail,
                'weight': 15
            }
            total_score += breadth_score
            
            # Determine category and recommendation
            if total_score >= 80:
                category = "EXCELLENT"
                recommendation = "🚀 PRIME CONDITIONS: Send all alerts, consider larger positions"
            elif total_score >= 65:
                category = "GOOD"
                recommendation = "✅ FAVORABLE: Send alerts normally"
            elif total_score >= 45:
                category = "FAIR" 
                recommendation = "⚠️  CAUTION: Send only highest conviction alerts"
            else:
                category = "POOR"
                recommendation = "🛑 UNFAVORABLE: Avoid or reduce alert frequency"
            
            result = {
                'score': total_score,
                'category': category,
                'factors': factors,
                'recommendation': recommendation,
                'timestamp': current_time.isoformat()
            }
            
            # Cache the result
            self.cache['market_score'] = (current_time, result)
            
            self.logger.info(f"Market sentiment score: {total_score}/100 ({category})")
            return result
            
        except Exception as e:
            self.logger.error(f"Error calculating market sentiment score: {e}")
            return {
                'score': 50,  # Neutral default
                'category': "UNKNOWN",
                'factors': {},
                'recommendation': "⚠️  Unable to assess market conditions",
                'timestamp': datetime.now().isoformat(),
                'error': str(e)
            }
    
    def _fetch_current_market_data(self):
        """Fetch current/recent market data for scoring"""
        symbols = {
            'SPY': 'S&P 500 ETF',
            'QQQ': 'NASDAQ ETF',
            'IWM': 'Russell 2000 ETF', 
            'IBB': 'Biotech ETF',
            'XLV': 'Healthcare ETF',
            'XLK': 'Technology ETF'
        }
        
        # Fetch last 2 trading days to calculate daily returns
        end_date = datetime.now()
        start_date = end_date - timedelta(days=5)  # Go back 5 days to ensure we get 2 trading days
        
        data = {}
        for symbol, name in symbols.items():
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(start=start_date.strftime('%Y-%m-%d'), 
                                    end=end_date.strftime('%Y-%m-%d'), 
                                    interval='1d')
                
                if len(hist) >= 2:
                    # Calculate today's performance
                    latest = hist.iloc[-1]
                    previous = hist.iloc[-2]
                    
                    daily_return = ((latest['Close'] - previous['Close']) / previous['Close']) * 100
                    high_low_range = ((latest['High'] - latest['Low']) / latest['Low']) * 100
                    
                    data[symbol] = {
                        'close': latest['Close'],
                        'daily_return': daily_return,
                        'high_low_range': high_low_range,
                        'volume': latest['Volume'],
                        'name': name
                    }
                    
            except Exception as e:
                self.logger.warning(f"Failed to fetch {symbol}: {e}")
        
        return data
    
    def _score_small_cap_outperformance(self, market_data):
        """
        Score based on IWM (small caps) vs SPY (large caps) performance
        Strongest predictor: correlation 0.988 with success
        """
        if 'IWM' not in market_data or 'SPY' not in market_data:
            return 0, "No small cap data available"
        
        iwm_return = market_data['IWM']['daily_return']
        spy_return = market_data['SPY']['daily_return'] 
        outperformance = iwm_return - spy_return
        
        # Scoring based on analysis:
        # Aug 18 (best day): IWM outperformed by +0.39% = 50% success rate
        # Aug 15,19 (poor days): IWM underperformed by ~-0.25% = ~23% success rate
        
        if outperformance > 0.3:
            score = 25  # Maximum points
            detail = f"🚀 Excellent: IWM outperforming SPY by {outperformance:+.2f}%"
        elif outperformance > 0:
            score = int(20 + (outperformance / 0.3) * 5)  # 20-25 points
            detail = f"✅ Good: IWM outperforming SPY by {outperformance:+.2f}%"
        elif outperformance > -0.2:
            score = int(15 + ((outperformance + 0.2) / 0.2) * 5)  # 15-20 points
            detail = f"⚠️  Fair: IWM vs SPY {outperformance:+.2f}%"
        elif outperformance > -0.5:
            score = int(5 + ((outperformance + 0.5) / 0.3) * 10)  # 5-15 points
            detail = f"❌ Poor: IWM underperforming SPY by {outperformance:+.2f}%"
        else:
            score = 0
            detail = f"🛑 Very Poor: IWM badly underperforming by {outperformance:+.2f}%"
        
        return max(0, min(25, score)), detail
    
    def _score_nasdaq_performance(self, market_data):
        """
        Score based on QQQ performance
        Analysis showed positive correlation (0.808) - contrary to hypothesis
        """
        if 'QQQ' not in market_data:
            return 0, "No NASDAQ data available"
        
        qqq_return = market_data['QQQ']['daily_return']
        
        # Scoring based on analysis:
        # Aug 18 (best day): QQQ -0.04% = 50% success
        # Aug 15 (good day): QQQ -0.44% = 25% success  
        # Aug 19 (poor day): QQQ -1.36% = 21.4% success
        
        if qqq_return > 0.5:
            score = 20
            detail = f"🚀 Strong: QQQ up {qqq_return:+.2f}%"
        elif qqq_return > -0.1:
            score = 18
            detail = f"✅ Good: QQQ flat {qqq_return:+.2f}%"
        elif qqq_return > -0.5:
            score = 12
            detail = f"⚠️  Weak: QQQ down {qqq_return:+.2f}%"
        elif qqq_return > -1.0:
            score = 8
            detail = f"❌ Poor: QQQ down {qqq_return:+.2f}%"
        else:
            score = 0
            detail = f"🛑 Very Weak: QQQ down {qqq_return:+.2f}%"
        
        return score, detail
    
    def _score_biotech_strength(self, market_data):
        """Score based on biotech sector strength (IBB ETF)"""
        if 'IBB' not in market_data:
            return 0, "No biotech data available"
        
        ibb_return = market_data['IBB']['daily_return']
        
        # Scoring based on biotech being our key sector for winners
        if ibb_return > 2.0:
            score = 20
            detail = f"🚀 Strong: Biotech up {ibb_return:+.2f}%"
        elif ibb_return > 0.5:
            score = 16
            detail = f"✅ Good: Biotech up {ibb_return:+.2f}%"  
        elif ibb_return > -0.5:
            score = 12
            detail = f"⚠️  Neutral: Biotech {ibb_return:+.2f}%"
        elif ibb_return > -1.5:
            score = 6
            detail = f"❌ Weak: Biotech down {ibb_return:+.2f}%"
        else:
            score = 0
            detail = f"🛑 Very Weak: Biotech down {ibb_return:+.2f}%"
        
        return score, detail
    
    def _score_volatility_conditions(self, market_data):
        """Score based on optimal volatility range"""
        if 'SPY' not in market_data:
            return 0, "No volatility data available"
        
        high_low_range = market_data['SPY']['high_low_range']
        daily_return_abs = abs(market_data['SPY']['daily_return'])
        
        # Based on analysis: Aug 18 (best day) had low volatility, but need some movement
        # Optimal appears to be moderate range
        
        # Score based on intraday range
        if 0.3 <= high_low_range <= 0.8:
            range_score = 15  # Optimal range
        elif 0.2 <= high_low_range <= 1.2:
            range_score = 10  # Acceptable range
        else:
            range_score = 5   # Too volatile or too calm
        
        # Score based on daily movement
        if 0.1 <= daily_return_abs <= 0.6:
            move_score = 5   # Good movement
        else:
            move_score = 2   # Too much or too little
        
        total_score = range_score + move_score
        detail = f"Range: {high_low_range:.2f}%, Move: {daily_return_abs:.2f}%"
        
        return total_score, detail
    
    def _score_market_breadth(self, market_data):
        """Score based on how many sectors are positive"""
        sectors = ['XLV', 'XLK', 'IBB']
        available_sectors = [s for s in sectors if s in market_data]
        
        if not available_sectors:
            return 0, "No sector data available"
        
        positive_sectors = sum(1 for s in available_sectors 
                             if market_data[s]['daily_return'] > 0)
        
        total_sectors = len(available_sectors)
        positive_pct = positive_sectors / total_sectors
        
        if positive_pct >= 0.8:
            score = 15
            detail = f"🚀 Strong: {positive_sectors}/{total_sectors} sectors positive"
        elif positive_pct >= 0.6:
            score = 12
            detail = f"✅ Good: {positive_sectors}/{total_sectors} sectors positive"
        elif positive_pct >= 0.4:
            score = 8
            detail = f"⚠️  Mixed: {positive_sectors}/{total_sectors} sectors positive" 
        else:
            score = 3
            detail = f"❌ Weak: {positive_sectors}/{total_sectors} sectors positive"
        
        return score, detail
    
    def print_current_score(self):
        """Print current market sentiment score with details"""
        score_data = self.get_current_market_sentiment_score()
        
        print(f"\n🎯 MARKET SENTIMENT SCORE: {score_data['score']}/100 ({score_data['category']})")
        print("=" * 60)
        print(f"⭐ {score_data['recommendation']}")
        print(f"📅 Updated: {score_data['timestamp'][:19]}")
        
        if 'factors' in score_data:
            print(f"\n📊 FACTOR BREAKDOWN:")
            print("-" * 30)
            
            for factor_name, factor_data in score_data['factors'].items():
                weight = factor_data['weight']
                score = factor_data['score']  
                detail = factor_data['detail']
                
                factor_display = factor_name.replace('_', ' ').title()
                print(f"{factor_display:20} | {score:2d}/{weight:2d} | {detail}")
        
        return score_data

def main():
    """Test the market sentiment scorer"""
    import logging
    logging.basicConfig(level=logging.INFO)
    
    print("🎯 MARKET SENTIMENT SCORER - LIVE TEST")
    print("=" * 60)
    
    scorer = MarketSentimentScorer()
    score_data = scorer.print_current_score()
    
    print(f"\n💡 INTEGRATION RECOMMENDATIONS:")
    print("1. Check score before sending telegram alerts")
    print("2. Filter out alerts when score < 45")
    print("3. Send all alerts when score > 80")
    print("4. Use score to adjust position sizing")

if __name__ == "__main__":
    main()