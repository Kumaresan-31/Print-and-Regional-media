import re

with open('scratch/lokmat_pune_main.html', 'r', encoding='utf-8') as f:
    html = f.read()

matches = re.findall(r'https?://[^\s"\'<>]+', html)
for m in sorted(set(matches)):
    if any(k in m.lower() for k in ['enewspaper', 'amazonaws', 'news/lok', 'thumbnails', 'pages', 'pune']):
        print('URL:', m)

for line in html.splitlines():
    if any(k in line.lower() for k in ['enewspaper', 'totalpage', 'mapname', 'zoom', 'curpage']):
        print('LINE:', line.strip()[:140])
