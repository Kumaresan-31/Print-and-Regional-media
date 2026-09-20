import sys
from bs4 import BeautifulSoup
import re

sys.stdout.reconfigure(encoding='utf-8')

with open('scratch/lokmat_page.html', 'r', encoding='utf-8') as f:
    html = f.read()

soup = BeautifulSoup(html, 'html.parser')

print('Title:', repr(soup.title.string if soup.title else 'No title'))

print('--- Links with edition / article / eddate / lokmat ---')
seen = set()
for a in soup.find_all('a', href=True):
    href = a['href']
    if any(k in href.lower() for k in ['pune', 'mumbai', 'edition', 'eddate', 'lokmat', 'article']):
        txt = a.get_text(strip=True).encode('ascii', 'replace').decode('ascii')
        if href not in seen:
            seen.add(href)
            print(f'{txt[:30]:<32} -> {href}')

print('\n--- Scripts mentioning page, edition, or cdn ---')
for s in soup.find_all('script'):
    content = s.string or ''
    if any(k in content for k in ['edition', 'page', 'cdn', 'image', 'eddate', 'zoom']):
        for line in content.splitlines():
            if any(k in line.lower() for k in ['edition', 'date', 'pune', 'mumbai', 'page', 'article', 'url', 'cdn']):
                l = line.strip().encode('ascii', 'replace').decode('ascii')
                if len(l) < 160:
                    print('JS:', l)
