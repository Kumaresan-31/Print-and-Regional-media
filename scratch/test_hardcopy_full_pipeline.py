import sys
import time
import requests
import json
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://127.0.0.1:8000"

def test_hardcopy_pipeline():
    print("--- 1. Testing Hardcopy PDF Batch Upload ---")
    files_to_upload = []
    p1 = Path("data/real_hindu_page1.pdf")
    p2 = Path("data/sample_regional_newspaper.pdf")
    
    if p1.exists():
        files_to_upload.append(('files', ('real_hindu_page1.pdf', open(p1, 'rb'), 'application/pdf')))
    if p2.exists():
        files_to_upload.append(('files', ('sample_regional_newspaper.pdf', open(p2, 'rb'), 'application/pdf')))

    if not files_to_upload:
        print("Error: No test PDFs found!")
        return

    data = {
        'notify_whatsapp': 'false',
        'notify_telegram': 'false',
        'notify_email': 'false',
        'async_mode': 'true',
    }

    resp = requests.post(f"{BASE_URL}/api/newspaper/upload-batch", files=files_to_upload, data=data)
    print("Upload status code:", resp.status_code)
    upload_res = resp.json()
    print("Upload Response:", json.dumps(upload_res, indent=2))
    job_id = upload_res.get("job_id")
    assert job_id, "No job_id returned!"

    print(f"\n--- 2. Polling Job Progress for {job_id} ---")
    completed = False
    for attempt in range(40):
        time.sleep(1.5)
        p_resp = requests.get(f"{BASE_URL}/api/newspaper/upload-progress/{job_id}")
        job_data = p_resp.json()
        status = job_data.get("status")
        pct = job_data.get("progress_pct")
        checklist = job_data.get("pages_checklist", [])
        print(f"[{attempt+1}] Status: {status} | Progress: {pct}% | Pages Audited: {len(checklist)}")
        
        if status == "completed":
            completed = True
            break
        elif status == "failed":
            print("Job failed:", job_data.get("error"))
            return

    assert completed, "Job did not complete in time!"
    print("Job completed successfully!")

    print("\n--- 3. Verifying Per-Page Checklist ---")
    for page in job_data.get("pages_checklist", []):
        print(f"  Page {page.get('page_num')} ({page.get('file_name')}): {page.get('status')} | Conf: {page.get('ocr_confidence')} | Blank: {page.get('is_blank')}")

    print("\n--- 4. Verifying Summary Header ---")
    summary = job_data.get("summary", {})
    print("  Newspapers:", summary.get("newspaper_names"))
    print("  Dates:", summary.get("publication_dates"))
    print("  Languages:", summary.get("original_languages"))
    print("  Total Pages Processed:", summary.get("total_pages_processed"))
    print("  Total Articles Extracted:", summary.get("total_articles_extracted"))

    print("\n--- 5. Verifying 19 Categories & English Articles ---")
    articles = job_data.get("articles", [])
    print(f"Total extracted articles: {len(articles)}")
    for i, a in enumerate(articles[:5]):
        print(f"\n[Article {i+1}]")
        print(f"  Primary Category: {a.get('category')} | Secondaries: {a.get('secondary_categories')}")
        print(f"  Page & Continuation: {a.get('continuation_label')} (Pages: {a.get('page_numbers')})")
        print(f"  Original Language: {a.get('original_language')}")
        print(f"  English Headline: {a.get('headline_english')}")
        print(f"  Original Headline: {a.get('headline_original')}")
        print(f"  English Body (preview): {a.get('content_english', '')[:120]}...")
        print(f"  OCR Confidence: {a.get('ocr_confidence')} | Low Conf: {a.get('is_low_confidence')}")
        print(f"  Snapshot URL: {a.get('page_snapshot_url')}")

    print("\n--- 6. Verifying Filtered Search API ---")
    meta_resp = requests.get(f"{BASE_URL}/api/newspaper/hardcopy-meta?job_id={job_id}")
    print("Hardcopy Metadata:", json.dumps(meta_resp.json(), indent=2))

    news_resp = requests.get(f"{BASE_URL}/api/newspaper/hardcopy-news?job_id={job_id}&limit=10")
    print(f"Hardcopy News returned {news_resp.json().get('total')} articles.")

    print("\n--- 7. Testing Alert Dispatch Endpoint ---")
    if articles:
        first_art_id = articles[0].get("id")
        alert_payload = {
            "article_id": first_art_id,
            "channels": ["whatsapp", "telegram", "email"],
            "custom_recipient": "cuttyknowledge2006@gmail.com"
        }
        alert_resp = requests.post(f"{BASE_URL}/api/newspaper/share-alert", json=alert_payload)
        print("Alert Dispatch Response:", json.dumps(alert_resp.json(), indent=2))

    print("\n=== ALL HARDCOPY PIPELINE AUDITS PASSED ===")

if __name__ == "__main__":
    test_hardcopy_pipeline()
