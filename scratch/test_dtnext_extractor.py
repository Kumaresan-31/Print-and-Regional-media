import asyncio
import json
import urllib.parse
import requests
from playwright.async_api import async_playwright
from harvester.auth.session_manager import session_manager

async def test_page_keys_intercept():
    cookies = session_manager.load_cookies('dt_next')
    print(f"Loaded {len(cookies)} cookies")
    
    page_keys = []
    issue_id = None
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
        )
        pw_cookies = [{'name': c['name'], 'value': c['value'], 'domain': c['domain'], 'path': c.get('path', '/')} for c in cookies]
        await context.add_cookies(pw_cookies)
        page = await context.new_page()
        
        async def on_response(response):
            nonlocal page_keys, issue_id
            url = response.url
            if 'GetPageKeys' in url and response.status == 200:
                try:
                    data = await response.json()
                    page_keys = data.get('PageKeys', [])
                    # Extract issue parameter from URL
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                    issue_id = qs.get('issue', [None])[0]
                    print(f"Intercepted GetPageKeys! Issue={issue_id}, Total keys={len(page_keys)}")
                except Exception as e:
                    print("Error parsing GetPageKeys JSON:", e)
                    
        page.on('response', on_response)
        
        print("Navigating to https://news.dtnext.in/dt-next...")
        await page.goto('https://news.dtnext.in/dt-next', wait_until='domcontentloaded', timeout=30000)
        
        # Wait up to 10 seconds for GetPageKeys to be intercepted
        for _ in range(20):
            if page_keys and issue_id:
                break
            await asyncio.sleep(0.5)
            
        print(f"Intercepted {len(page_keys)} page keys for issue {issue_id}")
        
        # Now test downloading all page images directly!
        downloaded = []
        for pk in page_keys:
            p_num = pk.get('PageNumber')
            key = pk.get('Key')
            ticket = urllib.parse.quote(key)
            img_url = f"https://i.prcdn.co/img?file={issue_id}&page={p_num}&scale=100&ticket={ticket}"
            
            # Download using requests with referer
            r = requests.get(img_url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://news.dtnext.in/'}, timeout=15)
            if r.status_code == 200:
                downloaded.append((p_num, len(r.content)))
                print(f"  [OK] Downloaded Page {p_num}: {len(r.content):,} bytes")
            else:
                print(f"  [FAIL] Page {p_num}: HTTP {r.status_code}")
                
        print(f"\nSUCCESS: Downloaded {len(downloaded)} / {len(page_keys)} authentic high-res pages!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(test_page_keys_intercept())
