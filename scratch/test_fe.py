import requests
import re
import json

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Cookie': 'rwmypublications=335%2C629%2C434%2C628%2C630'
}

r = requests.get('https://epaper.financialexpress.com/4200680/Delhi/September-19-2026', headers=headers)
print('Length:', len(r.text))

# Search for JSON or javascript configurations
matches = re.findall(r'var\s+(\w+)\s*=\s*([^\n;]+)', r.text)
for var_name, var_val in matches:
    if any(k in var_name.lower() for k in ['page', 'edition', 'issue', 'readwhere', 'config', 'book']):
        print(f'{var_name}: {var_val[:120]}')

for script in re.findall(r'<script[^>]*>(.*?)</script>', r.text, re.DOTALL):
    if 'pages' in script or 'readwhere' in script or 'cdn' in script:
        for line in script.splitlines():
            if any(k in line for k in ['pages', 'total_pages', 'readwhere.com', 'manifest', 'device_type', 'initBook']):
                print('Script line:', line.strip()[:140])
