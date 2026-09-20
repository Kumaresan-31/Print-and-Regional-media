import requests, re
from bs4 import BeautifulSoup

editions = {
    "pune": "https://epaper.lokmat.com/main-editions/Pune%20Main/-1/1",
    "mumbai": "https://epaper.lokmat.com/main-editions/Mumbai%20Main/-1/1",
    "nagpur": "https://epaper.lokmat.com/main-editions/Nagpur%20Main/-1/1",
    "nashik": "https://epaper.lokmat.com/main-editions/Nashik%20Main/-1/1",
    "aurangabad": "https://epaper.lokmat.com/main-editions/Aurangabad%20Main/-1/1",
}

for ed, url in editions.items():
    try:
        r = requests.get(url, timeout=10)
        m = re.search(r'issueidPdf\s*=\s*["\']([^"\']+)["\']', r.text)
        issue_id = m.group(1) if m else "NOT_FOUND"
        print(f"Edition {ed}: issueid={issue_id}")
    except Exception as e:
        print(f"Edition {ed} error: {e}")
