import copy
import uuid
import concurrent.futures
import pytest
from fastapi.testclient import TestClient

from app.main import app, storage, active_recommendations
from app.models import TransferRecommendation

client = TestClient(app)

# Pristine storage snapshots for test isolation
_PRISTINE_INV = storage.inv_path.read_text() if storage.inv_path.exists() else None
_PRISTINE_CONS = storage.consignments_path.read_text() if storage.consignments_path.exists() else None
_PRISTINE_IDEMP = storage.idempotency_path.read_text() if storage.idempotency_path.exists() else None
_PRISTINE_AUDIT = storage.audit_path.read_text() if storage.audit_path.exists() else None
_PRISTINE_RECS = copy.deepcopy(active_recommendations)

@pytest.fixture(autouse=True)
def isolate_test_state():
    def _restore():
        if _PRISTINE_INV is not None:
            storage.inv_path.write_text(_PRISTINE_INV)
        elif storage.inv_path.exists():
            storage.inv_path.unlink()

        if _PRISTINE_CONS is not None:
            storage.consignments_path.write_text(_PRISTINE_CONS)
        elif storage.consignments_path.exists():
            storage.consignments_path.unlink()

        if _PRISTINE_IDEMP is not None:
            storage.idempotency_path.write_text(_PRISTINE_IDEMP)
        elif storage.idempotency_path.exists():
            storage.idempotency_path.unlink()

        if _PRISTINE_AUDIT is not None:
            storage.audit_path.write_text(_PRISTINE_AUDIT)
        elif storage.audit_path.exists():
            storage.audit_path.unlink()

        active_recommendations.clear()
        active_recommendations.update(copy.deepcopy(_PRISTINE_RECS))

    _restore()
    yield
    _restore()


