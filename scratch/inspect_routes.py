import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from harvester.api.app import app

for route in app.routes:
    if hasattr(route, 'path'):
        methods = getattr(route, 'methods', None)
        print(f"{methods or 'WS'} {route.path}")
