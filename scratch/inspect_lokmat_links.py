import requests
from bs4 import BeautifulSoup

url = "https://epaper.lokmat.com/articlepage.php?catid=1&eddate=2026-09-20"
resp = requests.get(url, timeout=15)
soup = BeautifulSoup(resp.text, "html.parser")

links = [a.get("href") for a in soup.find_all("a") if a.get("href")]
print(f"Total links: {len(links)}")
edition_links = [l for l in links if any(k in l for k in ["eddate", "edition", "page", "catid", "pune", "mumbai"])]
print("Edition/page links:", edition_links[:20])
