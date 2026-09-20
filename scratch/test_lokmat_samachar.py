import requests, re
from bs4 import BeautifulSoup

r = requests.get("https://epaper.lokmat.com/articlepage.php?catid=1", timeout=10)
soup = BeautifulSoup(r.text, "html.parser")
samachar_links = [a.get("href") for a in soup.find_all("a") if "samachar" in (a.get("href") or "").lower() or "hindi" in (a.get("href") or "").lower()]
print("Samachar links:", samachar_links)
