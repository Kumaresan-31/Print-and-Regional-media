import sys
sys.path.insert(0, 'backend')
import re
from harvester.news.hardcopy_manager import hardcopy_manager
from harvester.news.news_cropper import get_or_create_boxes
from pathlib import Path

art = next(a for a in hardcopy_manager.get_articles(limit=2000) if a.get('id') == '83f2c8d96a24')
snap_path = Path('data/snapshots/f17dce123281/page_002.jpg')
boxes_data = get_or_create_boxes(snap_path)

print('Article id:', art.get('id'))
print('Headline:', repr(art.get('headline_english')))
print('Original:', repr(art.get('headline_original')))
print('Content:', repr(art.get('content_english', ''))[:150])

story_lines = []
story_tokens = []
for field in ['headline_original', 'headline_english', 'title', 'content_original', 'content_english', 'ocr_raw_text', 'snippet']:
    val = art.get(field) or ''
    if isinstance(val, str) and val.strip():
        for ln in val.splitlines():
            ln_c = ln.strip().lower()
            if len(ln_c) >= 3:
                story_lines.append(ln_c)
        for w in re.split(r'\s+', val.strip()):
            w_c = w.lower().strip("',;:.!?\"/\\()-।")
            if len(w_c) >= 3 and w_c not in story_tokens:
                story_tokens.append(w_c)

print('story_tokens:', story_tokens)

matched = []
for item in boxes_data:
    txt = (item.get('text') or '').strip().lower()
    if not txt:
        continue
    hit = False
    if story_lines and any(sl in txt or txt in sl for sl in story_lines if len(sl) >= 4):
        hit = True
    elif any(st in txt for st in story_tokens):
        hit = True
    if hit:
        matched.append(item.get('text'))

print('Matched boxes count:', len(matched))
for m in matched:
    print('  ->', repr(m))
