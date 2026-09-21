import json
from pathlib import Path

f = sorted(Path("data/hardcopy_uploads").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[0]
data = json.loads(f.read_text(encoding="utf-8"))
arts = data.get("articles", [])
out = []
out.append(f"LATEST FILE: {f.name}")
out.append(f"Total articles: {len(arts)}")
if arts:
    a0 = arts[0]
    out.append("KEYS in article 0:")
    for k, v in a0.items():
        val_str = repr(v)
        if len(val_str) > 150:
            val_str = val_str[:150] + "..."
        out.append(f"  {k}: {val_str}")

Path("scratch/article_0_dump.txt").write_text("\n".join(out), encoding="utf-8")
print("Wrote scratch/article_0_dump.txt successfully")
