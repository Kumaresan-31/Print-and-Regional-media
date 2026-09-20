import requests
from bs4 import BeautifulSoup
import re

url = "https://epaper.lokmat.com/main-editions/Pune%20Main/-1/1"
resp = requests.get(url, timeout=15)
soup = BeautifulSoup(resp.text, "html.parser")

# Check map, area, or canvas
print("Maps count:", len(soup.find_all("map")))
print("Canvas count:", len(soup.find_all("canvas")))
print("Areas count:", len(soup.find_all("area")))

# Check all elements with style containing background or image
bg_elements = [el.get("style") for el in soup.find_all(style=True) if "image" in el.get("style", "").lower() or ".jpg" in el.get("style", "").lower() or ".png" in el.get("style", "").lower()]
print("Style background elements:", bg_elements)

# Check all IDs of div elements
div_ids = [d.get("id") for d in soup.find_all("div") if d.get("id")]
print("Div IDs:", div_ids[:20])

# Check what is inside main content divs
for div_id in ["pagecontent", "content", "main", "newspaper", "book", "holder", "magazine"]:
    el = soup.find(id=re.compile(div_id, re.IGNORECASE))
    if el:
        print(f"Found element {el.get('id')}:", str(el)[:300])
