import json
from datetime import datetime

with open('d:/Projects/VEE2/data/sessions/loksatta.json') as f:
    data = json.load(f)

cookies = data['cookies']
now_ts = datetime.now().timestamp()
auth_keys = ('token', 'auth', 'jwt', 'sso', 'user', 'session', 'rwmy', 'upssid', 'fpid')
skip_names = ('_gat', '_gid', '_dc_gtm', '_chartbeat', 'sessiontraffic')

auth_cookies = [
    c for c in cookies 
    if any(k in c.get('name', '').lower() for k in auth_keys)
    and not any(s in c.get('name', '').lower() for s in skip_names)
]

print(f'Found {len(auth_cookies)} auth cookies:')
for c in auth_cookies:
    exp = c.get('expires') or c.get('expirationDate')
    dt = datetime.fromtimestamp(exp) if exp else None
    print(f"  {c['name']}: exp={dt}, is_future={exp > now_ts if exp else None}")
