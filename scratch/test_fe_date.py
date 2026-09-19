import requests
import re

headers = {'User-Agent': 'Mozilla/5.0'}
r = requests.get('https://epaper.financialexpress.com/t/227/18-09-2026/Delhi', headers=headers)
print('Final URL:', r.url)
m = re.search(r'issueId\W+(\d+)', r.text)
if m:
    print('Found issueId:', m.group(1))
