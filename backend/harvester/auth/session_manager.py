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

    def save_cookies(self, source_id: str, cookies: List[Dict[str, Any]]) -> Path:
        """
        Saves normalized cookie dicts into a persistent JSON session file.
        """
        file_path = self._get_session_path(source_id)
        # Deduplicate and normalize cookies
        normalized_map = {}
        for c in cookies:
            name = c.get("name")
            if not name:
                continue
            key = (c.get("domain"), name, c.get("path", "/"))
            exp = c.get("expirationDate") or c.get("expires") or c.get("expiry")
            if exp and isinstance(exp, (int, float)) and exp > 0:
                c["expirationDate"] = exp
                c["expires"] = exp
                c["expiry"] = exp
            normalized_map[key] = c

        cleaned_cookies = list(normalized_map.values())
        data = {
            "source_id": source_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "cookies": cleaned_cookies
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved {len(cleaned_cookies)} cookies for source '{source_id}' to {file_path}")
        return file_path

    def import_cookies_raw(self, source_id: str, raw_text: str) -> int:
        """
        Imports cookies from either JSON string (including concatenated arrays) or Netscape cookie format.
        """
        cookies = []
        raw_text = raw_text.strip()
        
        # Try JSON parsing (handles single or multiple concatenated JSON arrays/objects)
        if raw_text.startswith("[") or raw_text.startswith("{"):
            decoder = json.JSONDecoder()
            idx = 0
            while idx < len(raw_text):
                while idx < len(raw_text) and raw_text[idx].isspace():
                    idx += 1
                if idx >= len(raw_text):
                    break
                try:
                    obj, end_idx = decoder.raw_decode(raw_text, idx)
                    if isinstance(obj, list):
                        cookies.extend(obj)
                    elif isinstance(obj, dict):
                        if "cookies" in obj and isinstance(obj["cookies"], list):
                            cookies.extend(obj["cookies"])
                        else:
                            cookies.append(obj)
                    idx = end_idx
                except json.JSONDecodeError:
                    break
        
        # Try Netscape format
        if not cookies:
            lines = raw_text.splitlines()
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    exp_val = int(parts[4]) if parts[4].isdigit() else -1
                    cookies.append({
                        "domain": parts[0],
                        "httpOnly": parts[1].upper() == "TRUE",
                        "path": parts[2],
                        "secure": parts[3].upper() == "TRUE",
                        "expires": exp_val,
                        "expirationDate": exp_val,
                        "expiry": exp_val,
                        "name": parts[5],
                        "value": parts[6],
                    })

        if cookies:
            self.save_cookies(source_id, cookies)
            # If source has multi-edition sessions, synchronize them
            if source_id == "loksatta":
                for ed in ["mumbai", "pune", "nagpur", "nashik", "nasik", "ahilyanagar", "sambhajinagar"]:
                    self.save_cookies(f"loksatta_{ed}", cookies)
            elif source_id == "financial_express":
                for ed in ["delhi", "mumbai", "bengaluru", "chennai", "kolkata", "lucknow", "hyderabad", "ahmedabad", "pune", "chandigarh", "kochi"]:
                    self.save_cookies(f"financial_express_{ed}", cookies)
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
            
        now_ts = datetime.now().timestamp()
        
        # Transient analytics / tracking cookies that shouldn't invalidate user auth sessions
        ephemeral_prefixes = ("_gat", "_dc_gtm", "_chartbeat", "sessiontraffic", "_cb", "_gid")
        
        future_expiries: List[datetime] = []
        all_expiries: List[float] = []
        has_future_auth = False
        
        auth_keywords = ("token", "jwt", "auth", "sso", "user", "session", "rwmy", "upssid", "fpid", "fpuuid")

        for c in cookies:
            name = (c.get("name") or "").lower()
            exp = c.get("expires") or c.get("expiry") or c.get("expirationDate")
            
            # Skip ephemeral tracking pixels from expiry decision
            if any(name.startswith(p) for p in ephemeral_prefixes):
                continue
                
            if exp and isinstance(exp, (int, float)) and exp > 0:
                all_expiries.append(exp)
                dt = datetime.fromtimestamp(exp)
                if exp > now_ts:
                    future_expiries.append(dt)
                    if any(k in name for k in auth_keywords):
                        has_future_auth = True

        # Valid if has future-expiring cookies or if session-only cookies (no explicit exp)
        if future_expiries:
            valid = True
            min_expiry = min(future_expiries)
        elif not all_expiries:
            # Session-based cookies without absolute timestamps
            valid = True
            min_expiry = None
        else:
            # All non-ephemeral timestamped cookies are in the past
            valid = False
            min_expiry = datetime.fromtimestamp(max(all_expiries))
                    
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
