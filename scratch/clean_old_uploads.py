from pathlib import Path
import json

# Check the old files that contain 'Give the whip'
bad_files = []
for p in Path("data/hardcopy_uploads").glob("*.json"):
    try:
        txt = p.read_text(encoding="utf-8")
        if "Give the whip" in txt or "September 110101" in txt:
            bad_files.append(p)
    except Exception:
        pass

print(f"Found {len(bad_files)} old uploads with garbled text:")
for bf in bad_files:
    print(" -", bf.name)
    # Move to a backup folder or remove so hardcopy_manager doesn't serve old garbled mock-looking data
    backup_dir = Path("data/hardcopy_uploads/old_garbled_backup")
    backup_dir.mkdir(exist_ok=True)
    bf.replace(backup_dir / bf.name)

print("Moved old garbled files to data/hardcopy_uploads/old_garbled_backup/")
