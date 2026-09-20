import requests, json

headers = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://epaper.lokmat.com/"
}

base = "https://epaperlokmat.in/eNewspaper/"

for op in ["getImageDetails", "getThumbnailDetails", "getPageArticleDetails"]:
    url = f"{base}OutSourcingDataNew.php?operation={op}&selectedIssueId=LOK_PULK_20260920&data=2"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        print(f"=== {op} (status={r.status_code}, len={len(r.text)}) ===")
        print(r.text[:500])
    except Exception as e:
        print(f"Error {op}: {e}")
