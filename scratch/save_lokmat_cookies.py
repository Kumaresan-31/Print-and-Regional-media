import json
from pathlib import Path
from datetime import datetime, timezone

raw_cookie_arrays = [
    # Array 1 (Newest session activity)
    [
        {
            "domain": ".lokmat.com",
            "expirationDate": 1824396583.015756,
            "hostOnly": False,
            "httpOnly": False,
            "name": "_ga_V1GGXX48BX",
            "path": "/",
            "sameSite": None,
            "secure": False,
            "session": False,
            "storeId": None,
            "value": "GS2.1.s1789836065$o2$g1$t1789836583$j57$l0$h0"
        },
        {
            "domain": ".lokmat.com",
            "expirationDate": 1824396583.015964,
            "hostOnly": False,
            "httpOnly": False,
            "name": "_ga",
            "path": "/",
            "sameSite": None,
            "secure": False,
            "session": False,
            "storeId": None,
            "value": "GA1.1.795940722.1789816155"
        },
        {
            "domain": ".lokmat.com",
            "expirationDate": 1789836643,
            "hostOnly": False,
            "httpOnly": False,
            "name": "_gat",
            "path": "/",
            "sameSite": None,
            "secure": False,
            "session": False,
            "storeId": None,
            "value": "1"
        },
        {
            "domain": ".lokmat.com",
            "expirationDate": 1789922983,
            "hostOnly": False,
            "httpOnly": False,
            "name": "_gid",
            "path": "/",
            "sameSite": None,
            "secure": False,
            "session": False,
            "storeId": None,
            "value": "GA1.2.1113632655.1789816155"
        }
    ],
    # Array 2
    [
        {
            "domain": ".lokmat.com",
            "expirationDate": 1824396358.374625,
            "hostOnly": False,
            "httpOnly": False,
            "name": "_ga_V1GGXX48BX",
            "path": "/",
            "sameSite": None,
            "secure": False,
            "session": False,
            "storeId": None,
            "value": "GS2.1.s1789836065$o2$g1$t1789836358$j49$l0$h0"
        },
        {
            "domain": ".lokmat.com",
            "expirationDate": 1824396358.374866,
            "hostOnly": False,
            "httpOnly": False,
            "name": "_ga",
            "path": "/",
            "sameSite": None,
            "secure": False,
            "session": False,
            "storeId": None,
            "value": "GA1.1.795940722.1789816155"
        },
        {
            "domain": ".lokmat.com",
            "expirationDate": 1789922758,
            "hostOnly": False,
            "httpOnly": False,
            "name": "_gid",
            "path": "/",
            "sameSite": None,
            "secure": False,
            "session": False,
            "storeId": None,
            "value": "GA1.2.1113632655.1789816155"
        }
    ],
    # Array 3
    [
        {
            "domain": ".lokmat.com",
            "expirationDate": 1824396235.50034,
            "hostOnly": False,
            "httpOnly": False,
            "name": "_ga_V1GGXX48BX",
            "path": "/",
            "sameSite": None,
            "secure": False,
            "session": False,
            "storeId": None,
            "value": "GS2.1.s1789836065$o2$g1$t1789836235$j53$l0$h0"
        },
        {
            "domain": ".lokmat.com",
            "expirationDate": 1824396235.500621,
            "hostOnly": False,
            "httpOnly": False,
            "name": "_ga",
            "path": "/",
            "sameSite": None,
            "secure": False,
            "session": False,
            "storeId": None,
            "value": "GA1.1.795940722.1789816155"
        },
        {
            "domain": ".lokmat.com",
            "expirationDate": 1789922635,
            "hostOnly": False,
            "httpOnly": False,
            "name": "_gid",
            "path": "/",
            "sameSite": None,
            "secure": False,
            "session": False,
            "storeId": None,
            "value": "GA1.2.1113632655.1789816155"
        }
    ],
    # Array 4
    [
        {
            "domain": ".lokmat.com",
            "expirationDate": 1824396165.156836,
            "hostOnly": False,
            "httpOnly": False,
            "name": "_ga_V1GGXX48BX",
            "path": "/",
            "sameSite": None,
            "secure": False,
            "session": False,
            "storeId": None,
            "value": "GS2.1.s1789836065$o2$g1$t1789836165$j38$l0$h0"
        },
        {
            "domain": ".lokmat.com",
            "expirationDate": 1824396162.568624,
            "hostOnly": False,
            "httpOnly": False,
            "name": "_ga",
            "path": "/",
            "sameSite": None,
            "secure": False,
            "session": False,
            "storeId": None,
            "value": "GA1.1.795940722.1789816155"
        },
        {
            "domain": ".lokmat.com",
            "expirationDate": 1789836222,
            "hostOnly": False,
            "httpOnly": False,
            "name": "_gat",
            "path": "/",
            "sameSite": None,
            "secure": False,
            "session": False,
            "storeId": None,
            "value": "1"
        },
        {
            "domain": ".lokmat.com",
            "expirationDate": 1789922562,
            "hostOnly": False,
            "httpOnly": False,
            "name": "_gid",
            "path": "/",
            "sameSite": None,
            "secure": False,
            "session": False,
            "storeId": None,
            "value": "GA1.2.1113632655.1789816155"
        }
    ]
]

