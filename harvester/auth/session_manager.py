import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from harvester.config import settings
from harvester.models import SessionInfo

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages session persistence and cookies for authenticated sources (e.g. TOI+, The Hindu, etc.)
    """
    def __init__(self, sessions_dir: Optional[Path] = None):
        self.sessions_dir = sessions_dir or settings.sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _get_session_path(self, source_id: str) -> Path:
        return self.sessions_dir / f"{source_id}.json"

    def save_cookies(self, source_id: str, cookies: List[Dict[str, Any]]) -> Path:
        """
        Saves cookie dicts into a persistent JSON session file.
        """
        file_path = self._get_session_path(source_id)
        data = {
            "source_id": source_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "cookies": cookies
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved {len(cookies)} cookies for source '{source_id}' to {file_path}")
        return file_path

    def load_cookies(self, source_id: str) -> List[Dict[str, Any]]:
        """
        Loads cookies list from disk if available.
        """
        file_path = self._get_session_path(source_id)
        if not file_path.exists():
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("cookies", [])
        except Exception as e:
            logger.error(f"Failed to load cookies for {source_id}: {e}")
            return []

    def get_cookie_dict(self, source_id: str) -> Dict[str, str]:
        """
        Returns cookies in a simple name-value dictionary suitable for requests/aiohttp.
        """
        cookies = self.load_cookies(source_id)
        return {c.get("name"): c.get("value") for c in cookies if c.get("name") and c.get("value")}

    def import_cookies_raw(self, source_id: str, raw_text: str) -> int:
        """
        Imports cookies from either JSON string or Netscape cookie format.
        """
        cookies = []
        raw_text = raw_text.strip()
        
        # Try JSON parsing
        if raw_text.startswith("[") or raw_text.startswith("{"):
            try:
                parsed = json.loads(raw_text)
                if isinstance(parsed, list):
                    cookies = parsed
                elif isinstance(parsed, dict) and "cookies" in parsed:
                    cookies = parsed["cookies"]
            except json.JSONDecodeError:
                pass
        
        # Try Netscape format
        if not cookies:
            lines = raw_text.splitlines()
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    cookies.append({
                        "domain": parts[0],
                        "httpOnly": parts[1].upper() == "TRUE",
                        "path": parts[2],
                        "secure": parts[3].upper() == "TRUE",
                        "expires": int(parts[4]) if parts[4].isdigit() else -1,
                        "name": parts[5],
                        "value": parts[6],
                    })

        if cookies:
            self.save_cookies(source_id, cookies)
            return len(cookies)
        return 0

    def get_session_info(self, source_id: str, source_name: str) -> SessionInfo:
        """
        Retrieves status of session file and validity for dashboard UI.
        """
        cookies = self.load_cookies(source_id)
        file_path = self._get_session_path(source_id)
        
        if not file_path.exists() or not cookies:
            return SessionInfo(
                source_id=source_id,
                source_name=source_name,
                has_session=False,
                cookie_count=0,
                is_valid=False
            )
            
        # Check expiry
        now_ts = datetime.now().timestamp()
        valid = True
        min_expiry: Optional[datetime] = None
        
        for c in cookies:
            exp = c.get("expires") or c.get("expiry")
            if exp and isinstance(exp, (int, float)) and exp > 0:
                dt = datetime.fromtimestamp(exp)
                if min_expiry is None or dt < min_expiry:
                    min_expiry = dt
                if exp < now_ts:
                    valid = False
                    
        return SessionInfo(
            source_id=source_id,
            source_name=source_name,
            has_session=True,
            cookie_count=len(cookies),
            expires_at=min_expiry,
            is_valid=valid,
            last_updated=datetime.fromtimestamp(file_path.stat().st_mtime)
        )


session_manager = SessionManager()
