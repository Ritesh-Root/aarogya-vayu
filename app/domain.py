import math
import uuid
import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from fastapi import HTTPException

from app.models import (
    StockActionRequest, StockActionResult,
    TransferConsignment, DispatchConsignmentRequest,
    ReceiveConsignmentRequest, CancelConsignmentRequest,
    DailyActionItem, ApprovalRequest, TransferRecommendation
)
from app.storage import StorageManager, StorageError
from app.audit_ledger import AuditLedger

def _compute_hash(data: Any) -> str:
    """Computes SHA-256 hash over deterministic JSON string."""
    encoded = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

class InventoryDomainService:
    def __init__(self, storage: StorageManager, audit_ledger: AuditLedger, facilities: Dict[str, dict], medicines: Dict[str, dict]):
        self.storage = storage
        self.audit_ledger = audit_ledger
        self.facilities = facilities
        self.medicines = medicines

    def _check_idempotency(self, idempotency_key: Optional[str], payload: Dict[str, Any], idempotency_cache: Dict[str, dict]) -> Optional[Dict[str, Any]]:
        """
        Enforces true idempotency:
        - Same key & same payload hash -> returns cached response.
        - Same key & different payload hash -> raises HTTP 409 Conflict.
        """
        if not idempotency_key:
            return None

        req_hash = _compute_hash(payload)
        if idempotency_key in idempotency_cache:
            entry = idempotency_cache[idempotency_key]
            if entry.get("payload_hash") == req_hash:
                return entry.get("response")
            else:
                raise HTTPException(
                    status_code=409,
                    detail=f"Idempotency conflict: Key '{idempotency_key}' was previously executed with different parameters."
                )
        return None

    def _record_idempotency(self, idempotency_key: Optional[str], payload: Dict[str, Any], response: Dict[str, Any], idempotency_cache: Dict[str, dict]):
        if idempotency_key:
            idempotency_cache[idempotency_key] = {
                "payload_hash": _compute_hash(payload),
                "response": response,
                "created_at": datetime.now(timezone.utc).isoformat() + "Z"
            }

    def _find_item(self, inventory: List[dict], facility_id: str, medicine_id: str, batch_number: Optional[str] = None) -> Optional[dict]:
        for item in inventory:
            if item["facility_id"] == facility_id and item["medicine_id"] == medicine_id:
                if batch_number is None or item.get("batch_number") == batch_number:
                    return item
        return None

    def get_facility_inventory(self, facility_id: str) -> List[dict]:
        inventory, consignments, _, _ = self.storage.load_all()
        fac_items = [i for i in inventory if i["facility_id"] == facility_id]
        
        # Add derived in_transit count from active dispatched consignments heading to this facility
        in_transit_map: Dict[str, int] = {}
        for c in consignments.values():
            if c.get("recipient_facility_id") == facility_id and c.get("status") == "DISPATCHED":
                m_id = c.get("medicine_id")
                in_transit_map[m_id] = in_transit_map.get(m_id, 0) + c.get("units_dispatched", 0)

        for item in fac_items:
            m_id = item["medicine_id"]
            item["in_transit"] = in_transit_map.get(m_id, 0)
            item["available"] = max(0, item.get("on_hand", 0) - item.get("reserved", 0) - item.get("quarantined", 0))
            item["current_stock"] = item.get("on_hand", 0)
        return fac_items

    def execute_stock_action(self, req: StockActionRequest) -> StockActionResult:
        inventory, consignments, idempotency_cache, _ = self.storage.load_all()

        cached = self._check_idempotency(req.idempotency_key, req.model_dump(), idempotency_cache)
        if cached:
            return StockActionResult(**cached)

        item = self._find_item(inventory, req.facility_id, req.medicine_id, req.batch_number)
        if not item:
            # Fallback search without batch if single batch exists
            item = self._find_item(inventory, req.facility_id, req.medicine_id)
            if not item:
                raise HTTPException(status_code=404, detail=f"Stock item not found for {req.facility_id} / {req.medicine_id}")

        # Optimistic locking check
        if req.expected_version is not None and item.get("version", 1) != req.expected_version:
            raise HTTPException(
                status_code=409,
                detail=f"Stale inventory update: Expected version {req.expected_version}, but current version is {item.get('version', 1)}. Refresh and retry."
            )

        prev_on_hand = item.get("on_hand", item.get("current_stock", 0))
        prev_reserved = item.get("reserved", 0)
        prev_quarantined = item.get("quarantined", 0)
        reconciliation_exception = False
        audit_event_type = "STOCK_ACTION_EXECUTED"

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if req.action_type == "PHYSICAL_COUNT":
            counted_units = req.quantity
            if counted_units < 0:
                raise HTTPException(status_code=400, detail="Counted units cannot be negative.")

            # Check if count is below existing commitments
            if counted_units < (prev_reserved + prev_quarantined):
                reconciliation_exception = True
                audit_event_type = "STOCK_RECONCILIATION_EXCEPTION"
                # Freeze dispatches for this batch to prevent ghost transfers
                item["is_frozen"] = True
                item["on_hand"] = counted_units
                # Proportionally assign remaining to quarantine and reserved
                if counted_units < prev_quarantined:
                    item["quarantined"] = counted_units
                    item["reserved"] = 0
                else:
                    item["quarantined"] = prev_quarantined
                    item["reserved"] = counted_units - prev_quarantined
                item["available"] = 0
                msg = (
                    f"CRITICAL RECONCILIATION EXCEPTION: Physical count ({counted_units}) is below active commitments "
                    f"(reserved={prev_reserved}, quarantined={prev_quarantined}). Batch is frozen pending MOIC investigation."
                )
            else:
                item["on_hand"] = counted_units
                item["is_frozen"] = False
                item["available"] = max(0, item["on_hand"] - item["reserved"] - item["quarantined"])
                msg = f"Physical stock count verified at {counted_units} units."

            item["last_verified_at"] = now_str
            item["verified_by"] = req.operator_name

        elif req.action_type == "STOCK_RECEIVED":
            if req.quantity <= 0:
                raise HTTPException(status_code=400, detail="Received quantity must be positive.")
            item["on_hand"] += req.quantity
            item["available"] = max(0, item["on_hand"] - item["reserved"] - item["quarantined"])
            msg = f"Received and stocked {req.quantity} units."

        elif req.action_type == "STOCK_ISSUED":
            if req.quantity <= 0:
                raise HTTPException(status_code=400, detail="Issued quantity must be positive.")
            current_avail = max(0, item["on_hand"] - item["reserved"] - item["quarantined"])
            if req.quantity > current_avail:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot issue {req.quantity} units: Only {current_avail} available (On Hand: {item['on_hand']}, Reserved: {item['reserved']}, Quarantined: {item['quarantined']})."
                )
            item["on_hand"] -= req.quantity
            item["available"] = max(0, item["on_hand"] - item["reserved"] - item["quarantined"])
            msg = f"Dispensed/issued {req.quantity} units for OPD/IPD."

        elif req.action_type == "QUARANTINE_DAMAGED":
            if req.quantity <= 0:
                raise HTTPException(status_code=400, detail="Quarantine quantity must be positive.")
            current_avail = max(0, item["on_hand"] - item["reserved"] - item["quarantined"])
            if req.quantity > current_avail:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot quarantine {req.quantity} units: Exceeds available stock of {current_avail}."
                )
            item["quarantined"] += req.quantity
            item["available"] = max(0, item["on_hand"] - item["reserved"] - item["quarantined"])
            msg = f"Segregated {req.quantity} units into quarantine (damaged/expired/held)."

        else:
            raise HTTPException(status_code=400, detail=f"Unknown stock action: {req.action_type}")

        # Invariant checks
        assert item["reserved"] + item["quarantined"] <= item["on_hand"], "Invariant violation: reserved + quarantined > on_hand"
        item["current_stock"] = item["on_hand"]
        item["version"] = item.get("version", 1) + 1
        item["last_updated"] = now_str

        # Mint audit entry
        audit_entry = self.audit_ledger.record_entry(
            event_type=audit_event_type,
            details={
                "action_type": req.action_type,
                "facility_id": req.facility_id,
                "medicine_id": req.medicine_id,
                "batch_number": item.get("batch_number"),
                "previous_on_hand": prev_on_hand,
                "new_on_hand": item["on_hand"],
                "reserved": item["reserved"],
                "quarantined": item["quarantined"],
                "available": item["available"],
                "reason": req.reason,
                "reconciliation_exception": reconciliation_exception,
                "operator_role": req.operator_role,
                "idempotency_key": req.idempotency_key
            },
            approved_by=f"{req.operator_name} ({req.operator_role})"
        )

        result = StockActionResult(
            success=True,
            action_type=req.action_type,
            facility_id=req.facility_id,
            medicine_id=req.medicine_id,
            batch_number=item.get("batch_number", "DEFAULT"),
            previous_on_hand=prev_on_hand,
            new_on_hand=item["on_hand"],
            new_reserved=item["reserved"],
            new_quarantined=item["quarantined"],
            new_available=item["available"],
            version=item["version"],
            reconciliation_exception=reconciliation_exception,
            message=msg,
            audit_hash=audit_entry.get("current_hash"),
            timestamp=audit_entry["timestamp"]
        )

        self._record_idempotency(req.idempotency_key, req.model_dump(), result.model_dump(), idempotency_cache)
        self.storage.commit_transaction(inventory, consignments, idempotency_cache, audit_entry)
        return result

    def approve_transfer_to_consignment(self, req: ApprovalRequest, rec: TransferRecommendation) -> TransferConsignment:
        inventory, consignments, idempotency_cache, _ = self.storage.load_all()

        cached = self._check_idempotency(req.idempotency_key, req.model_dump(), idempotency_cache)
        if cached:
            return TransferConsignment(**cached)

        # Idempotent re-approval check: return existing consignment if already approved
        existing_c = next((c for c in consignments.values() if c.get("recommendation_id") == rec.id and c.get("status") in ["APPROVED_RESERVED", "DISPATCHED", "RECEIVED"]), None)
        if existing_c:
            return TransferConsignment(**existing_c)

        # Locate specific donor item
        donor_item = self._find_item(inventory, rec.donor_facility_id, rec.medicine_id, rec.batch_number)
        if not donor_item:
            donor_item = self._find_item(inventory, rec.donor_facility_id, rec.medicine_id)
        if not donor_item:
            raise HTTPException(status_code=404, detail=f"Donor inventory record not found for {rec.donor_facility_id}")

        if donor_item.get("is_frozen", False):
            raise HTTPException(
                status_code=409,
                detail=f"Donor batch {donor_item.get('batch_number')} is FROZEN due to an active reconciliation exception. Dispatch disallowed."
            )

        donor_avail = max(0, donor_item["on_hand"] - donor_item.get("reserved", 0) - donor_item.get("quarantined", 0))
        if donor_avail < rec.units_to_transfer:
            raise HTTPException(
                status_code=409,
                detail=f"Stock conservation conflict: Donor has {donor_avail} available, cannot reserve {rec.units_to_transfer} units."
            )

        # Upward ceiling reserve check
        min_reserve = rec.donor_min_reserve_units
        if min_reserve <= 0:
            min_reserve = math.ceil(donor_item.get("daily_consumption_base", 5.0) * 14.0)

        if (donor_avail - rec.units_to_transfer) < min_reserve:
            raise HTTPException(
                status_code=409,
                detail=f"Clinical safety violation: Reserving {rec.units_to_transfer} units leaves donor with {donor_avail - rec.units_to_transfer}, below strict safety ceiling of {min_reserve} units."
            )

        # Enforce packaging formula
        pack_size = donor_item.get("pack_size", 10) or 10
        transfer_units = pack_size * (max(0, rec.units_to_transfer) // pack_size)
        if transfer_units <= 0:
            raise HTTPException(status_code=400, detail="Transfer quantity must be at least one full packaging multiple.")

        # APPLY RESERVATION: Donor on_hand stays UNCHANGED, reserved += Q. Recipient stays UNCHANGED.
        donor_item["reserved"] = donor_item.get("reserved", 0) + transfer_units
        donor_item["available"] = max(0, donor_item["on_hand"] - donor_item["reserved"] - donor_item.get("quarantined", 0))
        donor_item["current_stock"] = donor_item["on_hand"]
        donor_item["version"] = donor_item.get("version", 1) + 1
        donor_item["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        consignment_id = f"CONSIGN-{uuid.uuid4().hex[:8].upper()}"
        challan_id = f"CHALLAN-UP-{datetime.now().strftime('%Y%m%d')}-{consignment_id[-6:]}"
        now_iso = datetime.now(timezone.utc).isoformat() + "Z"

        audit_entry = self.audit_ledger.record_entry(
            event_type="STOCK_TRANSFER_RESERVED",
            details={
                "consignment_id": consignment_id,
                "challan_id": challan_id,
                "donor_facility_id": rec.donor_facility_id,
                "donor_facility_name": rec.donor_facility_name,
                "recipient_facility_id": rec.recipient_facility_id,
                "recipient_facility_name": rec.recipient_facility_name,
                "medicine_id": rec.medicine_id,
                "medicine_name": rec.medicine_name,
                "units_reserved": transfer_units,
                "batch_number": donor_item.get("batch_number", "BAT-DEF"),
                "donor_remaining_available": donor_item["available"],
                "officer_comments": req.comments,
                "idempotency_key": req.idempotency_key
            },
            approved_by=req.officer_name
        )

        consignment = TransferConsignment(
            id=consignment_id,
            recommendation_id=rec.id,
            challan_id=challan_id,
            donor_facility_id=rec.donor_facility_id,
            donor_facility_name=rec.donor_facility_name,
            recipient_facility_id=rec.recipient_facility_id,
            recipient_facility_name=rec.recipient_facility_name,
            medicine_id=rec.medicine_id,
            medicine_name=rec.medicine_name,
            batch_number=donor_item.get("batch_number", "BAT-DEF"),
            expiry_date=donor_item.get("expiry_date", "2027-12-31"),
            days_to_expiry=donor_item.get("days_to_expiry", 365),
            pack_size=pack_size,
            distance_km=rec.distance_km,
            units_requested=transfer_units,
            units_dispatched=0,
            status="APPROVED_RESERVED",
            authorized_by=req.officer_name,
            approved_at=now_iso,
            idempotency_key=req.idempotency_key,
            cryptographic_hash=audit_entry.get("current_hash")
        )

        consignments[consignment_id] = consignment.model_dump()
        rec.status = "APPROVED"
        rec.challan_id = challan_id

        self._record_idempotency(req.idempotency_key, req.model_dump(), consignment.model_dump(), idempotency_cache)
        self.storage.commit_transaction(inventory, consignments, idempotency_cache, audit_entry)
        return consignment

    def cancel_consignment(self, req: CancelConsignmentRequest) -> TransferConsignment:
        inventory, consignments, idempotency_cache, _ = self.storage.load_all()

        cached = self._check_idempotency(req.idempotency_key, req.model_dump(), idempotency_cache)
        if cached:
            return TransferConsignment(**cached)

        c_data = consignments.get(req.consignment_id)
        if not c_data:
            raise HTTPException(status_code=404, detail="Consignment not found.")

        if c_data.get("status") != "APPROVED_RESERVED":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot cancel consignment in status '{c_data.get('status')}'. Only 'APPROVED_RESERVED' consignments can be cancelled."
            )

        # Release reservation at donor
        donor_item = self._find_item(inventory, c_data["donor_facility_id"], c_data["medicine_id"], c_data["batch_number"])
        if donor_item:
            units = c_data["units_requested"]
            donor_item["reserved"] = max(0, donor_item.get("reserved", 0) - units)
            donor_item["available"] = max(0, donor_item["on_hand"] - donor_item["reserved"] - donor_item.get("quarantined", 0))
            donor_item["current_stock"] = donor_item["on_hand"]
            donor_item["version"] = donor_item.get("version", 1) + 1
            donor_item["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        c_data["status"] = "CANCELLED"
        c_data["condition_notes"] = f"Cancelled by {req.operator_name}: {req.reason}"

        audit_entry = self.audit_ledger.record_entry(
            event_type="STOCK_TRANSFER_CANCELLED",
            details={
                "consignment_id": req.consignment_id,
                "reason": req.reason,
                "units_released": c_data["units_requested"],
                "donor_facility_id": c_data["donor_facility_id"]
            },
            approved_by=f"{req.operator_name} ({req.operator_role})"
        )

        c_data["cryptographic_hash"] = audit_entry.get("current_hash")
        consignment = TransferConsignment(**c_data)

        self._record_idempotency(req.idempotency_key, req.model_dump(), consignment.model_dump(), idempotency_cache)
        self.storage.commit_transaction(inventory, consignments, idempotency_cache, audit_entry)
        return consignment

    def dispatch_consignment(self, req: DispatchConsignmentRequest) -> TransferConsignment:
        inventory, consignments, idempotency_cache, _ = self.storage.load_all()

        cached = self._check_idempotency(req.idempotency_key, req.model_dump(), idempotency_cache)
        if cached:
            return TransferConsignment(**cached)

        c_data = consignments.get(req.consignment_id)
        if not c_data:
            raise HTTPException(status_code=404, detail="Consignment not found.")

        # Idempotent re-dispatch check
        if c_data.get("status") == "DISPATCHED":
            return TransferConsignment(**c_data)

        if c_data.get("status") != "APPROVED_RESERVED":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot dispatch consignment with status '{c_data.get('status')}'. Must be 'APPROVED_RESERVED'."
            )

        # Locate donor item
        donor_item = self._find_item(inventory, c_data["donor_facility_id"], c_data["medicine_id"], c_data["batch_number"])
        if not donor_item:
            raise HTTPException(status_code=404, detail="Donor inventory batch record not found.")

        if donor_item.get("is_frozen", False):
            raise HTTPException(
                status_code=409,
                detail=f"Batch {donor_item.get('batch_number')} is currently frozen due to an unresolved reconciliation exception. Dispatch blocked."
            )

        units = c_data["units_requested"]
        if donor_item["on_hand"] < units or donor_item.get("reserved", 0) < units:
            raise HTTPException(
                status_code=409,
                detail=f"Physical stock discrepancy: Donor has {donor_item['on_hand']} on hand ({donor_item.get('reserved', 0)} reserved), cannot dispatch {units}."
            )

        # DISPATCH EXECUTION: Donor physical stock drops, reservation clears.
        # Recipient stock is NOT credited (it enters in_transit).
        donor_item["on_hand"] -= units
        donor_item["reserved"] -= units
        donor_item["available"] = max(0, donor_item["on_hand"] - donor_item["reserved"] - donor_item.get("quarantined", 0))
        donor_item["current_stock"] = donor_item["on_hand"]
        donor_item["version"] = donor_item.get("version", 1) + 1
        donor_item["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        now_iso = datetime.now(timezone.utc).isoformat() + "Z"
        c_data["status"] = "DISPATCHED"
        c_data["units_dispatched"] = units
        c_data["dispatched_by"] = req.operator_name
        c_data["dispatched_at"] = now_iso
        c_data["vehicle_number"] = req.vehicle_number
        c_data["condition_notes"] = req.courier_notes

        audit_entry = self.audit_ledger.record_entry(
            event_type="STOCK_TRANSFER_DISPATCHED",
            details={
                "consignment_id": req.consignment_id,
                "challan_id": c_data["challan_id"],
                "units_dispatched": units,
                "donor_remaining_on_hand": donor_item["on_hand"],
                "vehicle_number": req.vehicle_number,
                "courier_notes": req.courier_notes
            },
            approved_by=f"{req.operator_name} ({req.operator_role})"
        )

        c_data["cryptographic_hash"] = audit_entry.get("current_hash")
        consignment = TransferConsignment(**c_data)

        self._record_idempotency(req.idempotency_key, req.model_dump(), consignment.model_dump(), idempotency_cache)
        self.storage.commit_transaction(inventory, consignments, idempotency_cache, audit_entry)
        return consignment

    def receive_consignment(self, req: ReceiveConsignmentRequest) -> TransferConsignment:
        inventory, consignments, idempotency_cache, _ = self.storage.load_all()

        cached = self._check_idempotency(req.idempotency_key, req.model_dump(), idempotency_cache)
        if cached:
            return TransferConsignment(**cached)

        c_data = consignments.get(req.consignment_id)
        if not c_data:
            raise HTTPException(status_code=404, detail="Consignment not found.")

        # Idempotent re-receipt check
        if c_data.get("status") == "RECEIVED":
            return TransferConsignment(**c_data)

        if c_data.get("status") != "DISPATCHED":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot receive consignment with status '{c_data.get('status')}'. Must be 'DISPATCHED'."
            )

        dispatched = c_data.get("units_dispatched", 0)
        accepted = req.accepted_units
        quarantined = req.quarantined_units
        missing = req.missing_units

        # Enforce strict single final receipt equality: Q_dispatched = Q_accepted + Q_quarantined + Q_missing
        if (accepted + quarantined + missing) != dispatched:
            raise HTTPException(
                status_code=400,
                detail=f"Receipt breakdown invariant violated: accepted ({accepted}) + quarantined ({quarantined}) + missing ({missing}) = {accepted + quarantined + missing}, which does not match dispatched units ({dispatched})."
            )

        # Locate or initialize recipient item for this batch
        rec_item = self._find_item(inventory, c_data["recipient_facility_id"], c_data["medicine_id"], c_data["batch_number"])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not rec_item:
            # Create batch record preserving transferred batch and expiry
            rec_fac = self.facilities.get(c_data["recipient_facility_id"], {})
            rec_item = {
                "facility_id": c_data["recipient_facility_id"],
                "facility_name": rec_fac.get("name", c_data["recipient_facility_name"]),
                "medicine_id": c_data["medicine_id"],
                "medicine_name": c_data["medicine_name"],
                "batch_number": c_data["batch_number"],
                "expiry_date": c_data.get("expiry_date", "2027-12-31"),
                "days_to_expiry": c_data.get("days_to_expiry", 365),
                "daily_consumption_base": 15.0,
                "on_hand": 0,
                "reserved": 0,
                "quarantined": 0,
                "available": 0,
                "current_stock": 0,
                "pack_size": c_data.get("pack_size", 10),
                "unit": "units",
                "version": 1,
                "is_frozen": False,
                "last_updated": now_str,
                "last_verified_at": now_str,
                "verified_by": req.operator_name
            }
            inventory.append(rec_item)

        # RECEIPT INVENTORY EXECUTION:
        # Physical on_hand increases by accepted + quarantined (quarantined units are physically present on site)
        # Quarantined increases by quarantined
        # Newly available is strictly accepted
        rec_item["on_hand"] += (accepted + quarantined)
        rec_item["quarantined"] += quarantined
        rec_item["available"] = max(0, rec_item["on_hand"] - rec_item.get("reserved", 0) - rec_item["quarantined"])
        rec_item["current_stock"] = rec_item["on_hand"]
        rec_item["version"] = rec_item.get("version", 1) + 1
        rec_item["last_updated"] = now_str
        rec_item["last_verified_at"] = now_str
        rec_item["verified_by"] = req.operator_name

        now_iso = datetime.now(timezone.utc).isoformat() + "Z"
        c_data["status"] = "RECEIVED"
        c_data["units_accepted"] = accepted
        c_data["units_quarantined"] = quarantined
        c_data["units_missing"] = missing
        c_data["received_by"] = req.operator_name
        c_data["received_at"] = now_iso
        c_data["condition_notes"] = req.discrepancy_notes

        audit_entry = self.audit_ledger.record_entry(
            event_type="STOCK_TRANSFER_RECEIVED",
            details={
                "consignment_id": req.consignment_id,
                "challan_id": c_data["challan_id"],
                "recipient_facility_id": c_data["recipient_facility_id"],
                "units_accepted": accepted,
                "units_quarantined": quarantined,
                "units_missing": missing,
                "discrepancy_recorded": missing > 0,
                "discrepancy_notes": req.discrepancy_notes,
                "recipient_new_on_hand": rec_item["on_hand"],
                "recipient_new_available": rec_item["available"]
            },
            approved_by=f"{req.operator_name} ({req.operator_role})"
        )

        c_data["cryptographic_hash"] = audit_entry.get("current_hash")
        consignment = TransferConsignment(**c_data)

        self._record_idempotency(req.idempotency_key, req.model_dump(), consignment.model_dump(), idempotency_cache)
        self.storage.commit_transaction(inventory, consignments, idempotency_cache, audit_entry)
        return consignment

    def get_facility_action_items(self, facility_id: str) -> List[DailyActionItem]:
        inventory, consignments, _, _ = self.storage.load_all()
        actions: List[DailyActionItem] = []

        # 1. Impending Stockouts (Coverage < 4.0 days)
        for item in inventory:
            if item["facility_id"] == facility_id:
                avail = max(0, item.get("on_hand", 0) - item.get("reserved", 0) - item.get("quarantined", 0))
                rate = item.get("daily_consumption_base", 10.0)
                days_cover = round(avail / max(0.1, rate), 1)
                if days_cover < 4.0:
                    actions.append(DailyActionItem(
                        id=f"ACT-STOCKOUT-{item['medicine_id']}",
                        urgency="CRITICAL",
                        action_type="IMPENDING_STOCKOUT",
                        title=f"Critical Stockout: {item['medicine_name']}",
                        description=f"Only {avail} units available ({days_cover} days cover remaining). Immediate replenishment or transfer required.",
                        target_medicine_id=item["medicine_id"],
                        target_batch=item.get("batch_number"),
                        cta_label="Request Stock Transfer"
                    ))

        # 2. Inbound Consignments awaiting inspection and receipt
        for c_id, c in consignments.items():
            if c.get("recipient_facility_id") == facility_id and c.get("status") == "DISPATCHED":
                actions.append(DailyActionItem(
                    id=f"ACT-INBOUND-{c_id}",
                    urgency="HIGH",
                    action_type="INBOUND_TRANSFER_PENDING",
                    title=f"Incoming Consignment: {c.get('units_dispatched')} units of {c.get('medicine_name')}",
                    description=f"Dispatched from {c.get('donor_facility_name')} via Challan {c.get('challan_id')}. Awaiting physical count and receipt.",
                    target_consignment_id=c_id,
                    target_medicine_id=c.get("medicine_id"),
                    cta_label="Inspect & Confirm Receipt"
                ))

        # 3. Outbound Consignments awaiting dispatch
        for c_id, c in consignments.items():
            if c.get("donor_facility_id") == facility_id and c.get("status") == "APPROVED_RESERVED":
                actions.append(DailyActionItem(
                    id=f"ACT-OUTBOUND-{c_id}",
                    urgency="HIGH",
                    action_type="OUTBOUND_DISPATCH_PENDING",
                    title=f"Approved Transfer: {c.get('units_requested')} units of {c.get('medicine_name')}",
                    description=f"Destination: {c.get('recipient_facility_name')}. Stock is reserved. Hand over to courier and confirm dispatch.",
                    target_consignment_id=c_id,
                    target_medicine_id=c.get("medicine_id"),
                    cta_label="Handover & Confirm Dispatch"
                ))

        # 4. Reconciliation Exceptions (Frozen batches)
        for item in inventory:
            if item["facility_id"] == facility_id and item.get("is_frozen", False):
                actions.append(DailyActionItem(
                    id=f"ACT-RECON-{item['medicine_id']}-{item.get('batch_number')}",
                    urgency="CRITICAL",
                    action_type="RECONCILIATION_REQUIRED",
                    title=f"Batch Frozen: {item['medicine_name']} ({item.get('batch_number')})",
                    description="Physical count was below existing commitments. Dispatches are blocked pending MOIC investigation.",
                    target_medicine_id=item["medicine_id"],
                    target_batch=item.get("batch_number"),
                    cta_label="Resolve Reconciliation"
                ))

        # 5. Near-Expiry Batches (< 60 days)
        for item in inventory:
            if item["facility_id"] == facility_id:
                days_exp = item.get("days_to_expiry", 999)
                if days_exp <= 60 and item.get("on_hand", 0) > 0:
                    actions.append(DailyActionItem(
                        id=f"ACT-EXPIRY-{item['medicine_id']}-{item.get('batch_number')}",
                        urgency="MEDIUM",
                        action_type="EXPIRY_WARNING",
                        title=f"Expiry Warning: Batch {item.get('batch_number')}",
                        description=f"Expires in {days_exp} days ({item['expiry_date']}). Prioritize for dispensing or inter-facility transfer.",
                        target_medicine_id=item["medicine_id"],
                        target_batch=item.get("batch_number"),
                        cta_label="Flag for Redistribution"
                    ))

        # Sort: CRITICAL first, then HIGH, then MEDIUM
        urgency_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        actions.sort(key=lambda a: urgency_order.get(a.urgency, 9))
        return actions
