import json
from pathlib import Path
from datetime import datetime, timezone

files = [
    r'C:\Users\Kumaresan B\.gemini\antigravity-ide\brain\656b54cd-711e-4782-a975-cc8ac2ec9a3a\.user_uploaded\media_1789832866039.txt',
    r'C:\Users\Kumaresan B\.gemini\antigravity-ide\brain\656b54cd-711e-4782-a975-cc8ac2ec9a3a\.user_uploaded\media_1789832866016.txt',
    r'C:\Users\Kumaresan B\.gemini\antigravity-ide\brain\656b54cd-711e-4782-a975-cc8ac2ec9a3a\.user_uploaded\media_1789832866009.txt',
    r'C:\Users\Kumaresan B\.gemini\antigravity-ide\brain\656b54cd-711e-4782-a975-cc8ac2ec9a3a\.user_uploaded\media_1789832866006.txt'
]

cookie_map = {}
for fpath in files:
    with open(fpath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        for c in data:
            key = (c.get('domain'), c.get('name'), c.get('path'))
            # Format cookie with standard expiration keys
            exp = c.get('expirationDate') or c.get('expires') or c.get('expiry')
            if exp:
                c['expirationDate'] = exp
                c['expires'] = exp
                c['expiry'] = exp
            cookie_map[key] = c

cookies = list(cookie_map.values())
# Sort for deterministic output
cookies.sort(key=lambda x: (x.get('name', ''), x.get('domain', '')))

print(f"Total merged cookies: {len(cookies)}")

sessions_dir = Path(r"d:\Projects\VEE2\data\sessions")
sessions_dir.mkdir(parents=True, exist_ok=True)

targets = [
    ("loksatta", "loksatta.json", None),
    ("loksatta_mumbai", "loksatta_mumbai.json", "mumbai"),
    ("loksatta_pune", "loksatta_pune.json", "pune"),
    ("loksatta_nagpur", "loksatta_nagpur.json", "nagpur"),
    ("loksatta_nashik", "loksatta_nashik.json", "nashik"),
]

for src_id, fname, edition in targets:
    out_path = sessions_dir / fname
    session_data = {
        "source_id": src_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cookies": cookies
    }
    if edition:
        session_data["edition"] = edition
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2)
    print(f"Saved {len(cookies)} cookies to {out_path}")

# Also save root loksatta_cookies.json
root_cookie_path = Path(r"d:\Projects\VEE2\loksatta_cookies.json")
with open(root_cookie_path, "w", encoding="utf-8") as f:
    json.dump(cookies, f, indent=2)
print(f"Saved {len(cookies)} cookies to {root_cookie_path}")
