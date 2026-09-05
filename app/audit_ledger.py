import json
import hashlib
from datetime import datetime
from typing import List, Dict, Any

class AuditLedger:
    def __init__(self, ledger_file: str = "/home/ritesh/aarogya_vayu/data/audit_log.json"):
        self.ledger_file = ledger_file
        self.entries: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        try:
            with open(self.ledger_file, "r") as f:
                self.entries = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.entries = []
            # Genesis block
            self.record_entry(
                event_type="GENESIS",
                details={"message": "Aarogya-Vāyu Climate-Health Ledger Initialized for Lucknow-Unnao District Cluster"},
                approved_by="SYSTEM_INITIALIZER"
            )

    def _save(self):
        with open(self.ledger_file, "w") as f:
            json.dump(self.entries, f, indent=2)

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
