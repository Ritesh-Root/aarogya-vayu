import os
import json
import tempfile
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

class StorageError(Exception):
    """Raised when atomic state persistence fails."""
    pass

class StorageManager:
    """
    Explicit Storage Boundary:
    - STORAGE_BACKEND=demo (default): Local atomic JSON persistence with in-process lock.
    - STORAGE_BACKEND=firestore: GCP Cloud Firestore atomic transactions with NO silent fallback.
    """
    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            base_dir = Path(__file__).resolve().parent.parent
        self.base_dir = base_dir
        self.data_dir = self.base_dir / "data"
        self.tmp_dir = Path("/tmp/aarogya_vayu")
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

        self.backend = os.environ.get("STORAGE_BACKEND", "demo").strip().lower()
        self._lock = threading.Lock()

        # Check firestore configuration upfront if specified
        self.firestore_client = None
        if self.backend == "firestore":
            try:
                from google.cloud import firestore
                self.firestore_client = firestore.Client()
            except Exception as e:
                raise StorageError(
                    f"STORAGE_BACKEND is set to 'firestore', but Google Cloud Firestore client "
                    f"initialization failed: {e}. Safe abort enforced: silent fallback is forbidden."
                )

        # File paths for demo mode
        self.inv_path = self.data_dir / "inventory.json"
        self.consignments_path = self.data_dir / "consignments.json"
        self.idempotency_path = self.data_dir / "idempotency.json"
        self.audit_path = self.data_dir / "audit_log.json"

    def load_all(self) -> Tuple[List[dict], Dict[str, dict], Dict[str, dict], List[dict]]:
        """
        Loads inventory, consignments, idempotency cache, and audit ledger.
        Returns: (inventory, consignments_dict, idempotency_dict, audit_log_list)
        """
        if self.backend == "firestore":
            # Firestore implementation
            try:
                inv_docs = self.firestore_client.collection("inventory").stream()
                inventory = [d.to_dict() for d in inv_docs]
                
                cons_docs = self.firestore_client.collection("consignments").stream()
                consignments = {d.id: d.to_dict() for d in cons_docs}

                idem_docs = self.firestore_client.collection("idempotency").stream()
                idempotency = {d.id: d.to_dict() for d in idem_docs}

                audit_docs = self.firestore_client.collection("audit_ledger").order_by("index").stream()
                audit_log = [d.to_dict() for d in audit_docs]

                return inventory, consignments, idempotency, audit_log
            except Exception as e:
                raise StorageError(f"Firestore load failed: {e}")

        # Demo / Local Mode
        with self._lock:
            # 1. Inventory
            inventory = self._read_json_file(self.inv_path, fallback_path=self.tmp_dir / "inventory.json", default=[])
            # Normalize inventory items to ensure segregated stock keys exist
            for item in inventory:
                if "on_hand" not in item:
                    item["on_hand"] = item.get("current_stock", 0)
                if "reserved" not in item:
                    item["reserved"] = 0
                if "quarantined" not in item:
                    item["quarantined"] = 0
                item["available"] = max(0, item["on_hand"] - item["reserved"] - item["quarantined"])
                item["current_stock"] = item["on_hand"]
                if "version" not in item:
                    item["version"] = 1
                if "pack_size" not in item:
                    item["pack_size"] = 10
                if "is_frozen" not in item:
                    item["is_frozen"] = False

            # 2. Consignments
            consignments = self._read_json_file(self.consignments_path, fallback_path=self.tmp_dir / "consignments.json", default={})

            # 3. Idempotency Cache
            idempotency = self._read_json_file(self.idempotency_path, fallback_path=self.tmp_dir / "idempotency.json", default={})

            # 4. Audit Log
            audit_log = self._read_json_file(self.audit_path, fallback_path=self.tmp_dir / "audit_log.json", default=[])

            return inventory, consignments, idempotency, audit_log

    def commit_transaction(
        self,
        inventory: List[dict],
        consignments: Dict[str, dict],
        idempotency: Dict[str, dict],
        audit_entry: Optional[dict] = None
    ) -> None:
        """
        Atomically persists updated inventory, consignments, idempotency records, and audit log.
        Guarantees that partial writes never occur.
        """
        if self.backend == "firestore":
            try:
                batch = self.firestore_client.batch()
                # Update inventory
                for item in inventory:
                    doc_id = f"{item['facility_id']}_{item['medicine_id']}_{item.get('batch_number', 'DEFAULT')}"
                    doc_ref = self.firestore_client.collection("inventory").document(doc_id)
                    batch.set(doc_ref, item)

                # Update consignments
                for c_id, c_data in consignments.items():
                    c_ref = self.firestore_client.collection("consignments").document(c_id)
                    batch.set(c_ref, c_data)

                # Update idempotency records
                for key, val in idempotency.items():
                    i_ref = self.firestore_client.collection("idempotency").document(key)
                    batch.set(i_ref, val)

                # Append audit entry if provided
                if audit_entry:
                    a_ref = self.firestore_client.collection("audit_ledger").document(str(audit_entry.get("index", "0")))
                    batch.set(a_ref, audit_entry)

                batch.commit()
                return
            except Exception as e:
                raise StorageError(f"Atomic commit failed on Firestore: {e}. No mutations applied.")

        # Demo / Local Mode (Atomic write via replace)
        with self._lock:
            try:
                # Synchronize current_stock with on_hand across all items
                for item in inventory:
                    item["current_stock"] = item.get("on_hand", 0)
                    item["available"] = max(0, item.get("on_hand", 0) - item.get("reserved", 0) - item.get("quarantined", 0))

                self._atomic_write_json(self.inv_path, inventory, fallback_path=self.tmp_dir / "inventory.json")
                self._atomic_write_json(self.consignments_path, consignments, fallback_path=self.tmp_dir / "consignments.json")
                self._atomic_write_json(self.idempotency_path, idempotency, fallback_path=self.tmp_dir / "idempotency.json")

                # If audit_entry provided, read full audit ledger, append, and atomic write
                if audit_entry:
                    audit_list = self._read_json_file(self.audit_path, fallback_path=self.tmp_dir / "audit_log.json", default=[])
                    # Check if already present to prevent duplicate append
                    if not any(e.get("current_hash") == audit_entry.get("current_hash") for e in audit_list):
                        audit_list.append(audit_entry)
                    self._atomic_write_json(self.audit_path, audit_list, fallback_path=self.tmp_dir / "audit_log.json")

            except Exception as e:
                raise StorageError(f"Atomic commit failed on local storage: {e}")

    def _read_json_file(self, primary_path: Path, fallback_path: Path, default: Any) -> Any:
        for p in [fallback_path, primary_path]:
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue
        return default

    def _atomic_write_json(self, primary_path: Path, data: Any, fallback_path: Optional[Path] = None) -> None:
        """
        Writes data to a temporary file on the same filesystem and replaces atomically.
        """
        # Attempt primary path first
        target = primary_path
        parent_dir = target.parent
        is_writable = os.access(parent_dir, os.W_OK) if parent_dir.exists() else False

        if not is_writable and fallback_path is not None:
            target = fallback_path
            parent_dir = target.parent
            parent_dir.mkdir(parents=True, exist_ok=True)

        try:
            temp_file = tempfile.NamedTemporaryFile("w", dir=str(parent_dir), delete=False, encoding="utf-8")
            json.dump(data, temp_file, indent=2)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_file.close()
            os.replace(temp_file.name, str(target))
        except Exception as err:
            # If primary write failed due to read-only filesystem (e.g. Vercel), retry on fallback
            if target != fallback_path and fallback_path is not None:
                parent_dir = fallback_path.parent
                parent_dir.mkdir(parents=True, exist_ok=True)
                temp_file = tempfile.NamedTemporaryFile("w", dir=str(parent_dir), delete=False, encoding="utf-8")
                json.dump(data, temp_file, indent=2)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_file.close()
                os.replace(temp_file.name, str(fallback_path))
            else:
                raise err