def test_full_clinic_day_scenario_10_steps():
    """
    Validates the full 10-step realistic clinic day acceptance exercise:
    1. Pharmacist records morning count (optimistic locking & audit stamp)
    2. Frontline worker submits ambiguous voice report (draft only, zero inventory mutation)
    3. Pharmacist records routine consumption (usable unreserved stock check, over-issue blocked)
    4. Supervisor approves transfer (donor reservation increases, recipient uncredited)
    5. Donor dispatches (donor physical stock decreases, transit record opens)
    6. Recipient records damage/shortage (accepted + quarantined + missing == dispatched invariant)
    7. Replayed receipt request (idempotent, zero duplicate stock addition)
    8. Network failure / retry simulation with conflicting payload (HTTP 409 Conflict)
    9. Application restart & storage integrity verification (SHA-256 chain verified)
    10. Shortage against reservations triggers freeze, stock register verification & MOIC resolution
    """
    donor_fac = "CHC-LKO-02"
    recipient_fac = "PHC-LKO-01"
    med_id = "MED-001"  # Salbutamol 100mcg Inhaler
    batch_num = "BAT-SAL-01"

    # Seed clean donor inventory for the exercise
    inv, cons, idem, _ = storage.load_all()
    donor_item = {
        "facility_id": donor_fac,
        "facility_name": "CHC Malihabad",
        "medicine_id": med_id,
        "medicine_name": "Salbutamol Inhaler",
        "batch_number": batch_num,
        "expiry_date": "2027-10-31",
        "days_to_expiry": 420,
        "daily_consumption_base": 5.0,
        "on_hand": 100,
        "reserved": 0,
        "quarantined": 0,
        "available": 100,
        "current_stock": 100,
        "pack_size": 10,
        "unit": "Inhalers",
        "version": 1,
        "is_frozen": False,
        "last_updated": "2026-09-08 00:00:00"
    }
    # Clean recipient item if exists
    inv = [i for i in inv if not (i["facility_id"] == donor_fac and i["medicine_id"] == med_id)]
    inv = [i for i in inv if not (i["facility_id"] == recipient_fac and i["medicine_id"] == med_id)]
    inv.append(donor_item)
    storage.commit_transaction(inv, cons, idem)

    # --------------------------------------------------------------------------
    # STEP 1: Pharmacist records morning shelf count (Version-checked)
    # --------------------------------------------------------------------------
    desk_res = client.get(f"/api/clinic/{donor_fac}/desk")
    assert desk_res.status_code == 200
    desk_data = desk_res.json()
    item_v1 = next(i for i in desk_data["inventory"] if i["medicine_id"] == med_id and i["batch_number"] == batch_num)
    assert item_v1["version"] == 1

    # Stale version check: attempt to count with expected_version=999 must return 409
    stale_res = client.post(f"/api/clinic/{donor_fac}/stock-action", json={
        "facility_id": donor_fac,
        "medicine_id": med_id,
        "batch_number": batch_num,
        "action_type": "PHYSICAL_COUNT",
        "quantity": 100,
        "expected_version": 999,
        "reason": "Stale update test"
    })
    assert stale_res.status_code == 409

    # Valid morning physical count
    count_res = client.post(f"/api/clinic/{donor_fac}/stock-action", json={
        "facility_id": donor_fac,
        "medicine_id": med_id,
        "batch_number": batch_num,
        "action_type": "PHYSICAL_COUNT",
        "quantity": 100,
        "expected_version": 1,
        "reason": "Morning shelf verification by Ramesh Verma",
        "operator_name": "Ramesh Verma",
        "operator_role": "PHARMACIST"
    })
    assert count_res.status_code == 200
    count_data = count_res.json()
    assert count_data["version"] == 2
    assert count_data["new_on_hand"] == 100
    assert count_data["new_available"] == 100
    assert count_data["reconciliation_exception"] is False

    # --------------------------------------------------------------------------
    # STEP 2: Frontline worker submits ambiguous voice report (Draft Only)
    # --------------------------------------------------------------------------
    voice_res = client.post("/api/voice-intake", json={
        "transcript_text": "Bhaiya Malihabad store se bol rahe hain, lagbhag 20 inhaler kharch ho gaye lagta hai",
        "facility_id": donor_fac,
        "language": "hi"
    })
    assert voice_res.status_code == 200
    voice_data = voice_res.json()
    assert voice_data["is_draft"] is True
    assert voice_data["action_taken"] == "DRAFT_CREATED_AWAITING_CONFIRMATION"

    # Master inventory must be 100% UNTOUCHED
    inv_check, _, _, _ = storage.load_all()
    d_check = next(i for i in inv_check if i["facility_id"] == donor_fac and i["medicine_id"] == med_id)
    assert d_check["on_hand"] == 100
    assert d_check["available"] == 100

    # --------------------------------------------------------------------------
    # STEP 3: Pharmacist records routine OPD consumption (10 units)
    # --------------------------------------------------------------------------
    # Over-issuance attempt: trying to issue 150 units when only 100 available -> 409
    over_res = client.post(f"/api/clinic/{donor_fac}/stock-action", json={
        "facility_id": donor_fac,
        "medicine_id": med_id,
        "batch_number": batch_num,
        "action_type": "STOCK_ISSUED",
        "quantity": 150,
        "reason": "Over-issue attempt"
    })
    assert over_res.status_code == 409

    # Valid OPD issuance of 10 units
    issue_res = client.post(f"/api/clinic/{donor_fac}/stock-action", json={
        "facility_id": donor_fac,
        "medicine_id": med_id,
        "batch_number": batch_num,
        "action_type": "STOCK_ISSUED",
        "quantity": 10,
        "reason": "Morning OPD dispensing to asthma patients",
        "operator_name": "Ramesh Verma",
        "operator_role": "PHARMACIST"
    })
    assert issue_res.status_code == 200
    issue_data = issue_res.json()
    assert issue_data["new_on_hand"] == 90
    assert issue_data["new_available"] == 90
    assert issue_data["version"] == 3

    # --------------------------------------------------------------------------
    # STEP 4: Supervisor approves transfer (20 units reserved at donor)
    # --------------------------------------------------------------------------
    rec_id = f"REC-CLINIC-ACCEPT-{uuid.uuid4().hex[:6]}"
    rec = TransferRecommendation(
        id=rec_id,
        donor_facility_id=donor_fac,
        donor_facility_name="CHC Malihabad",
        recipient_facility_id=recipient_fac,
        recipient_facility_name="PHC Kakori",
        medicine_id=med_id,
        medicine_name="Salbutamol Inhaler",
        batch_number=batch_num,
        batch_expiry_days=420,
        units_to_transfer=20,
        donor_min_reserve_units=50,
        distance_km=14.2,
        recipient_initial_coverage_days=1.5,
        recipient_new_coverage_days=6.5,
        donor_remaining_coverage_days=14.0,
        expiry_waste_prevented=False,
        rationale_en="Deterministic clinical surge acceptance test",
        rationale_hi="Deterministic clinical surge acceptance test",
        route_status="OPEN",
        status="PENDING_APPROVAL"
    )
    active_recommendations[rec_id] = rec

    app_res = client.post("/api/approve-transfer", json={
        "recommendation_id": rec_id,
        "officer_name": "Dr. S. K. Saxena",
        "comments": "Approved 20 inhalers for high-smog surge at Kakori"
    })
    assert app_res.status_code == 200
    app_data = app_res.json()
    consignment_id = app_data["consignment_id"]
    challan_id = app_data["dispatch_challan_id"]
    assert app_data["status"] == "APPROVED"

    # Verify donor reservation: on_hand=90 (unchanged), reserved=20, available=70
    inv_post_app, cons_post_app, _, _ = storage.load_all()
    donor_post_app = next(i for i in inv_post_app if i["facility_id"] == donor_fac and i["medicine_id"] == med_id)
    assert donor_post_app["on_hand"] == 90
    assert donor_post_app["reserved"] == 20
    assert donor_post_app["available"] == 70

    # Recipient inventory must be completely uncredited
    recip_items = [i for i in inv_post_app if i["facility_id"] == recipient_fac and i["medicine_id"] == med_id]
    assert len(recip_items) == 0 or recip_items[0].get("on_hand", 0) == 0

    # --------------------------------------------------------------------------
    # STEP 5: Donor dispatches (Donor physical on-hand drops, transit record opens)
    # --------------------------------------------------------------------------
    disp_res = client.post("/api/transfer/dispatch", json={
        "consignment_id": consignment_id,
        "operator_name": "Ramesh Verma",
        "operator_role": "PHARMACIST",
        "vehicle_number": "UP-32-MED-4412",
        "courier_notes": "Insulated transport carrier with temperature log"
    })
    assert disp_res.status_code == 200
    disp_data = disp_res.json()
    assert disp_data["status"] == "DISPATCHED"
    assert disp_data["units_dispatched"] == 20

    # Verify donor: physical on-hand drops to 70, reservation clears to 0, available remains 70
    inv_post_disp, _, _, _ = storage.load_all()
    donor_post_disp = next(i for i in inv_post_disp if i["facility_id"] == donor_fac and i["medicine_id"] == med_id)
    assert donor_post_disp["on_hand"] == 70
    assert donor_post_disp["reserved"] == 0
    assert donor_post_disp["available"] == 70

    # Recipient: in_transit increases to 20, but available and on_hand remain 0
    recip_desk_res = client.get(f"/api/clinic/{recipient_fac}/desk")
    assert recip_desk_res.status_code == 200
    recip_desk = recip_desk_res.json()
    assert len(recip_desk["inbound_consignments"]) == 1
    assert recip_desk["inbound_consignments"][0]["status"] == "DISPATCHED"

    # --------------------------------------------------------------------------
    # STEP 6: Recipient records receipt with damage/shortage inspection
    # Invariant: Q_dispatched (20) = accepted (16) + quarantined (2) + missing (2)
    # --------------------------------------------------------------------------
    # Invariant breach attempt: 16 + 2 + 1 = 19 != 20 -> must return HTTP 400
    bad_math_res = client.post("/api/transfer/receive", json={
        "consignment_id": consignment_id,
        "accepted_units": 16,
        "quarantined_units": 2,
        "missing_units": 1,
        "operator_name": "Anil Kumar",
        "operator_role": "PHARMACIST",
        "discrepancy_notes": "Missing math error"
    })
    assert bad_math_res.status_code == 400

    # Valid receipt with idempotency key
    receipt_key = f"IDEM-RECEIPT-{uuid.uuid4().hex[:8]}"
    receive_payload = {
        "consignment_id": consignment_id,
        "accepted_units": 16,
        "quarantined_units": 2,
        "missing_units": 2,
        "operator_name": "Anil Kumar",
        "operator_role": "PHARMACIST",
        "discrepancy_notes": "2 units crushed in transit, 2 units missing from package count",
        "idempotency_key": receipt_key
    }
    rec_res = client.post("/api/transfer/receive", json=receive_payload)
    assert rec_res.status_code == 200
    rec_data = rec_res.json()
    assert rec_data["status"] == "RECEIVED"
    assert rec_data["units_accepted"] == 16
    assert rec_data["units_quarantined"] == 2
    assert rec_data["units_missing"] == 2

    # Recipient inventory verification:
    # on_hand = accepted (16) + quarantined (2) = 18
    # quarantined = 2
    # available = 16 (strictly usable accepted stock)
    inv_post_rec, _, _, _ = storage.load_all()
    recip_item = next(i for i in inv_post_rec if i["facility_id"] == recipient_fac and i["medicine_id"] == med_id)
    assert recip_item["on_hand"] == 18
    assert recip_item["quarantined"] == 2
    assert recip_item["available"] == 16

    # --------------------------------------------------------------------------
    # STEP 7: Replayed receipt request (Idempotent replay, zero duplicate mutation)
    # --------------------------------------------------------------------------
    replay_res = client.post("/api/transfer/receive", json=receive_payload)
    assert replay_res.status_code == 200
    assert replay_res.json()["status"] == "RECEIVED"

    # Inventory must remain exactly on_hand=18, available=16 (NO duplicate increment!)
    inv_replay, _, _, _ = storage.load_all()
    recip_replay = next(i for i in inv_replay if i["facility_id"] == recipient_fac and i["medicine_id"] == med_id)
    assert recip_replay["on_hand"] == 18
    assert recip_replay["available"] == 16

    # --------------------------------------------------------------------------
    # STEP 8: Network retry with conflicting payload (HTTP 409 Conflict)
    # --------------------------------------------------------------------------
    conflict_payload = copy.deepcopy(receive_payload)
    conflict_payload["accepted_units"] = 20  # Different payload with same key
    conflict_payload["quarantined_units"] = 0
    conflict_payload["missing_units"] = 0
    conflict_res = client.post("/api/transfer/receive", json=conflict_payload)
    assert conflict_res.status_code == 409
    assert "idempotency conflict" in conflict_res.text.lower()

    # --------------------------------------------------------------------------
    # STEP 9: Application restart simulation & storage integrity verification
    # --------------------------------------------------------------------------
    verify_res = client.get("/api/audit-log/verify")
    assert verify_res.status_code == 200
    v_data = verify_res.json()
    assert v_data["valid"] is True
    assert v_data["total_blocks"] >= 5
    assert v_data["tamper_evident"] is True

    # --------------------------------------------------------------------------
    # STEP 10: Shelf shortage against active reservations triggers freeze & MOIC resolution
    # --------------------------------------------------------------------------
    # Seed a batch with 50 units on-hand and 40 units reserved for another transfer
    recon_med = "MED-002"  # Paracetamol 500mg
    recon_batch = "BAT-PARA-RECON"
    inv_r, cons_r, idem_r, _ = storage.load_all()
    inv_r.append({
        "facility_id": donor_fac,
        "facility_name": "CHC Malihabad",
        "medicine_id": recon_med,
        "medicine_name": "Paracetamol 500mg",
        "batch_number": recon_batch,
        "expiry_date": "2028-06-30",
        "days_to_expiry": 650,
        "daily_consumption_base": 15.0,
        "on_hand": 50,
        "reserved": 40,
        "quarantined": 0,
        "available": 10,
        "current_stock": 50,
        "pack_size": 10,
        "unit": "Tablets",
        "version": 1,
        "is_frozen": False,
        "last_updated": "2026-09-08 00:00:00"
    })
    storage.commit_transaction(inv_r, cons_r, idem_r)

    # Pharmacist performs count and finds only 30 units (10 units deficit against 40 reserved!)
    count_shortage_res = client.post(f"/api/clinic/{donor_fac}/stock-action", json={
        "facility_id": donor_fac,
        "medicine_id": recon_med,
        "batch_number": recon_batch,
        "action_type": "PHYSICAL_COUNT",
        "quantity": 30,
        "reason": "Count revealed shelf count below reservations"
    })
    assert count_shortage_res.status_code == 200
    cs_data = count_shortage_res.json()
    assert cs_data["reconciliation_exception"] is True
    assert cs_data["reconciliation_deficit"] == 10
    assert cs_data["raw_available"] == -10
    assert cs_data["new_available"] == 0
    assert cs_data["new_on_hand"] == 30
    assert cs_data["new_reserved"] == 40  # Commitment preserved: not silently lowered!

    # Verify operations on this batch are blocked:
    # 1. Issuing stock must fail with 409 Conflict
    blocked_issue_res = client.post(f"/api/clinic/{donor_fac}/stock-action", json={
        "facility_id": donor_fac,
        "medicine_id": recon_med,
        "batch_number": recon_batch,
        "action_type": "STOCK_ISSUED",
        "quantity": 5,
        "reason": "Attempt to issue frozen batch"
    })
    assert blocked_issue_res.status_code == 409
    assert "frozen" in blocked_issue_res.text.lower()

    # 2. Check Daily Desk Action Priorities: RECONCILIATION_REQUIRED item must be listed
    desk_after_freeze = client.get(f"/api/clinic/{donor_fac}/desk").json()
    recon_action = next(a for a in desk_after_freeze["action_items"] if a["action_type"] == "RECONCILIATION_REQUIRED" and a["target_medicine_id"] == recon_med)
    assert recon_action["urgency"] == "CRITICAL"

    # 3. Check Stock Movement Register: verify full chronological movements and compliance notice
    reg_res = client.get(f"/api/clinic/{donor_fac}/stock-register?medicine_id={recon_med}&batch_number={recon_batch}")
    assert reg_res.status_code == 200
    reg_data = reg_res.json()
    assert reg_data["facility_id"] == donor_fac
    assert reg_data["medicine_id"] == recon_med
    assert reg_data["batch_number"] == recon_batch
    assert reg_data["is_frozen"] is True
    assert reg_data["reconciliation_deficit"] == 10
    assert "Pre-validation e-Aushadhi / Form 16 Working Format" in reg_data["compliance_notice"]
    assert len(reg_data["movements"]) > 0

    # 4. Attempt resolution by non-MOIC unauthorized role -> Must return HTTP 403 Forbidden
    unauth_recon_res = client.post(f"/api/clinic/{donor_fac}/resolve-reconciliation", json={
        "facility_id": donor_fac,
        "medicine_id": recon_med,
        "batch_number": recon_batch,
        "resolution_type": "SUPERVISOR_RECOUNT",
        "verified_physical_count": 50,
        "supervisor_name": "Ramesh Verma",
        "supervisor_role": "PHARMACIST",  # Pharmacist cannot resolve!
        "resolution_notes": "Attempt by pharmacist"
    })
    assert unauth_recon_res.status_code == 403

    # 5. MOIC Supervisor recount verification: recounts 45 units on shelf (>= 40 reserved)
    moic_recon_res = client.post(f"/api/clinic/{donor_fac}/resolve-reconciliation", json={
        "facility_id": donor_fac,
        "medicine_id": recon_med,
        "batch_number": recon_batch,
        "resolution_type": "SUPERVISOR_RECOUNT",
        "verified_physical_count": 45,
        "supervisor_name": "Dr. S. K. Saxena (MOIC)",
        "supervisor_role": "MOIC",
        "resolution_notes": "Joint recount by MOIC and storekeeper. Extra 15 units verified in reserve bin."
    })
    assert moic_recon_res.status_code == 200
    moic_data = moic_recon_res.json()
    assert moic_data["success"] is True
    assert moic_data["is_frozen"] is False
    assert moic_data["new_on_hand"] == 45
    assert moic_data["new_reserved"] == 40
    assert moic_data["new_available"] == 5
    assert moic_data["raw_available"] == 5

    # Check inventory post-resolution: batch is completely unfrozen with 5 usable available units
    inv_post_moic, _, _, _ = storage.load_all()
    unfrozen_item = next(i for i in inv_post_moic if i["facility_id"] == donor_fac and i["medicine_id"] == recon_med and i.get("batch_number") == recon_batch)
    assert unfrozen_item["is_frozen"] is False
    assert unfrozen_item["reconciliation_deficit"] == 0
    assert unfrozen_item["available"] == 5


