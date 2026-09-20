import requests
from bs4 import BeautifulSoup
import re

url = "https://epaper.lokmat.com/main-editions/Pune%20Main/-1/1"
resp = requests.get(url, timeout=15)
soup = BeautifulSoup(resp.text, "html.parser")

for s in soup.find_all("script"):
    t = s.text
    if "showimageinframe" in t or "slides" in t or "slider1_container" in t:
        print("Script (first 1500 chars):")
        print(t[:1500])
