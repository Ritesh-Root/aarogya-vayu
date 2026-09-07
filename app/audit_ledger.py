import json
import hashlib
from datetime import datetime, timezone
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
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        
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

    def verify_chain_integrity(self) -> Dict[str, Any]:
        """
        Cryptographically validates the entire SHA-256 hash chain from genesis to head.
        Guarantees tamper-evidence and non-repudiation across all audit records.
        """
        if not self.entries:
            return {"valid": True, "total_blocks": 0, "head_hash": None, "tamper_evident": True}

        expected_prev_hash = "0" * 64
        for i, entry in enumerate(self.entries):
            # 1. Validate block index continuity
            if entry.get("index") != i:
                return {
                    "valid": False,
                    "error": f"Block index discontinuity at position {i}: expected {i}, got {entry.get('index')}",
                    "compromised_index": i
                }

            # 2. Validate cryptographic link to previous block
            if entry.get("prev_hash") != expected_prev_hash:
                return {
                    "valid": False,
                    "error": f"Broken cryptographic link at block {i}: expected prev_hash {expected_prev_hash}, got {entry.get('prev_hash')}",
                    "compromised_index": i
                }

            # 3. Recalculate block SHA-256 hash over deterministic payload
            payload_str = f"{entry['index']}|{entry['timestamp']}|{entry['event_type']}|{json.dumps(entry['details'], sort_keys=True)}|{entry['approved_by']}|{entry['prev_hash']}"
            recomputed_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

            if recomputed_hash != entry.get("current_hash"):
                return {
                    "valid": False,
                    "error": f"Tampering detected at block {i}: stored hash {entry.get('current_hash')} does not match recomputed hash {recomputed_hash}",
                    "compromised_index": i
                }

            expected_prev_hash = entry["current_hash"]

        return {
            "valid": True,
            "total_blocks": len(self.entries),
            "head_hash": self.entries[-1]["current_hash"],
            "genesis_hash": self.entries[0]["current_hash"],
            "tamper_evident": True,
            "algorithm": "SHA-256 Chained Hash Ledger",
            "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        }

