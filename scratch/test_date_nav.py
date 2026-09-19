import asyncio
import urllib.parse
from playwright.async_api import async_playwright
from harvester.auth.session_manager import session_manager

async def main():
    cookies = session_manager.load_cookies('dt_next')
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        pw_cookies = [{'name': c['name'], 'value': c['value'], 'domain': c['domain'], 'path': c.get('path', '/')} for c in cookies]
        await context.add_cookies(pw_cookies)
        page = await context.new_page()

        page_keys = []
        issue_id = None
        async def on_response(response):
            nonlocal page_keys, issue_id
            if 'GetPageKeys' in response.url and response.status == 200:
                data = await response.json()
                page_keys = data.get('PageKeys', [])
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(response.url).query)
                issue_id = qs.get('issue', [None])[0]
                print(f"Intercepted GetPageKeys! Issue={issue_id}, count={len(page_keys)}")

        page.on('response', on_response)
        print("Navigating to https://news.dtnext.in/dt-next/20260919...")
        await page.goto("https://news.dtnext.in/dt-next/20260919", wait_until="domcontentloaded", timeout=25000)
        for _ in range(20):
            if page_keys and issue_id:
                break
            await asyncio.sleep(0.5)
        print(f"Result for /20260919: Issue={issue_id}, keys={len(page_keys)}")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
