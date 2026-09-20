import requests
from bs4 import BeautifulSoup
import json, re

url = "https://epaper.lokmat.com/main-editions/Pune%20Main/-1/1"
resp = requests.get(url, timeout=15)
print("Status code:", resp.status_code)
print("Final URL:", resp.url)
soup = BeautifulSoup(resp.text, "html.parser")
imgs = [img.get("src") for img in soup.find_all("img") if img.get("src")]
print("Found images:", len(imgs))
for img in imgs[:10]:
    print("  img:", img)

# Check for JSON/state data
for s in soup.find_all("script"):
    t = s.text
    if "editions" in t or "pages" in t or "Page" in t or ".jpg" in t:
        print("Script with pages/jpg:", t[:300].strip())
