import requests
resp = requests.get("http://www.lokmat.com/epaper.js?v=0.1")
print(resp.text[:2000])
