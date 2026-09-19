import sys
sys.path.insert(0, 'backend')
import json
import re
from pathlib import Path
from PIL import Image, ImageDraw
from harvester.news.news_cropper import get_or_create_boxes

def smart_crop_test(snapshot_path, query, story=None):
    orig_img = Image.open(snapshot_path).convert("RGB")
    img_w, img_h = orig_img.size
    boxes_data = get_or_create_boxes(snapshot_path)

    clean_q = query.strip().lower()
    q_tokens = [t for t in re.split(r"\s+", clean_q) if len(t) >= 2] or [clean_q]

    # 1. Identify matched boxes
    direct_matches = []
    story_matches = []
    story_title = (story.get('title') or '') if story else ''
    story_tokens = [w.lower() for w in re.split(r"\s+", story_title) if len(w) >= 3] if story_title else []

    for item in boxes_data:
        box = item.get("box")
        txt = (item.get("text") or "").lower()
        if not box or len(box) < 4:
            continue
        # Direct query match
        if any(t in txt for t in q_tokens):
            direct_matches.append((box, item.get("text", "")))
        elif story_tokens and any(st in txt for st in story_tokens[:10]):
            story_matches.append((box, item.get("text", "")))

    targets = direct_matches if direct_matches else story_matches
    if not targets:
        print("No targets found!")
        return None

    print(f"Found {len(direct_matches)} direct matches, {len(story_matches)} story matches")

    # 2. Cluster matched boxes spatially to avoid averaging across opposite sides of the page
    reach_x = max(380, int(img_w * 0.35))
    reach_y = max(450, int(img_h * 0.25))

    clusters = []
    for b, txt in targets:
        bx = (min(pt[0] for pt in b) + max(pt[0] for pt in b)) / 2
        by = (min(pt[1] for pt in b) + max(pt[1] for pt in b)) / 2
        assigned = False
        for c in clusters:
            cx, cy = c['center']
            if abs(bx - cx) <= reach_x and abs(by - cy) <= reach_y:
                c['boxes'].append((b, txt))
                # update center
                all_b = [box for box, _ in c['boxes']]
                c['center'] = (
                    sum((min(pt[0] for pt in box) + max(pt[0] for pt in box)) / 2 for box in all_b) / len(all_b),
                    sum((min(pt[1] for pt in box) + max(pt[1] for pt in box)) / 2 for box in all_b) / len(all_b),
                )
                assigned = True
                break
        if not assigned:
            clusters.append({'boxes': [(b, txt)], 'center': (bx, by)})

    print(f"Grouped into {len(clusters)} spatial cluster(s)")
    # Pick best cluster: prefer cluster matching story title or cluster with most matches
    best_cluster = clusters[0]
    if len(clusters) > 1:
        if story_title:
            st_lower = story_title.lower()
            for c in clusters:
                if any(any(st in txt.lower() for st in story_tokens) for _, txt in c['boxes']):
                    best_cluster = c
                    break
        else:
            best_cluster = max(clusters, key=lambda c: len(c['boxes']))

    center_m_x, center_m_y = best_cluster['center']
    print(f"Selected cluster center: ({center_m_x:.1f}, {center_m_y:.1f}) with {len(best_cluster['boxes'])} boxes")

    # 3. Collect all nearby article text boxes in the same column/story zone
    article_boxes = []
    for item in boxes_data:
        b = item.get("box")
        if not b or len(b) < 4:
            continue
        bx = (min(pt[0] for pt in b) + max(pt[0] for pt in b)) / 2
        by = (min(pt[1] for pt in b) + max(pt[1] for pt in b)) / 2
        if abs(bx - center_m_x) <= reach_x and abs(by - center_m_y) <= reach_y:
            article_boxes.append(b)

    active_boxes = article_boxes if article_boxes else [b for b, _ in best_cluster['boxes']]

    # 4. Crop boundary
    pad_x = max(55, int(img_w * 0.045))
    pad_y = max(60, int(img_h * 0.035))
    min_w = max(520, int(img_w * 0.42))
    min_h = max(360, int(img_h * 0.20))

    crop_x1 = max(0, int(min(min(pt[0] for pt in b) for b in active_boxes) - pad_x))
    crop_y1 = max(0, int(min(min(pt[1] for pt in b) for b in active_boxes) - pad_y))
    crop_x2 = min(img_w, int(max(max(pt[0] for pt in b) for b in active_boxes) + pad_x))
    crop_y2 = min(img_h, int(max(max(pt[1] for pt in b) for b in active_boxes) + pad_y))

    if (crop_x2 - crop_x1) < min_w:
        cx = (crop_x1 + crop_x2) // 2
        crop_x1 = max(0, cx - min_w // 2)
        crop_x2 = min(img_w, crop_x1 + min_w)
    if (crop_y2 - crop_y1) < min_h:
        cy = (crop_y1 + crop_y2) // 2
        crop_y1 = max(0, cy - min_h // 2)
        crop_y2 = min(img_h, crop_y1 + min_h)

    print(f"Crop box: [{crop_x1}, {crop_y1}, {crop_x2}, {crop_y2}], size: {crop_x2-crop_x1}x{crop_y2-crop_y1}")
    cropped_img = orig_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))

    # Highlight
    overlay = Image.new("RGBA", cropped_img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    for b, txt in best_cluster['boxes']:
        bx1 = min(pt[0] for pt in b) - crop_x1
        by1 = min(pt[1] for pt in b) - crop_y1
        bx2 = max(pt[0] for pt in b) - crop_x1
        by2 = max(pt[1] for pt in b) - crop_y1
        if bx2 <= 0 or by2 <= 0 or bx1 >= cropped_img.width or by1 >= cropped_img.height:
            continue
        draw.rounded_rectangle(
            [(bx1 - 4, by1 - 3), (bx2 + 4, by2 + 3)],
            radius=4,
            fill=(254, 240, 138, 140),
            outline=(245, 158, 11, 235),
            width=2,
        )

    final_clipping = Image.alpha_composite(cropped_img.convert("RGBA"), overlay).convert("RGB")
    return final_clipping

# Test on Financial Express
fe_snap = Path('data/snapshots/38bbe6d6d44b/page_001.jpg')
fe_clip = smart_crop_test(fe_snap, 'stocks', {'title': "2 stocks playing India's textile opportunity differently"})
if fe_clip:
    fe_clip.save('scratch/test_fe_smart_crop.jpg')
    print("Saved scratch/test_fe_smart_crop.jpg, size:", fe_clip.size)

# Test on Loksatta
lok_snap = Path('data/snapshots/8a21ade82909/page_001.jpg')
lok_clip = smart_crop_test(lok_snap, 'horoscope', {'title': "Weekly Horoscope - Loksatta"})
if lok_clip:
    lok_clip.save('scratch/test_lok_smart_crop.jpg')
    print("Saved scratch/test_lok_smart_crop.jpg, size:", lok_clip.size)
