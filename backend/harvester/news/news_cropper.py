"""
News Cropper & Highlighter Service
==================================
Identifies, crops, and highlights matched news articles from newspaper page snapshots.
Provides broadsheet-accurate article clippings with glowing keyword highlights.
"""

import io
import json
import logging
import hashlib
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image, ImageDraw

from harvester.config import settings, SNAPSHOTS_DIR

logger = logging.getLogger("harvester.news_cropper")

# Cache for OCR box results
_BOXES_CACHE: Dict[str, List[Dict[str, Any]]] = {}


def _clean_box_coords(box: Any) -> Any:
    """Recursively convert numpy arrays/scalars to pure Python floats/ints for JSON serialization."""
    if hasattr(box, "tolist"):
        return _clean_box_coords(box.tolist())
    if isinstance(box, (list, tuple)):
        return [_clean_box_coords(item) for item in box]
    if hasattr(box, "item"):
        return box.item()
    return box


def get_or_create_boxes(snapshot_path: Path) -> List[Dict[str, Any]]:
    """
    Loads precomputed OCR text boxes for a snapshot, or computes and caches them.
    """
    cache_key = str(snapshot_path)
    if cache_key in _BOXES_CACHE:
        return _BOXES_CACHE[cache_key]

    boxes_file = snapshot_path.with_suffix(".boxes.json")
    if boxes_file.exists():
        try:
            with open(boxes_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    boxes = json.loads(content)
                    if isinstance(boxes, list) and len(boxes) > 0:
                        _BOXES_CACHE[cache_key] = boxes
                        return boxes
        except Exception as e:
            logger.warning(f"Error reading boxes file {boxes_file}: {e}")

    # Compute using dual-engine run_ocr_on_image (supports all Indian regional scripts via Tesseract + RapidOCR)
    boxes: List[Dict[str, Any]] = []
    try:
        from harvester.news.pdf_parser import run_ocr_on_image
        _, _, computed_blocks = run_ocr_on_image(snapshot_path)
        if computed_blocks:
            boxes = computed_blocks
            try:
                clean_boxes = [
                    {"text": str(b.get("text", "")), "score": float(b.get("score", 0.9)), "box": _clean_box_coords(b.get("box"))}
                    for b in boxes
                ]
                with open(boxes_file, "w", encoding="utf-8") as f:
                    json.dump(clean_boxes, f, ensure_ascii=False)
            except Exception as e:
                logger.debug(f"Could not cache boxes to {boxes_file}: {e}")
    except Exception as e:
        logger.warning(f"Dual-engine box generation fallback failed on {snapshot_path}: {e}")

    _BOXES_CACHE[cache_key] = boxes
    return boxes


def generate_news_crop(
    snapshot_path: Path,
    query: str,
    story: Optional[Dict[str, Any]] = None,
    output_path: Optional[Path] = None
) -> Path:
    """
    Crops the specific news article matching the search query/story from the page snapshot,
    applies vibrant keyword highlights, and caches the result image.
    """
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")

    # Determine cache file if not provided
    if output_path is None:
        q_hash = hashlib.md5(f"v4_hl_{query}_{story.get('id', '') if story else ''}".encode()).hexdigest()[:10]
        crop_dir = snapshot_path.parent / "crops"
        crop_dir.mkdir(parents=True, exist_ok=True)
        output_path = crop_dir / f"{snapshot_path.stem}_crop_{q_hash}.jpg"

    if output_path.exists():
        return output_path

    orig_img = Image.open(snapshot_path).convert("RGB")
    img_w, img_h = orig_img.size

    # 0. DIRECT EXACT BOUNDING BOX CROPPING
    # If the article has an exact precomputed bounding box [bx1, by1, bx2, by2], crop that directly!
    bbox = story.get("bounding_box") if story else None
    if bbox and len(bbox) == 4:
        bx1, by1, bx2, by2 = bbox
        if bx2 > bx1 and by2 > by1:
            pad_x = 24
            pad_y = 20
            crop_x1 = max(0, int(bx1 - pad_x))
            crop_y1 = max(0, int(by1 - pad_y))
            crop_x2 = min(img_w, int(bx2 + pad_x))
            crop_y2 = min(img_h, int(by2 + pad_y))

            cropped = orig_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))

            overlay = Image.new("RGBA", cropped.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(overlay)

            # Elegant translucent headline highlight band (top portion of article)
            hl_h = min(int((by2 - by1) * 0.28), 70)
            hl_x1 = max(4, int(bx1 - crop_x1))
            hl_y1 = max(4, int(by1 - crop_y1))
            hl_x2 = min(cropped.width - 4, int(bx2 - crop_x1))
            hl_y2 = min(cropped.height - 4, int(by1 - crop_y1 + hl_h))

            draw.rounded_rectangle(
                [(hl_x1, hl_y1), (hl_x2, hl_y2)],
                radius=4,
                fill=(254, 240, 138, 120),    # gentle translucent yellow headline glow
                outline=(245, 158, 11, 210),   # crisp amber headline boundary
                width=2,
            )

            # Sleek subtle border around the entire clipping
            draw.rounded_rectangle(
                [(2, 2), (cropped.width - 3, cropped.height - 3)],
                radius=6,
                outline=(245, 158, 11, 190),
                width=2,
            )

            final_clipping = Image.alpha_composite(cropped.convert("RGBA"), overlay).convert("RGB")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            final_clipping.save(output_path, "JPEG", quality=93)
            logger.info(f"Direct bounding-box crop generated for article {story.get('id', '')} ({final_clipping.size})")
            return output_path

    boxes_data = get_or_create_boxes(snapshot_path)

    # Tokenize query
    clean_q = query.strip().lower()
    q_tokens = [t for t in re.split(r"\s+", clean_q) if len(t) >= 2]
    if not q_tokens and clean_q:
        q_tokens = [clean_q]

    # Additional tokens and lines from matched story
    story_tokens = []
    story_lines = []
    story_title = ""
    if story:
        story_title = (
            story.get("headline_original")
            or story.get("headline_english")
            or story.get("title")
            or story.get("original_title")
            or ""
        )
        for field in [
            "headline_original",
            "headline_english",
            "title",
            "original_title",
            "content_original",
            "content_english",
            "snippet",
            "ocr_raw_text",
            "body",
        ]:
            val = story.get(field) or ""
            if isinstance(val, str) and val.strip():
                for ln in val.splitlines():
                    ln_c = ln.strip().lower()
                    if len(ln_c) >= 3:
                        story_lines.append(ln_c)
                words = [w.lower().strip("\"'.,;:-!?।/\\()-") for w in re.split(r"\s+", val.strip()) if len(w) >= 2]
                for w in words[:60]:
                    if len(w) >= 2 and w not in story_tokens:
                        story_tokens.append(w)

    # Find matched boxes on the page
    direct_matched_boxes = []
    story_matched_boxes = []
    seen_box_texts = set()

    for item in boxes_data:
        box = item.get("box")
        txt = (item.get("text") or "").strip().lower()
        if not box or len(box) < 4 or not txt:
            continue

        txt_key = txt[:35]
        # Check exact direct query match
        if q_tokens and any(t in txt for t in q_tokens):
            if txt_key not in seen_box_texts:
                direct_matched_boxes.append((box, item.get("text", "")))
                seen_box_texts.add(txt_key)
        # Check story line / token correlation
        elif (story_lines and any(sl in txt or txt in sl for sl in story_lines if len(sl) >= 4)) or \
             (story_tokens and any(st in txt for st in story_tokens[:40])):
            if txt_key not in seen_box_texts:
                story_matched_boxes.append((box, item.get("text", "")))
                seen_box_texts.add(txt_key)

    # Combine direct query matches and story content matches
    targets = direct_matched_boxes + [b for b in story_matched_boxes if b not in direct_matched_boxes]

    # If no text box matched, fallback to focused upper column band
    if not targets:
        crop_x1 = max(0, int(img_w * 0.05))
        crop_x2 = min(img_w, int(img_w * 0.50))
        crop_y1 = max(0, int(img_h * 0.10))
        crop_y2 = min(img_h, int(img_h * 0.45))
        cropped = orig_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))

        overlay = Image.new("RGBA", cropped.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        draw.rounded_rectangle(
            [(4, 4), (cropped.width - 4, cropped.height - 4)],
            radius=6,
            outline=(245, 158, 11, 200),
            width=2,
        )
        final_fallback = Image.alpha_composite(cropped.convert("RGBA"), overlay).convert("RGB")
        final_fallback.save(output_path, "JPEG", quality=92)
        return output_path

    # Cluster matched boxes spatially within a single broadsheet column (~18% page width)
    reach_x = max(180, int(img_w * 0.18))
    reach_y = max(320, int(img_h * 0.20))

    clusters = []
    for b, txt in targets:
        bx = (min(pt[0] for pt in b) + max(pt[0] for pt in b)) / 2
        by = (min(pt[1] for pt in b) + max(pt[1] for pt in b)) / 2
        assigned = False
        for c in clusters:
            cx, cy = c["center"]
            if abs(bx - cx) <= reach_x and abs(by - cy) <= reach_y:
                c["boxes"].append((b, txt))
                all_b = [box for box, _ in c["boxes"]]
                c["center"] = (
                    sum((min(pt[0] for pt in box) + max(pt[0] for pt in box)) / 2 for box in all_b) / len(all_b),
                    sum((min(pt[1] for pt in box) + max(pt[1] for pt in box)) / 2 for box in all_b) / len(all_b),
                )
                assigned = True
                break
        if not assigned:
            clusters.append({"boxes": [(b, txt)], "center": (bx, by)})

    # Select best cluster: prefer cluster containing story title, else highest match density
    best_cluster = clusters[0]
    if len(clusters) > 1:
        if story_title:
            st_toks = [w.lower() for w in re.split(r"\s+", story_title) if len(w) >= 3]
            for c in clusters:
                if any(any(st in txt.lower() for st in st_toks) for _, txt in c["boxes"]):
                    best_cluster = c
                    break
        else:
            best_cluster = max(clusters, key=lambda c: len(c["boxes"]))

    center_m_x, center_m_y = best_cluster["center"]

    # Collect nearby article text boxes in the same column/story zone
    article_boxes = []
    for item in boxes_data:
        b = item.get("box")
        if not b or len(b) < 4:
            continue
        bx = (min(pt[0] for pt in b) + max(pt[0] for pt in b)) / 2
        by = (min(pt[1] for pt in b) + max(pt[1] for pt in b)) / 2
        if abs(bx - center_m_x) <= reach_x and abs(by - center_m_y) <= reach_y:
            article_boxes.append(b)

    active_boxes = article_boxes if article_boxes else [b for b, _ in best_cluster["boxes"]]

    # Compute crop boundary with tight padding scaled to article column
    pad_x = max(24, int(img_w * 0.02))
    pad_y = max(24, int(img_h * 0.02))
    min_w = max(280, int(img_w * 0.20))
    min_h = max(160, int(img_h * 0.12))

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

    # Crop
    cropped_img = orig_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))

    # Apply vibrant golden highlight on matched lines inside this cluster and a glowing border around the article
    overlay = Image.new("RGBA", cropped_img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    boxes_to_highlight = best_cluster.get("boxes", [])
    for b, txt in boxes_to_highlight:
        bx1 = min(pt[0] for pt in b) - crop_x1
        by1 = min(pt[1] for pt in b) - crop_y1
        bx2 = max(pt[0] for pt in b) - crop_x1
        by2 = max(pt[1] for pt in b) - crop_y1

        # Only highlight if inside crop boundary
        if bx2 <= 0 or by2 <= 0 or bx1 >= cropped_img.width or by1 >= cropped_img.height:
            continue

        draw.rounded_rectangle(
            [(bx1 - 4, by1 - 3), (bx2 + 4, by2 + 3)],
            radius=4,
            fill=(254, 240, 138, 140),   # vibrant translucent yellow highlight
            outline=(245, 158, 11, 235),  # glowing amber outline
            width=2,
        )

    # Draw a stylish glowing amber border around the overall matched article zone
    if boxes_to_highlight:
        all_hb = [box for box, _ in boxes_to_highlight]
        art_x1 = max(4, min(min(pt[0] for pt in b) for b in all_hb) - crop_x1 - 8)
        art_y1 = max(4, min(min(pt[1] for pt in b) for b in all_hb) - crop_y1 - 8)
        art_x2 = min(cropped_img.width - 4, max(max(pt[0] for pt in b) for b in all_hb) - crop_x1 + 8)
        art_y2 = min(cropped_img.height - 4, max(max(pt[1] for pt in b) for b in all_hb) - crop_y1 + 8)
        draw.rounded_rectangle(
            [(art_x1, art_y1), (art_x2, art_y2)],
            radius=6,
            outline=(245, 158, 11, 210),  # vibrant amber article boundary
            width=2,
        )

    final_clipping = Image.alpha_composite(cropped_img.convert("RGBA"), overlay).convert("RGB")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_clipping.save(output_path, "JPEG", quality=92)
    logger.info(f"Generated news crop for '{query}' at {output_path.name} ({final_clipping.size})")

    return output_path
