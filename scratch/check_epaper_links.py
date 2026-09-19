import urllib.request, ssl, re

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

req = urllib.request.Request('https://epaper.thehindu.com/', headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'})
try:
    with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
        html = r.read().decode('utf-8', errors='ignore')
        print('HTML length:', len(html))
        dates = re.findall(r'\d{4}[-/]\d{2}[-/]\d{2}', html)
        print('Found dates in The Hindu page:', list(set(dates))[:10])
        links = re.findall(r'href=["\']([^"\']+)["\']', html)
        reader_links = [l for l in links if 'reader' in l or 'edition' in l or 'epaper' in l]
        print('Reader links:', reader_links[:10])
except Exception as e:
    print('Error:', e)
