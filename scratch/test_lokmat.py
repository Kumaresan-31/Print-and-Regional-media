import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from harvester.auth.session_manager import session_manager
import requests

cookies = session_manager.get_cookie_dict("lokmat")
print(f"Loaded {len(cookies)} cookies for lokmat: {list(cookies.keys())}")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
url = "https://epaper.lokmat.com/articlepage.php?catid=1&eddate=2026-09-20"
resp = requests.get(url, cookies=cookies, headers=headers, timeout=15)
print("Status code:", resp.status_code)
print("Content length:", len(resp.text))
print("HTML sample:", resp.text[:500])
