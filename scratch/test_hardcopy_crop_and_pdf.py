import urllib.request
import json
import os
import sys

BASE_URL = "http://127.0.0.1:8000"

def test():
    print("1. Fetching articles...")
    req = urllib.request.Request(f"{BASE_URL}/api/newspaper/hardcopy-news?limit=10")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
        articles = data.get("articles", [])

    if not articles:
        print("FAIL: No articles found!")
        sys.exit(1)

    print(f"Found {len(articles)} articles.")
    art = articles[0]
    art_id = art["id"]
    print(f"Testing with Article ID: {art_id}")
    print(f"Headline English: {art.get('headline_english')[:60]}...")
    print(f"Content English length: {len(art.get('content_english', ''))}")

    # 2. Test Crop Endpoint
    print("\n2. Testing Real News Clipping Crop endpoint: /api/newspaper/article/{art_id}/crop ...")
    crop_url = f"{BASE_URL}/api/newspaper/article/{art_id}/crop"
    try:
        with urllib.request.urlopen(crop_url, timeout=15) as c_resp:
            c_data = c_resp.read()
            c_type = c_resp.headers.get("Content-Type")
            print(f"Crop HTTP Status: {c_resp.status}, Content-Type: {c_type}, Size: {len(c_data)} bytes")
            assert c_resp.status == 200
            assert "image" in c_type
            assert len(c_data) > 1000
            print(">>> SUCCESS: Real Article Clipping Crop is working!")
    except Exception as e:
        print(f"FAIL testing crop: {e}")

    # 3. Test PDF Export Endpoint
    print("\n3. Testing Article PDF Export endpoint: /api/newspaper/article/{art_id}/pdf ...")
    pdf_url = f"{BASE_URL}/api/newspaper/article/{art_id}/pdf"
    try:
        with urllib.request.urlopen(pdf_url, timeout=20) as p_resp:
            p_data = p_resp.read()
            p_type = p_resp.headers.get("Content-Type")
            p_disp = p_resp.headers.get("Content-Disposition")
            print(f"PDF HTTP Status: {p_resp.status}, Content-Type: {p_type}, Size: {len(p_data)} bytes")
            print(f"Content-Disposition: {p_disp}")
            assert p_resp.status == 200
            assert "pdf" in p_type
            assert len(p_data) > 5000
            print(">>> SUCCESS: Publication-Grade Article PDF Export is working!")
    except Exception as e:
        print(f"FAIL testing PDF export: {e}")

    # 4. Test Alert Share with PDF attachment
    print("\n4. Testing Alert Share with PDF attachment: /api/newspaper/share-alert ...")
    alert_payload = json.dumps({
        "article_id": art_id,
        "channels": ["telegram", "email"],
        "custom_recipient": "cuttyknowledge2006@gmail.com"
    }).encode("utf-8")

    alert_req = urllib.request.Request(
        f"{BASE_URL}/api/newspaper/share-alert",
        data=alert_payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(alert_req, timeout=30) as a_resp:
            a_data = json.loads(a_resp.read().decode())
            print(f"Alert Share Response: {json.dumps(a_data, indent=2)}")
            print(">>> SUCCESS: Alert Dispatch with PDF attachment is working!")
    except Exception as e:
        print(f"FAIL testing alert dispatch: {e}")

if __name__ == "__main__":
    test()
