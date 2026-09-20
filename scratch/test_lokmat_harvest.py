import sys
import asyncio
from pathlib import Path
from datetime import datetime

backend_path = Path("backend").resolve()
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from harvester.registry import get_source
from harvester.extractors.factory import get_extractor

async def main():
    source = get_source("lokmat")
    print("Source config:", source)
    extractor = get_extractor(source)
    print("Extractor:", type(extractor))
    
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"Testing extraction for {today} edition pune...")
    temp_dir = Path("scratch/test_lokmat_temp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    def cb(curr, total, msg):
        print(f"[{curr}/{total}] {msg}")
        
    try:
        pages = await extractor.extract_pages(today, "pune", temp_dir, progress_callback=cb)
        print(f"Extracted {len(pages)} pages: {pages}")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
