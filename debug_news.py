#!/usr/bin/env python3

import sys
sys.path.append('/home/abdza/data/kakikoding/trading/momentumscreener')
from volume_momentum_tracker import VolumeMomentumTracker
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

tracker = VolumeMomentumTracker()

print('=== DEBUGGING Google News search for META ===')

# Test the search step by step
ticker = 'META'
company_name = tracker._get_company_name(ticker)
print(f'Company name detected: {company_name}')

# Build search query
if company_name and company_name != ticker.upper():
    search_query = f'{company_name} OR {ticker} stock earnings financial'
else:
    search_query = f'{ticker} stock earnings financial'

print(f'Search query: {search_query}')

url = f'https://news.google.com/rss/search?q={search_query}&hl=en-US&gl=US&ceid=US:en'
print(f'URL: {url}')

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

response = requests.get(url, headers=headers, timeout=10)
print(f'Response status: {response.status_code}')

root = ET.fromstring(response.content)
items = root.findall('.//item')
print(f'Found {len(items)} RSS items')

# Test first few items
for i, item in enumerate(items[:3]):
    title_elem = item.find('title')
    if title_elem is not None:
        title = title_elem.text
        print(f'\nItem {i+1}: {title}')
        
        # Test relevance
        is_relevant = tracker._is_relevant_news(title, ticker)
        print(f'  Relevance: {is_relevant}')
        
        # Test what keywords match
        keywords = tracker._create_search_keywords(ticker)
        matching_keywords = [kw for kw in keywords if kw.lower() in title.lower()]
        print(f'  Matching keywords: {matching_keywords}')