import sys
sys.stdout.reconfigure(encoding='utf-8')
import urllib.request
import urllib.parse
import json

queries = ["stocks", "market", "india", "rainfall", "road", "finance", "business", "horoscope", "cricket", "budget", "election"]

for q in queries:
    url = f"http://127.0.0.1:8000/api/pdf-search?q={urllib.parse.quote(q)}"
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode())
        results = data.get("results", [])
        by_src = {}
        for r in results:
            src = r.get("source_id")
            by_src[src] = by_src.get(src, 0) + 1
        print(f"Query '{q}': total {len(results)} -> {by_src}")
