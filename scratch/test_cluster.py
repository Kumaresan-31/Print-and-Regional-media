import sys
sys.path.insert(0, 'backend')
import re
from PIL import Image, ImageDraw
import numpy as np
from pathlib import Path
from harvester.news.hardcopy_manager import hardcopy_manager
from harvester.news.news_cropper import get_or_create_boxes

art = next(a for a in hardcopy_manager.get_articles(limit=2000) if a.get('id') == '83f2c8d96a24')
snap_path = Path('data/snapshots/f17dce123281/page_002.jpg')
orig_img = Image.open(snap_path).convert("RGB")
img_w, img_h = orig_img.size
boxes_data = get_or_create_boxes(snap_path)

# Extract story text lines & tokens
story_tokens = []
for field in ['headline_original', 'headline_english', 'title', 'content_original', 'content_english', 'ocr_raw_text', 'snippet']:
    val = art.get(field) or ''
    if isinstance(val, str) and val.strip():
        for w in re.split(r'\s+', val.strip()):
            w_c = w.lower().strip("',;:.!?\"/\\()-।")
            if len(w_c) >= 3 and w_c not in story_tokens:
                story_tokens.append(w_c)

clean_q = (art.get('headline_english') or '').strip().lower()
q_tokens = [t for t in re.split(r'\s+', clean_q) if len(t) >= 2]

matched_boxes = []
for item in boxes_data:
    b = item.get('box')
    txt = (item.get('text') or '').strip().lower()
    if not b or len(b) < 4 or not txt:
        continue
    # Check if box contains query token or story token
    if any(t in txt for t in q_tokens) or any(st in txt for st in story_tokens):
        matched_boxes.append((b, item.get('text', '')))

print(f'Total matched story boxes: {len(matched_boxes)}')
for b, txt in matched_boxes:
    print('  Box:', repr(txt))

# Cluster near headline center
hl_box = matched_boxes[0][0]
center_x = (min(pt[0] for pt in hl_box) + max(pt[0] for pt in hl_box)) / 2
center_y = (min(pt[1] for pt in hl_box) + max(pt[1] for pt in hl_box)) / 2

reach_x = max(380, int(img_w * 0.35))
reach_y = max(450, int(img_h * 0.25))

story_cluster_boxes = []
for b, txt in matched_boxes:
    bx = (min(pt[0] for pt in b) + max(pt[0] for pt in b)) / 2
    by = (min(pt[1] for pt in b) + max(pt[1] for pt in b)) / 2
    if abs(bx - center_x) <= reach_x and abs(by - center_y) <= reach_y:
        story_cluster_boxes.append((b, txt))

print(f'Story cluster boxes: {len(story_cluster_boxes)}')
for b, txt in story_cluster_boxes:
    print('   ->', repr(txt))
