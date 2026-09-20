import requests, re
r = requests.get("https://epaper.lokmat.com/lokmatsamachar", timeout=10)
m = re.search(r'issueidPdf\s*=\s*["\']([^"\']+)["\']', r.text)
print("Samachar issueid:", m.group(1) if m else "NOT_FOUND")
