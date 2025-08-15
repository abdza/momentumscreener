#!/usr/bin/env python3

import sys
sys.path.append('/home/abdza/data/kakikoding/trading/momentumscreener')
from volume_momentum_tracker import VolumeMomentumTracker
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

tracker = VolumeMomentumTracker()

print('=== DEBUGGING date parsing issue ===')

# Test the search step by step
ticker = 'META'
company_name = tracker._get_company_name(ticker)
search_query = f'{company_name} OR {ticker} stock earnings financial'
url = f'https://news.google.com/rss/search?q={search_query}&hl=en-US&gl=US&ceid=US:en'

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

response = requests.get(url, headers=headers, timeout=10)
root = ET.fromstring(response.content)
items = root.findall('.//item')

three_days_ago = datetime.now() - timedelta(days=3)
print(f'Three days ago cutoff: {three_days_ago}')

# Test first few items with full debugging
for i, item in enumerate(items[:3]):
    title_elem = item.find('title')
    link_elem = item.find('link')
    pub_date_elem = item.find('pubDate')
    
    if title_elem is not None and link_elem is not None:
        title = title_elem.text
        link = link_elem.text
        
        print(f'\n=== Item {i+1} ===')
        print(f'Title: {title}')
        print(f'Link: {link}')
        
        # Check pubDate
        if pub_date_elem is not None and pub_date_elem.text:
            raw_date = pub_date_elem.text
            print(f'Raw pubDate: {raw_date}')
            
            # Test our date parsing
            try:
                parsed_date = tracker._parse_date_with_fallbacks(raw_date, ticker)
                print(f'Parsed date: {parsed_date}')
                
                # Check if it's within 3 days
                if parsed_date and parsed_date < three_days_ago:
                    print(f'❌ Article is too old: {parsed_date} < {three_days_ago}')
                else:
                    print(f'✅ Article is recent enough')
                    
                    # Test relevance
                    is_relevant = tracker._is_relevant_news(title, ticker)
                    print(f'Relevance check: {is_relevant}')
                    
                    if is_relevant:
                        print('✅ This article should be included!')
                    else:
                        print('❌ This article failed relevance check')
                
            except Exception as date_e:
                print(f'❌ Date parsing error: {date_e}')
        else:
            print('No pubDate found, would use fallback time')
            fallback_date = datetime.now() - timedelta(hours=1)
            print(f'Fallback date: {fallback_date}')
            
            is_relevant = tracker._is_relevant_news(title, ticker)
            print(f'Relevance check: {is_relevant}')
            
            if is_relevant:
                print('✅ This article should be included!')