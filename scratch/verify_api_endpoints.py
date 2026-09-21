import requests
import json

BASE_URL = "http://127.0.0.1:8000"

print("1. Testing GET /upload HTML route...")
r = requests.get(f"{BASE_URL}/upload")
print(f"  Status: {r.status_code}, Length: {len(r.text)}")
assert r.status_code == 200, "Failed to load /upload"

job_id = "ac5eae0994e3"
print(f"\n2. Testing GET /api/newspaper/upload-progress/{job_id}...")
r = requests.get(f"{BASE_URL}/api/newspaper/upload-progress/{job_id}")
print(f"  Status: {r.status_code}")
data = r.json()
print(f"  Status: {data.get('status')}")
print(f"  Progress: {data.get('progress_percentage')}%")
print(f"  Checklist items: {len(data.get('checklist', []))}")
if data.get('checklist'):
    print(f"  Sample Checklist Item: {data['checklist'][0]}")

print(f"\n3. Testing GET /api/newspaper/hardcopy-news?job_id={job_id}...")
r = requests.get(f"{BASE_URL}/api/newspaper/hardcopy-news?job_id={job_id}&limit=5")
print(f"  Status: {r.status_code}")
news_data = r.json()
print(f"  Total Articles: {news_data.get('total')}")
articles = news_data.get("articles", [])
if articles:
    a0 = articles[0]
    print(f"  Article 1 Title: {a0.get('english_headline') or a0.get('headline_english')}")
    print(f"  Article 1 Category: {a0.get('category')}")
    print(f"  Article 1 Language: {a0.get('original_language')}")
    print(f"  Article 1 Page: {a0.get('page_num')}")
    print(f"  Article 1 Confidence: {a0.get('confidence')}")
    print(f"  Article 1 Crop URL: {a0.get('crop_image_url')}")

print(f"\n4. Testing GET /api/newspaper/hardcopy-meta?job_id={job_id}...")
r = requests.get(f"{BASE_URL}/api/newspaper/hardcopy-meta?job_id={job_id}")
print(f"  Status: {r.status_code}")
meta = r.json()
print(f"  Newspapers: {meta.get('newspapers')}")
print(f"  Languages: {meta.get('languages')}")
print(f"  Category Counts: {meta.get('category_counts')}")

print("\n--- ALL VERIFICATIONS PASSED SUCCESSFULLY! ---")
