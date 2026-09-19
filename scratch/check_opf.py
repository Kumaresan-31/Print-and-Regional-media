import urllib.request, ssl, re

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

req = urllib.request.Request(
    'https://epaper.thehindu.com/ccidist-ws/th/th_international/issues/204093/OPS/package.opf',
    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0', 'Referer': 'https://epaper.thehindu.com/reader'}
)
with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
    xml = r.read().decode('utf-8', errors='ignore')
    print('package.opf length:', len(xml))
    items = re.findall(r'href=["\']([^"\']+)["\']', xml)
    print('Total items in OPF:', len(items))
    images = [i for i in items if i.endswith('.jpg') or i.endswith('.png')]
    print('Total images in OPF:', len(images))
    page_images = [i for i in images if 'medium' in i or 'large' in i or 'page' in i]
    print('Page images:', len(page_images))
    for img in page_images[:10]:
        print(' -', img)
