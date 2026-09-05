import json
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

class AuditLedger:
    def __init__(self, ledger_file: Optional[str] = None):
        if ledger_file is None:
            base_dir = Path(__file__).resolve().parent.parent
            ledger_file = str(base_dir / "data" / "audit_log.json")
        self.ledger_file = ledger_file
        self.entries: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        loaded = False
        for path in [self.ledger_file, "/tmp/audit_log.json"]:
            try:
                with open(path, "r") as f:
                    self.entries = json.load(f)
                    loaded = True
                    break
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                continue
        if not loaded:
            self.entries = []
            # Genesis block
            self.record_entry(
                event_type="GENESIS",
                details={"message": "Aarogya-Vāyu Climate-Health Ledger Initialized for Lucknow-Unnao District Cluster"},
                approved_by="SYSTEM_INITIALIZER"
            )

    def _save(self):
        try:
            with open(self.ledger_file, "w") as f:
                json.dump(self.entries, f, indent=2)
        except OSError:
            try:
                with open("/tmp/audit_log.json", "w") as f:
                    json.dump(self.entries, f, indent=2)
            except Exception:
                pass

    def record_entry(self, event_type: str, details: Dict[str, Any], approved_by: str = "SYSTEM") -> Dict[str, Any]:
        prev_hash = self.entries[-1]["current_hash"] if self.entries else "0" * 64
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        payload_str = f"{len(self.entries)}|{timestamp}|{event_type}|{json.dumps(details, sort_keys=True)}|{approved_by}|{prev_hash}"
        current_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

        entry = {
            "index": len(self.entries),
            "timestamp": timestamp,
            "event_type": event_type,
            "approved_by": approved_by,
            "details": details,
            "prev_hash": prev_hash,
            "current_hash": current_hash
        }
        self.entries.append(entry)
        self._save()
        return entry

    def get_recent_entries(self, limit: int = 15) -> List[Dict[str, Any]]:
        return list(reversed(self.entries[-limit:]))
