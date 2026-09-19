import json

files = [
    r'C:\Users\Kumaresan B\.gemini\antigravity-ide\brain\656b54cd-711e-4782-a975-cc8ac2ec9a3a\.user_uploaded\media_1789832866039.txt',
    r'C:\Users\Kumaresan B\.gemini\antigravity-ide\brain\656b54cd-711e-4782-a975-cc8ac2ec9a3a\.user_uploaded\media_1789832866016.txt',
    r'C:\Users\Kumaresan B\.gemini\antigravity-ide\brain\656b54cd-711e-4782-a975-cc8ac2ec9a3a\.user_uploaded\media_1789832866009.txt',
    r'C:\Users\Kumaresan B\.gemini\antigravity-ide\brain\656b54cd-711e-4782-a975-cc8ac2ec9a3a\.user_uploaded\media_1789832866006.txt'
]
# We load oldest to newest so newest overwrites
cookie_dict = {}
for fpath in files:
    with open(fpath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        for c in data:
            key = (c.get('domain'), c.get('name'), c.get('path'))
            cookie_dict[key] = c

print(f'Total unique cookies: {len(cookie_dict)}')
for (domain, name, path), c in sorted(cookie_dict.items(), key=lambda x: x[0][1]):
    print(f"{name:30} {domain:25} exp={c.get('expirationDate')} val={str(c.get('value'))[:30]}")