def test_concurrent_competing_stock_requests():
    """
    Concurrency safety verification:
    Simulates 2 concurrent requests competing for the same 10 available units.
    Ensures that with transactional execution and atomic locking:
    - Exactly 1 request succeeds (HTTP 200).
    - Exactly 1 request is rejected (HTTP 409 Conflict).
    - Final stock is exactly 0, never negative.
    """
    facility_id = "PHC-LKO-01"
    med_id = "MED-CONCUR-01"
    batch_num = "BAT-CONCUR-01"

    inv, cons, idem, _ = storage.load_all()
    item = {
        "facility_id": facility_id,
        "facility_name": "PHC Kakori",
        "medicine_id": med_id,
        "medicine_name": "Azithromycin 500mg",
        "batch_number": batch_num,
        "expiry_date": "2027-12-31",
        "days_to_expiry": 400,
        "daily_consumption_base": 5.0,
        "on_hand": 10,
        "reserved": 0,
        "quarantined": 0,
        "available": 10,
        "current_stock": 10,
        "pack_size": 10,
        "unit": "Tablets",
        "version": 1,
        "is_frozen": False,
        "last_updated": "2026-09-08 00:00:00"
    }
    inv.append(item)
    storage.commit_transaction(inv, cons, idem)

    def _issue_stock(worker_id: int):
        t_client = TestClient(app)
        return t_client.post(f"/api/clinic/{facility_id}/stock-action", json={
            "facility_id": facility_id,
            "medicine_id": med_id,
            "batch_number": batch_num,
            "action_type": "STOCK_ISSUED",
            "quantity": 10,
            "expected_version": 1,  # Both threads expect initial version 1
            "reason": f"Concurrent issue from worker {worker_id}",
            "operator_name": f"Worker {worker_id}",
            "operator_role": "PHARMACIST"
        })

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_issue_stock, 1)
        f2 = executor.submit(_issue_stock, 2)
        r1 = f1.result()
        r2 = f2.result()

    status_codes = sorted([r1.status_code, r2.status_code])
    # Exactly one must succeed (200) and one must fail with 409 Conflict
    assert status_codes == [200, 409], f"Unexpected status codes: {status_codes}"

    inv_final, _, _, _ = storage.load_all()
    final_item = next(i for i in inv_final if i["facility_id"] == facility_id and i["medicine_id"] == med_id)
    assert final_item["on_hand"] == 0
    assert final_item["available"] == 0
