import urllib.request
import json

with urllib.request.urlopen('http://127.0.0.1:8000/api/pdf-index/status') as resp:
    status = json.loads(resp.read().decode())
    print('Index status:', json.dumps(status, indent=2))

for q, src in [('government', 'dt_next'), ('horoscope', 'loksatta'), ('stocks', 'financial_express'), ('report', 'loksatta'), ('jefferies', 'financial_express')]:
    url = f'http://127.0.0.1:8000/api/pdf-search?q={q}&source_ids={src}'
    try:
        with urllib.request.urlopen(url) as resp:
            res = json.loads(resp.read().decode())
            results = res.get('results', [])
            print(f'Query "{q}" on {src}: {len(results)} results')
            if results:
                r0 = results[0]
                print(f'   crop_url: {r0.get("crop_url")}')
                print(f'   snapshot_url: {r0.get("snapshot_url")}')
                # Test fetching crop_url and snapshot_url
                crop_test_url = f'http://127.0.0.1:8000{r0.get("crop_url")}'
                snap_test_url = f'http://127.0.0.1:8000{r0.get("snapshot_url")}'
                try:
                    with urllib.request.urlopen(crop_test_url) as c_resp:
                        print(f'   -> crop status: {c_resp.status}, size: {len(c_resp.read())} bytes')
                except Exception as ce:
                    print(f'   -> CROP FETCH FAILED: {ce}')
                try:
                    with urllib.request.urlopen(snap_test_url) as s_resp:
                        print(f'   -> snap status: {s_resp.status}, size: {len(s_resp.read())} bytes')
                except Exception as se:
                    print(f'   -> SNAP FETCH FAILED: {se}')
    except Exception as e:
        print(f'Query "{q}" on {src} FAILED: {e}')
