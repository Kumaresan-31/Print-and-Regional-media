import requests, re

js_urls = [
    "https://epaperlokmat.in/js/footer1.js?v=1.1",
    "http://www.lokmat.com/epaper.js?v=0.1",
    "https://epaperlokmat.in/js/ttmenu.js"
]

for url in js_urls:
    try:
        resp = requests.get(url, timeout=10)
        print(f"=== {url} ({len(resp.text)} bytes) ===")
        # Search for image url construction
        matches = re.findall(r'(\w*image\w*|\w*img\w*|\w*thumb\w*|\w*page\w*)\s*[:=]\s*[^;\n]+', resp.text, re.IGNORECASE)
        for m in matches[:10]:
            print(" ", m[:100])
    except Exception as e:
        print(f"Failed {url}: {e}")
