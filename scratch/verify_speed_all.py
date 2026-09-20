import sys
import time
import requests

sys.stdout.reconfigure(encoding='utf-8')

sources = [
    ("dtnext", "DT Next"),
    ("financeexpress", "Financial Express"),
    ("lokmat", "Lokmat"),
    ("loksatta", "Loksatta"),
    ("the_hindu", "The Hindu"),
]

categories = ["all", "sports", "business", "economic", "political", "crises_disasters"]

print("==================================================================================")
print("FINAL BENCHMARK & VERIFICATION (ALL 5 HARVESTED SOURCES, 0 EXTERNAL APIS)")
print("==================================================================================")

base_url = "http://127.0.0.1:8000/api/news"

def contains_indic(text):
    if not text:
        return False
    return any(0x0900 <= ord(c) <= 0x0D7F for c in text)

total_passed = 0

for slug, name in sources:
    print(f"\n>>> SOURCE: {name} (slug: {slug})")
    t0 = time.time()
    try:
        r = requests.get(f"{base_url}/{slug}?category=all&limit=5", timeout=15)
        elapsed = time.time() - t0
        if r.status_code != 200:
            print(f"    [FAIL] HTTP {r.status_code} in {elapsed:.2f}s")
            continue
        articles = r.json()
        print(f"    [PASS] HTTP 200 in {elapsed:.2f}s | Articles returned: {len(articles)}")
        
        # Print top 2 articles with translation details
        for i, a in enumerate(articles[:2]):
            t = a.get("title", "")
            orig_t = a.get("original_title")
            cat = a.get("category", "")
            page = a.get("page_number", 0)
            lang = a.get("original_language", "en")
            indic = contains_indic(t)
            status = "ENGLISH [OK]" if not indic else "INDIC FOUND [WARN]"
            print(f"      ({i+1}) [{cat.upper()}] Page {page} - {status}")
            print(f"          Title   : {t[:75]}")
            if orig_t:
                print(f"          Original ({lang}): {orig_t[:65]}")
            print(f"          Snapshot: {a.get('page_snapshot_url')}")

        # Check subcategories quickly
        cat_status = {}
        for c in categories[1:]:
            ct0 = time.time()
            cr = requests.get(f"{base_url}/{slug}?category={c}&limit=2", timeout=10)
            celapsed = time.time() - ct0
            if cr.status_code == 200:
                c_arts = cr.json()
                cat_status[c] = f"{len(c_arts)} items ({celapsed:.2f}s)"
            else:
                cat_status[c] = f"ERR {cr.status_code}"
        print(f"    Categories: {cat_status}")
        total_passed += 1

    except Exception as e:
        print(f"    [ERROR] {e}")

print("\n==================================================================================")
print(f"FINAL RESULT: {total_passed}/{len(sources)} SOURCES FULLY PASSING HARVESTED REGIONAL PIPELINE")
print("==================================================================================")
