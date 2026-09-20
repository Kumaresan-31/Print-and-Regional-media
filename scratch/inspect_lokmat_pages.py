import requests
from bs4 import BeautifulSoup
import re

url = "https://epaper.lokmat.com/main-editions/Pune%20Main/-1/1"
resp = requests.get(url, timeout=15)
soup = BeautifulSoup(resp.text, "html.parser")

# Find all images or elements with data- or thumb or carousal
thumbs = []
for el in soup.find_all(["img", "div", "li", "a"]):
    src = el.get("src") or el.get("data-src") or el.get("data-image") or el.get("data-large") or ""
    if "Thumbnails" in src or "eNewspaper" in src or ".jpg" in src:
        thumbs.append(src)

print("Found thumbnails/images:", len(thumbs))
for t in thumbs:
    print(" ", t)
