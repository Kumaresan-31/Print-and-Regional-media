import cv2
import numpy as np
from pathlib import Path
import pytesseract
import os
import json

tess_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(tess_path):
    pytesseract.pytesseract.tesseract_cmd = tess_path
os.environ["TESSDATA_PREFIX"] = str(Path("data/tessdata").resolve())

def extract_newspaper_articles_from_image(img_path: Path, lang: str = "mal"):
    img = cv2.imread(str(img_path))
    h, w = img.shape[:2]
    
    data = pytesseract.image_to_data(img, lang=lang, config="--psm 1", output_type=pytesseract.Output.DICT)
    
    n_boxes = len(data["level"])
    words = []
    line_dict = {}
    for i in range(n_boxes):
        txt = (data["text"][i] or "").strip()
        if not txt:
            continue
        x, y, bw, bh = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        b_num = data["block_num"][i]
        p_num = data["par_num"][i]
        l_num = data["line_num"][i]
        conf = float(data["conf"][i]) if data["conf"][i] != "-1" else 75.0
        
        words.append({
            "text": txt, "x": x, "y": y, "w": bw, "h": bh,
            "block": b_num, "par": p_num, "line": l_num, "conf": conf
        })
        
        line_key = (b_num, p_num, l_num)
        if line_key not in line_dict:
            line_dict[line_key] = {
                "words": [txt],
                "x1": x, "y1": y, "x2": x + bw, "y2": y + bh,
                "block": b_num, "par": p_num, "line": l_num,
                "avg_h": bh,
                "confs": [conf]
            }
        else:
            ld = line_dict[line_key]
            ld["words"].append(txt)
            ld["x1"] = min(ld["x1"], x)
            ld["y1"] = min(ld["y1"], y)
            ld["x2"] = max(ld["x2"], x + bw)
            ld["y2"] = max(ld["y2"], y + bh)
            ld["confs"].append(conf)
            
    lines = list(line_dict.values())
    if not lines:
        return []
    
    median_h = np.median([l["y2"] - l["y1"] for l in lines])
    
    # Exclude masthead at top 6% of page
    masthead_cutoff = int(h * 0.06)
    
    par_dict = {}
    for l in lines:
        if l["y1"] < masthead_cutoff:
            continue
        pkey = (l["block"], l["par"])
        if pkey not in par_dict:
            par_dict[pkey] = {
                "lines": [l],
                "text": " ".join(l["words"]),
                "x1": l["x1"], "y1": l["y1"], "x2": l["x2"], "y2": l["y2"],
                "max_h": l["y2"] - l["y1"]
            }
        else:
            p = par_dict[pkey]
            p["lines"].append(l)
            p["text"] += " " + " ".join(l["words"])
            p["x1"] = min(p["x1"], l["x1"])
            p["y1"] = min(p["y1"], l["y1"])
            p["x2"] = max(p["x2"], l["x2"])
            p["y2"] = max(p["y2"], l["y2"])
            p["max_h"] = max(p["max_h"], l["y2"] - l["y1"])
            
    paragraphs = list(par_dict.values())
    paragraphs.sort(key=lambda p: (p["y1"], p["x1"]))
    
    headlines = []
    body_blocks = []
    
    for p in paragraphs:
        p_text = p["text"].strip()
        words_count = len(p_text.split())
        # Filter out random single-word noise
        if len(p_text) < 4:
            continue
            
        is_headline = (p["max_h"] >= median_h * 1.35 and words_count <= 25) or (p["max_h"] >= median_h * 1.6)
        
        if is_headline and words_count >= 2:
            headlines.append(p)
        elif len(p_text) >= 15:
            body_blocks.append(p)
            
    articles = []
    assigned_body = set()
    
    for h_idx, hl in enumerate(headlines):
        hl_box = [hl["x1"], hl["y1"], hl["x2"], hl["y2"]]
        hl_text = hl["text"].strip()
        
        next_hl_y = h
        for other_hl in headlines:
            if other_hl["y1"] > hl["y2"] + 20 and not (other_hl["x2"] < hl["x1"] - 40 or other_hl["x1"] > hl["x2"] + 40):
                next_hl_y = min(next_hl_y, other_hl["y1"])
                
        matched_bodies = []
        for b_idx, bb in enumerate(body_blocks):
            if b_idx in assigned_body:
                continue
            h_overlap = max(0, min(hl["x2"] + 60, bb["x2"]) - max(hl["x1"] - 60, bb["x1"]))
            bb_w = bb["x2"] - bb["x1"]
            if h_overlap > 0.4 * min(bb_w, hl["x2"] - hl["x1"]):
                if hl["y1"] - 20 <= bb["y1"] <= next_hl_y + 30:
                    matched_bodies.append((b_idx, bb))
                    
        matched_bodies.sort(key=lambda item: (item[1]["x1"] // 150, item[1]["y1"]))
        
        article_text_parts = []
        art_x1, art_y1, art_x2, art_y2 = hl["x1"], hl["y1"], hl["x2"], hl["y2"]
        
        for b_idx, bb in matched_bodies:
            assigned_body.add(b_idx)
            article_text_parts.append(bb["text"].strip())
            art_x1 = min(art_x1, bb["x1"])
            art_y1 = min(art_y1, bb["y1"])
            art_x2 = max(art_x2, bb["x2"])
            art_y2 = max(art_y2, bb["y2"])
            
        body_text = "\n".join(article_text_parts).strip()
        if len(body_text) < 20:
            body_text = hl_text
            
        articles.append({
            "headline": hl_text,
            "body": body_text,
            "bbox": [int(art_x1), int(art_y1), int(art_x2), int(art_y2)],
            "word_count": len((hl_text + " " + body_text).split())
        })
        
    for b_idx, bb in enumerate(body_blocks):
        if b_idx not in assigned_body and len(bb["text"].strip()) > 80:
            lines_in_bb = bb["lines"]
            h_line = lines_in_bb[0]["words"]
            art_hl = " ".join(h_line)
            art_body = bb["text"][len(art_hl):].strip() or art_hl
            articles.append({
                "headline": art_hl,
                "body": art_body,
                "bbox": [int(bb["x1"]), int(bb["y1"]), int(bb["x2"]), int(bb["y2"])],
                "word_count": len(bb["text"].split())
            })
            
    # Filter out trivial fragments (< 10 words and small bbox)
    clean_articles = []
    for a in articles:
        bw = a["bbox"][2] - a["bbox"][0]
        bh = a["bbox"][3] - a["bbox"][1]
        if a["word_count"] >= 8 and (bw >= 150 or bh >= 60):
            clean_articles.append(a)
            
    return clean_articles

arts = extract_newspaper_articles_from_image(Path("scratch/rendered_page_300dpi.jpg"), lang="mal")

out = []
for idx, a in enumerate(arts):
    out.append({
        "id": idx + 1,
        "headline": a["headline"],
        "body_preview": a["body"][:200],
        "bbox": a["bbox"],
        "word_count": a["word_count"]
    })

Path("scratch/extracted_articles_test.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Successfully extracted {len(arts)} clean articles to scratch/extracted_articles_test.json")
