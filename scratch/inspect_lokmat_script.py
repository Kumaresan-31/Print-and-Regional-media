import requests
from bs4 import BeautifulSoup

url = "https://epaper.lokmat.com/main-editions/Pune%20Main/-1/1"
resp = requests.get(url, timeout=15)
soup = BeautifulSoup(resp.text, "html.parser")
for s in soup.find_all("script"):
    if "baseUrl" in s.text:
        print(s.text[:3000])
