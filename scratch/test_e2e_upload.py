import requests
import time
import json
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"

def run_test():
    test_file = Path("data/uploads/20260918_204657_DocScanner_Hardcopy.pdf")
    if not test_file.exists():
        test_file = Path("data/sample_regional_newspaper.pdf")
    
    print(f"Uploading file: {test_file.name} ({test_file.stat().st_size / 1024 / 1024:.2f} MB)...")
    with open(test_file, "rb") as f:
        files = [('files', (test_file.name, f, 'application/pdf'))]
        data = {
            'notify_whatsapp': 'false',
            'notify_telegram': 'false',
            'notify_email': 'false',
            'async_mode': 'true',
        }
        res = requests.post(f"{BASE_URL}/api/newspaper/upload-batch", files=files, data=data)
    
    print(f"Upload response status: {res.status_code}")
    job_info = res.json()
    job_id = job_info.get("job_id")
    print(f"Job ID: {job_id}")
    assert job_id, "Missing job_id"

    print("Polling progress...")
    for i in range(50):
        time.sleep(2)
        pr = requests.get(f"{BASE_URL}/api/newspaper/upload-progress/{job_id}")
        data = pr.json()
        status = data.get("status")
        pct = data.get("progress_percentage")
        step = data.get("current_step")
        checklist = data.get("checklist", [])
        print(f"  [{i+1}] Status: {status} | Progress: {pct}% | Checklist Items: {len(checklist)} | Step: {step[:60]}...")
        if status in ("completed", "failed"):
            break

    print(f"\nFinal Status: {status}")
    if status == "completed":
        print(f"Total articles extracted: {len(data.get('articles', []))}")
        print(f"Summary: {json.dumps(data.get('summary', {}), indent=2)}")
        if checklist:
            for c in checklist:
                print(f"  Page Audit: {c.get('name')} -> Status: {c.get('status')}, Conf: {c.get('ocr_confidence')}")
        
        # Verify hardcopy-news query
        r_news = requests.get(f"{BASE_URL}/api/newspaper/hardcopy-news?job_id={job_id}&limit=3")
        articles = r_news.json().get("articles", [])
        print(f"\nQueried Hardcopy News Articles: {len(articles)}")
        if articles:
            a = articles[0]
            print(f"  Sample Article: {a.get('english_headline')}")
            print(f"  Category: {a.get('category')} (Confidence: {a.get('confidence')})")
            print(f"  Crop URL: {a.get('crop_image_url')}")
            print(f"  PDF URL: {a.get('pdf_download_url')}")
    else:
        print(f"Error details: {data.get('error')}")

if __name__ == "__main__":
    run_test()
