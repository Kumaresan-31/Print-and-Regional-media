import urllib.request
import re

req = urllib.request.Request('https://epaper.loksatta.com/', headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode('utf-8', errors='ignore')
        # find links like /t/(\d+)/latest/([A-Za-z]+)
        matches = re.findall(r'/t/(\d+)/latest/([A-Za-z0-9_-]+)', html)
        print("Matches from homepage:", set(matches))
        # Also find /t/(\d+)/([A-Za-z0-9_-]+)
        matches2 = re.findall(r'/t/(\d+)/([A-Za-z0-9_-]+)', html)
        print("All /t/ matches:", set(matches2))
except Exception as e:
    print("Error:", e)
