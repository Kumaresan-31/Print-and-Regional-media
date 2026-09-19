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

    # Compute with RapidOCR
    boxes: List[Dict[str, Any]] = []
    try:
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()
        res, _ = ocr(str(snapshot_path))
        if res:
            for item in res:
                box = item[0]
                txt = str(item[1]).strip()
                score = float(item[2]) if len(item) > 2 else 0.95
                boxes.append({
                    "text": txt,
                    "box": _clean_box_coords(box),
                    "score": round(score, 4)
                })
        if boxes:
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
        logger.warning(f"RapidOCR box generation failed on {snapshot_path}: {e}")

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
        q_hash = hashlib.md5(f"{query}_{story.get('id', '') if story else ''}".encode()).hexdigest()[:10]
        crop_dir = snapshot_path.parent / "crops"
        crop_dir.mkdir(parents=True, exist_ok=True)
        output_path = crop_dir / f"{snapshot_path.stem}_crop_{q_hash}.jpg"

    if output_path.exists():
        return output_path

    orig_img = Image.open(snapshot_path).convert("RGB")
    img_w, img_h = orig_img.size

    boxes_data = get_or_create_boxes(snapshot_path)

    # Tokenize query
    clean_q = query.strip().lower()
    q_tokens = [t for t in re.split(r"\s+", clean_q) if len(t) >= 2]
    if not q_tokens and clean_q:
        q_tokens = [clean_q]

    # Additional tokens from matched story (e.g. original language text)
    story_tokens = []
    story_title = ""
    if story:
        story_title = story.get("title") or story.get("original_title") or ""
        for field in ["title", "original_title", "snippet", "ocr_raw_text"]:
            val = story.get(field) or ""
            if isinstance(val, str) and val.strip():
                story_tokens.extend([w.lower() for w in re.split(r"\s+", val.strip())[:15] if len(w) >= 3])

    # Find matched boxes on the page
    direct_matched_boxes = []
    story_matched_boxes = []

    for item in boxes_data:
        box = item.get("box")
        txt = (item.get("text") or "").lower()
        if not box or len(box) < 4:
            continue

        # Check exact direct query match
        if any(t in txt for t in q_tokens):
            direct_matched_boxes.append((box, item.get("text", "")))
        # Check story correlation
        elif story_tokens and any(st in txt for st in story_tokens[:20]):
            story_matched_boxes.append((box, item.get("text", "")))

    targets = direct_matched_boxes if direct_matched_boxes else story_matched_boxes

    # If no text box matched, fallback to smart vertical page band based on story position
    if not targets:
        crop_x1 = max(0, int(img_w * 0.05))
        crop_x2 = min(img_w, int(img_w * 0.95))
        crop_y1 = max(0, int(img_h * 0.15))
        crop_y2 = min(img_h, int(img_h * 0.55))
        cropped = orig_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))
        cropped.save(output_path, "JPEG", quality=92)
        return output_path

    # Cluster matched boxes spatially to avoid averaging across opposite sides of the broadsheet
    reach_x = max(380, int(img_w * 0.35))
    reach_y = max(450, int(img_h * 0.25))

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

    # Compute crop boundary with generous padding scaled to image size
    pad_x = max(50, int(img_w * 0.045))
    pad_y = max(55, int(img_h * 0.035))
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

    # Crop
    cropped_img = orig_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))

    # Apply translucent golden highlight on matched lines inside this cluster
    overlay = Image.new("RGBA", cropped_img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    for b, txt in best_cluster["boxes"]:
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
            fill=(254, 240, 138, 140),   # vibrant translucent yellow
            outline=(245, 158, 11, 235),  # amber outline
            width=2,
        )

    # Alpha composite highlight onto crop
    final_clipping = Image.alpha_composite(cropped_img.convert("RGBA"), overlay).convert("RGB")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_clipping.save(output_path, "JPEG", quality=92)
    logger.info(f"Generated news crop for '{query}' at {output_path.name} ({final_clipping.size})")

    return output_path
