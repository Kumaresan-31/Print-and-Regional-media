import json

data = json.load(open('data/hardcopy_uploads/90c09a843512.json', encoding='utf-8'))
arts = data.get('articles', [])
din = [a for a in arts if 'Dinamani' in str(a.get('pdf_file', ''))]

untranslated = [a for a in din if not a.get("is_translated") or any(0x0B80 <= ord(c) <= 0x0BFF for c in str(a.get("headline_english", ""))) or any(0x0B80 <= ord(c) <= 0x0BFF for c in str(a.get("content_english", "")))]

print(f"Total Dinamani: {len(din)}, Untranslated or partial Tamil: {len(untranslated)}")

for i, a in enumerate(untranslated[:10]):
    print(f"\n--- Untranslated #{i} Page {a.get('page_number')} (Cat: {a.get('category')}) ---")
    print("id:          ", a.get("id"))
    print("hl_orig:     ", a.get("headline_original"))
    print("hl_eng:      ", a.get("headline_english"))
    print("content_orig:", str(a.get("content_original", ""))[:80])
    print("content_eng: ", str(a.get("content_english", ""))[:80])
    print("snippet:     ", str(a.get("snippet", ""))[:80])
    print("title:       ", a.get("title"))
    print("is_translated:", a.get("is_translated"))