# Merge and deduplicate cookies, keeping the newest / longest expiration
cookie_map = {}
for arr in reversed(raw_cookie_arrays):  # Start from older, overwrite with newer
    for c in arr:
        name = c.get("name")
        if not name:
            continue
        key = (c.get("domain"), name, c.get("path", "/"))
        exp = c.get("expirationDate") or c.get("expires") or c.get("expiry")
        if exp and isinstance(exp, (int, float)) and exp > 0:
            c["expirationDate"] = exp
            c["expires"] = exp
            c["expiry"] = exp

        if key in cookie_map:
            existing_exp = cookie_map[key].get("expirationDate") or 0
            new_exp = exp or 0
            if new_exp >= existing_exp:
                cookie_map[key] = c
        else:
            cookie_map[key] = c

cookies = list(cookie_map.values())
cookies.sort(key=lambda x: (x.get("name", ""), x.get("domain", "")))

print(f"Total merged Lokmat cookies: {len(cookies)}")
for c in cookies:
    print(f"  - {c['name']} (exp: {c.get('expirationDate')}): {c['value'][:35]}...")

sessions_dir = Path(r"d:\Projects\VEE2\data\sessions")
sessions_dir.mkdir(parents=True, exist_ok=True)

timestamp = datetime.now(timezone.utc).isoformat()

# Target session files to populate
targets = [
    ("lokmat", "lokmat.json", None),
    ("lokmat_pune", "lokmat_pune.json", "pune"),
    ("lokmat_mumbai", "lokmat_mumbai.json", "mumbai"),
    ("lokmat_nagpur", "lokmat_nagpur.json", "nagpur"),
    ("lokmat_nashik", "lokmat_nashik.json", "nashik"),
    ("lokmat_aurangabad", "lokmat_aurangabad.json", "aurangabad"),
    ("lokmat_samachar", "lokmat_samachar.json", None),
    ("lokmat_samachar_nagpur", "lokmat_samachar_nagpur.json", "nagpur"),
    ("lokmat_samachar_aurangabad", "lokmat_samachar_aurangabad.json", "aurangabad"),
]

for src_id, fname, edition in targets:
    out_path = sessions_dir / fname
    session_data = {
        "source_id": src_id,
        "updated_at": timestamp,
        "cookies": cookies
    }
    if edition:
        session_data["edition"] = edition
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2)
    print(f"Saved {len(cookies)} cookies to {out_path}")

# Also save root lokmat_cookies.json
root_cookie_path = Path(r"d:\Projects\VEE2\lokmat_cookies.json")
with open(root_cookie_path, "w", encoding="utf-8") as f:
    json.dump(cookies, f, indent=2)
print(f"Saved {len(cookies)} cookies to {root_cookie_path}")
