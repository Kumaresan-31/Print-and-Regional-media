import urllib.request
import json

req = urllib.request.Request('https://epaper.loksatta.com/pagemeta/get/4200563/1-1', headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req) as resp:
    meta = json.loads(resp.read())
    p1 = meta['1']
    levels = p1.get('levels', {})
    lvl2 = levels.get('level2', {})
    chunks = lvl2.get('chunks', [])
    print("Level2 width:", lvl2.get("width"), "height:", lvl2.get("height"), "chunks:", len(chunks))
    jpg_chunks = [c for c in chunks if not c.get('url', '').endswith('.png')]
    png_chunks = [c for c in chunks if c.get('url', '').endswith('.png')]
    print("JPG chunks:", len(jpg_chunks), "PNG chunks:", len(png_chunks))
    if jpg_chunks:
        print("Sample JPG:", jpg_chunks[0])
    if png_chunks:
        print("Sample PNG:", png_chunks[0])
