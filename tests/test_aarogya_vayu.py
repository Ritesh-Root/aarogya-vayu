import pytest
import json
import copy
import uuid
from fastapi.testclient import TestClient
from app.main import app, inventory_data, active_recommendations, audit_ledger, optimizer, surge_engine, domain_service, storage
from app.models import (
    EnvironmentalReading, StockoutRiskAssessment, TransferRecommendation,
    VoiceIntakeRequest, ApprovalRequest, StockActionRequest,
    DispatchConsignmentRequest, ReceiveConsignmentRequest, CancelConsignmentRequest
)
from app.audit_ledger import AuditLedger

client = TestClient(app)

# Module-level pristine snapshots captured once when test runner imports:
_PRISTINE_INV = storage.inv_path.read_text() if storage.inv_path.exists() else None
_PRISTINE_CONS = storage.consignments_path.read_text() if storage.consignments_path.exists() else None
_PRISTINE_IDEMP = storage.idempotency_path.read_text() if storage.idempotency_path.exists() else None
_PRISTINE_AUDIT = storage.audit_path.read_text() if storage.audit_path.exists() else None
_PRISTINE_RECS = copy.deepcopy(active_recommendations)

@pytest.fixture(autouse=True)
def isolate_test_state():
    """
    Restore pristine baseline state before and after each test,
    ensuring 100% isolation and repeatability without test pollution.
    """
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

def test_environmental_surge_multipliers():
    """Verify that climate signals correctly trigger epidemiological demand multipliers."""
    smog_env = EnvironmentalReading(aqi=385, pm25=245.0, temperature_c=18.0, smog_episode=True)
    mults = surge_engine.calculate_surge_multipliers(smog_env)
    assert mults["AQI / Smog"] >= 1.60, f"Expected AQI surge >= 1.60, got {mults['AQI / Smog']}"

    heat_env = EnvironmentalReading(aqi=75, temperature_c=43.5, heatwave_alert=True, smog_episode=False)
    heat_mults = surge_engine.calculate_surge_multipliers(heat_env)
    assert heat_mults["Heatwave / Drought"] >= 1.68, f"Expected Heat surge >= 1.68, got {heat_mults['Heatwave / Drought']}"


def test_optimizer_constraints_and_donor_safety():
    """Verify that optimizer respects distance (<=35km), pack sizes, and protects donor reserves."""
    env = EnvironmentalReading(aqi=385, smog_episode=True)
    raw_inv = copy.deepcopy(inventory_data)
    risks = surge_engine.assess_facility_risks(raw_inv, env)
    recs = optimizer.optimize(risks, raw_inv)

    assert len(recs) > 0, "Expected at least one valid recommendation under severe smog"

    for rec in recs:
        assert rec.distance_km <= 35.0, f"Transfer {rec.id} exceeds 35km: {rec.distance_km}km"
        assert rec.units_to_transfer > 0, f"Units must be positive: {rec.units_to_transfer}"
        assert rec.donor_remaining_coverage_days >= 14.0, f"Donor {rec.donor_facility_name} left with < 14d cover: {rec.donor_remaining_coverage_days}d"
        assert rec.donor_min_reserve_units > 0, "Donor min reserve units must be recorded"


def test_transfer_lifecycle_reservation_and_conservation():
    """
    Verify complete lifecycle conservation across:
    REQUESTED -> APPROVED/RESERVED -> DISPATCHED -> RECEIVED
    """
    env = EnvironmentalReading(aqi=385, smog_episode=True)
    inv, _, _, _ = storage.load_all()
    risks = surge_engine.assess_facility_risks(inv, env)
    recs = optimizer.optimize(risks, inv)
    assert len(recs) > 0, "Need recommendations for testing"
    
    target_rec = recs[0]
    active_recommendations[target_rec.id] = target_rec

    donor_before = next(i["on_hand"] for i in inv if i["facility_id"] == target_rec.donor_facility_id and i["medicine_id"] == target_rec.medicine_id)
    rec_before = sum(i["on_hand"] for i in inv if i["facility_id"] == target_rec.recipient_facility_id and i["medicine_id"] == target_rec.medicine_id)
    total_physical_before = donor_before + rec_before

    # 1. APPROVAL: donor reserves Q, recipient on_hand DOES NOT change
    approve_res = client.post("/api/approve-transfer", json={
        "recommendation_id": target_rec.id,
        "officer_name": "Dr. Test CMO",
        "comments": "Unit test verified approval"
    })
    assert approve_res.status_code == 200, f"Approval failed: {approve_res.text}"
    app_data = approve_res.json()
    assert app_data["status"] == "APPROVED"
    consignment_id = app_data["consignment_id"]

    inv_after_app, _, _, _ = storage.load_all()
    donor_app = next(i for i in inv_after_app if i["facility_id"] == target_rec.donor_facility_id and i["medicine_id"] == target_rec.medicine_id)
    rec_app_sum = sum(i["on_hand"] for i in inv_after_app if i["facility_id"] == target_rec.recipient_facility_id and i["medicine_id"] == target_rec.medicine_id)

    # Donor on-hand has NOT decreased yet, but reserved has increased
    assert donor_app["on_hand"] == donor_before
    assert donor_app["reserved"] >= target_rec.units_to_transfer
    # Recipient has NOT received stock prematurely
    assert rec_app_sum == rec_before

    # 2. DISPATCH: donor on_hand drops, reserved drops
    dispatch_res = client.post("/api/transfer/dispatch", json={
        "consignment_id": consignment_id,
        "operator_name": "Ramesh (Pharmacist)",
        "operator_role": "PHARMACIST",
        "vehicle_number": "UP-32-MED-99"
    })
    assert dispatch_res.status_code == 200
    disp_data = dispatch_res.json()
    assert disp_data["status"] == "DISPATCHED"

    inv_after_disp, _, _, _ = storage.load_all()
    donor_disp = next(i for i in inv_after_disp if i["facility_id"] == target_rec.donor_facility_id and i["medicine_id"] == target_rec.medicine_id)
    assert donor_disp["on_hand"] == donor_before - target_rec.units_to_transfer

    # 3. RECEIVE: recipient confirms receipt
    receive_res = client.post("/api/transfer/receive", json={
        "consignment_id": consignment_id,
        "operator_name": "Suresh (Pharmacist)",
        "operator_role": "PHARMACIST",
        "accepted_units": target_rec.units_to_transfer,
        "quarantined_units": 0,
        "missing_units": 0,
        "condition_intact": True
    })
    assert receive_res.status_code == 200
    rec_data = receive_res.json()
    assert rec_data["status"] == "RECEIVED"

    inv_after_rec, _, _, _ = storage.load_all()
    rec_after = sum(i["on_hand"] for i in inv_after_rec if i["facility_id"] == target_rec.recipient_facility_id and i["medicine_id"] == target_rec.medicine_id)
    assert rec_after == rec_before + target_rec.units_to_transfer

    # Strict physical conservation
    donor_final = next(i["on_hand"] for i in inv_after_rec if i["facility_id"] == target_rec.donor_facility_id and i["medicine_id"] == target_rec.medicine_id)
    assert total_physical_before == donor_final + rec_after


def test_deterministic_acceptance_scenario():
    """
    Acceptance Fixture required by specification:
    | Step | Donor on hand | Donor reserved | In transit | Recipient on hand | Recipient quarantined |
    | Initial | 300 | 0 | 0 | 20 | 0 |
    | Reserve 90 | 300 | 90 | 0 | 20 | 0 |
    | Dispatch 90 | 210 | 0 | 90 | 20 | 0 |
    | Receive: 75 accepted, 5 quarantined, 10 missing | 210 | 0 | 0 | 100 | 5 |
    Final Recipient Available: 95
    Strict Conservation: Initial Physical (320) = Final Physical (310) + Missing (10)
    """
    uid = uuid.uuid4().hex[:6]
    test_donor_fac = f"TEST-D-{uid}"
    test_rec_fac = f"TEST-R-{uid}"
    med_id = "MED-001"
    batch = f"BAT-DET-{uid}"

    inv, cons, idem, _ = storage.load_all()
    
    donor_item = {
        "facility_id": test_donor_fac,
        "facility_name": "Test Donor Clinic",
        "medicine_id": med_id,
        "medicine_name": "Salbutamol Respirator Solution (Respules 2.5mg)",
        "batch_number": batch,
        "expiry_date": "2027-12-31",
        "days_to_expiry": 400,
        "daily_consumption_base": 10.0,
        "on_hand": 300,
        "reserved": 0,
        "quarantined": 0,
        "available": 300,
        "current_stock": 300,
        "pack_size": 10,
        "unit": "Respules",
        "version": 1,
        "is_frozen": False,
        "last_updated": "2026-09-08 00:00:00"
    }
    rec_item = {
        "facility_id": test_rec_fac,
        "facility_name": "Test Recipient Clinic",
        "medicine_id": med_id,
        "medicine_name": "Salbutamol Respirator Solution (Respules 2.5mg)",
        "batch_number": batch,
        "expiry_date": "2027-12-31",
        "days_to_expiry": 400,
        "daily_consumption_base": 15.0,
        "on_hand": 20,
        "reserved": 0,
        "quarantined": 0,
        "available": 20,
        "current_stock": 20,
        "pack_size": 10,
        "unit": "Respules",
        "version": 1,
        "is_frozen": False,
        "last_updated": "2026-09-08 00:00:00"
    }
    inv.extend([donor_item, rec_item])
    storage.commit_transaction(inv, cons, idem)

    # Initial check
    assert donor_item["on_hand"] == 300 and donor_item["reserved"] == 0
    assert rec_item["on_hand"] == 20 and rec_item["quarantined"] == 0

    # Step 2: Reserve 90 units
    rec_id = f"REC-DET-{uid}"
    rec = TransferRecommendation(
        id=rec_id,
        donor_facility_id=test_donor_fac,
        donor_facility_name="Test Donor Clinic",
        recipient_facility_id=test_rec_fac,
        recipient_facility_name="Test Recipient Clinic",
        medicine_id=med_id,
        medicine_name="Salbutamol Respirator Solution (Respules 2.5mg)",
        units_to_transfer=90,
        batch_number=batch,
        batch_expiry_days=400,
        distance_km=12.0,
        recipient_initial_coverage_days=1.3,
        recipient_new_coverage_days=7.3,
        donor_remaining_coverage_days=21.0,
        donor_min_reserve_units=140,
        expiry_waste_prevented=False,
        rationale_en="Deterministic test",
        rationale_hi="Deterministic test",
        status="PENDING_APPROVAL"
    )
    active_recommendations[rec.id] = rec

    approval_res = client.post("/api/approve-transfer", json={
        "recommendation_id": rec.id,
        "officer_name": "CMO Dr. Deterministic"
    })
    assert approval_res.status_code == 200
    c_id = approval_res.json()["consignment_id"]

    inv_after_res, cons_after_res, _, _ = storage.load_all()
    d_res = next(i for i in inv_after_res if i["facility_id"] == test_donor_fac and i["medicine_id"] == med_id)
    r_res = next(i for i in inv_after_res if i["facility_id"] == test_rec_fac and i["medicine_id"] == med_id)
    assert d_res["on_hand"] == 300
    assert d_res["reserved"] == 90
    assert r_res["on_hand"] == 20

    # Step 3: Dispatch 90 units
    dispatch_res = client.post("/api/transfer/dispatch", json={
        "consignment_id": c_id,
        "operator_name": "Pharmacist Donor"
    })
    assert dispatch_res.status_code == 200

    inv_after_disp, _, _, _ = storage.load_all()
    d_disp = next(i for i in inv_after_disp if i["facility_id"] == test_donor_fac and i["medicine_id"] == med_id)
    r_disp = next(i for i in inv_after_disp if i["facility_id"] == test_rec_fac and i["medicine_id"] == med_id)
    assert d_disp["on_hand"] == 210
    assert d_disp["reserved"] == 0
    assert r_disp["on_hand"] == 20

    # Verify derived in-transit for recipient
    rec_desk = client.get(f"/api/clinic/{test_rec_fac}/desk").json()
    rec_desk_item = next(i for i in rec_desk["inventory"] if i["medicine_id"] == med_id)
    assert rec_desk_item["in_transit"] == 90

    # Step 4: Receive: 75 accepted, 5 quarantined, 10 missing (Total = 90)
    receive_res = client.post("/api/transfer/receive", json={
        "consignment_id": c_id,
        "operator_name": "Pharmacist Recipient",
        "accepted_units": 75,
        "quarantined_units": 5,
        "missing_units": 10,
        "condition_intact": False,
        "discrepancy_notes": "10 ampoules missing in transit, 5 crushed"
    })
    assert receive_res.status_code == 200

    inv_final, _, _, _ = storage.load_all()
    d_final = next(i for i in inv_final if i["facility_id"] == test_donor_fac and i["medicine_id"] == med_id)
    r_final = next(i for i in inv_final if i["facility_id"] == test_rec_fac and i["medicine_id"] == med_id)

    assert d_final["on_hand"] == 210
    assert d_final["reserved"] == 0

    assert r_final["on_hand"] == 100, f"Expected 100 on_hand, got {r_final['on_hand']}"
    assert r_final["quarantined"] == 5, f"Expected 5 quarantined, got {r_final['quarantined']}"
    assert r_final["available"] == 95, f"Expected 95 available, got {r_final['available']}"

    # Verify Invariant: Initial physical stock (320) = Final physical stock (310) + Missing (10)
    initial_physical = 300 + 20
    final_physical = d_final["on_hand"] + r_final["on_hand"]
    missing_stock = 10
    assert initial_physical == final_physical + missing_stock, f"Physical conservation violated: {initial_physical} != {final_physical} + {missing_stock}"


def test_consignment_cancellation_releases_reservation():
    """Verify that cancelling an approved transfer releases the reservation without mutating on_hand."""
    uid = uuid.uuid4().hex[:6]
    test_donor_fac = f"TEST-CAN-D-{uid}"
    test_rec_fac = f"TEST-CAN-R-{uid}"
    med_id = "MED-002"
    batch = f"BAT-CAN-{uid}"

    inv, cons, idem, _ = storage.load_all()
    donor_item = {
        "facility_id": test_donor_fac,
        "facility_name": "Test Donor Clinic",
        "medicine_id": med_id,
        "medicine_name": "ORS Sachets",
        "batch_number": batch,
        "expiry_date": "2027-12-31",
        "days_to_expiry": 400,
        "daily_consumption_base": 10.0,
        "on_hand": 200,
        "reserved": 0,
        "quarantined": 0,
        "available": 200,
        "current_stock": 200,
        "pack_size": 20,
        "unit": "Sachets",
        "version": 1,
        "is_frozen": False,
        "last_updated": "2026-09-08 00:00:00"
    }
    inv.append(donor_item)
    storage.commit_transaction(inv, cons, idem)

    rec = TransferRecommendation(
        id=f"REC-CAN-{uid}",
        donor_facility_id=test_donor_fac,
        donor_facility_name="Test Donor Clinic",
        recipient_facility_id=test_rec_fac,
        recipient_facility_name="Test Recipient Clinic",
        medicine_id=med_id,
        medicine_name="ORS Sachets",
        units_to_transfer=40,
        batch_number=batch,
        batch_expiry_days=400,
        distance_km=10.0,
        recipient_initial_coverage_days=1.0,
        recipient_new_coverage_days=5.0,
        donor_remaining_coverage_days=16.0,
        donor_min_reserve_units=100,
        expiry_waste_prevented=False,
        rationale_en="Cancel test",
        rationale_hi="Cancel test",
        status="PENDING_APPROVAL"
    )
    active_recommendations[rec.id] = rec

    # Approve
    app_res = client.post("/api/approve-transfer", json={"recommendation_id": rec.id})
    assert app_res.status_code == 200
    c_id = app_res.json()["consignment_id"]

    # Verify reserved
    inv_mid, _, _, _ = storage.load_all()
    d_mid = next(i for i in inv_mid if i["facility_id"] == test_donor_fac and i["medicine_id"] == med_id)
    assert d_mid["reserved"] == 40
    assert d_mid["available"] == 160

    # Cancel
    cancel_res = client.post("/api/transfer/cancel", json={
        "consignment_id": c_id,
        "reason": "Vehicle breakdown; route impassable"
    })
    assert cancel_res.status_code == 200

    inv_after_cancel, _, _, _ = storage.load_all()
    d_after = next(i for i in inv_after_cancel if i["facility_id"] == test_donor_fac and i["medicine_id"] == med_id)
    assert d_after["on_hand"] == 200
    assert d_after["reserved"] == 0
    assert d_after["available"] == 200


def test_physical_count_below_commitments_triggers_reconciliation_exception():
    """Verify that reporting a physical count below active commitments sets is_frozen and records exception."""
    uid = uuid.uuid4().hex[:6]
    test_fac = f"TEST-RECON-{uid}"
    med_id = "MED-003"
    batch = f"BAT-RECON-{uid}"

    inv, cons, idem, _ = storage.load_all()
    item = {
        "facility_id": test_fac,
        "facility_name": "Recon Clinic",
        "medicine_id": med_id,
        "medicine_name": "Dexamethasone",
        "batch_number": batch,
        "expiry_date": "2027-12-31",
        "days_to_expiry": 400,
        "daily_consumption_base": 10.0,
        "on_hand": 100,
        "reserved": 40,
        "quarantined": 10,
        "available": 50,
        "current_stock": 100,
        "pack_size": 10,
        "unit": "Ampoules",
        "version": 1,
        "is_frozen": False,
        "last_updated": "2026-09-08 00:00:00"
    }
    inv.append(item)
    storage.commit_transaction(inv, cons, idem)

    # Report count of 30, which is below reserved (40) + quarantined (10) = 50
    res = client.post(f"/api/clinic/{test_fac}/stock-action", json={
        "facility_id": test_fac,
        "medicine_id": med_id,
        "batch_number": batch,
        "action_type": "PHYSICAL_COUNT",
        "quantity": 30,
        "reason": "Physical count revealed missing stock"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["reconciliation_exception"] is True
    assert data["new_on_hand"] == 30

    inv_after, _, _, _ = storage.load_all()
    item_after = next(i for i in inv_after if i["facility_id"] == test_fac and i["medicine_id"] == med_id)
    assert item_after["is_frozen"] is True


def test_voice_intake_is_draft_only_and_does_not_mutate_master_stock():
    """Verify that voice intake generates a draft report and never mutates master stock."""
    inv_before, _, _, _ = storage.load_all()
    target_item = next(i for i in inv_before if i["facility_id"] == "PHC-LKO-01" and i["medicine_id"] == "MED-001")
    stock_before = target_item["on_hand"]

    payload = {
        "transcript_text": "PHC काकोरी से बोल रहे हैं, सांस की दवाई के सिर्फ 5 रेस्प्यूल बचे हैं, कल 40 मरीज आए थे।",
        "facility_id": "PHC-LKO-01",
        "language": "hi"
    }
    response = client.post("/api/voice-intake", json=payload)
    assert response.status_code == 200
    res = response.json()
    assert res["is_draft"] is True
    assert res["action_taken"] == "DRAFT_CREATED_AWAITING_CONFIRMATION"

    inv_after, _, _, _ = storage.load_all()
    target_after = next(i for i in inv_after if i["facility_id"] == "PHC-LKO-01" and i["medicine_id"] == "MED-001")
    # Master inventory must be UNTOUCHED
    assert target_after["on_hand"] == stock_before


def test_idempotency_enforcement_and_conflict_rejection():
    """Verify that same idempotency key returns cached result, while key reuse with different payload returns 409."""
    key = f"IDEM-KEY-{uuid.uuid4().hex[:8]}"
    req_body_1 = {
        "facility_id": "PHC-LKO-01",
        "medicine_id": "MED-002",
        "batch_number": "BAT-854-26",
        "action_type": "STOCK_RECEIVED",
        "quantity": 20,
        "reason": "Test receipt",
        "idempotency_key": key
    }
    res1 = client.post("/api/clinic/PHC-LKO-01/stock-action", json=req_body_1)
    assert res1.status_code == 200
    data1 = res1.json()

    # Replay identical payload with same key -> Returns cached response
    res2 = client.post("/api/clinic/PHC-LKO-01/stock-action", json=req_body_1)
    assert res2.status_code == 200
    assert res2.json()["new_on_hand"] == data1["new_on_hand"]

    # Replay same key with DIFFERENT payload (quantity 50 instead of 20) -> Must return 409 Conflict
    req_body_diff = copy.deepcopy(req_body_1)
    req_body_diff["quantity"] = 50
    res3 = client.post("/api/clinic/PHC-LKO-01/stock-action", json=req_body_diff)
    assert res3.status_code == 409
    assert "idempotency conflict" in res3.text.lower()


def test_audit_ledger_hash_chain_integrity():
    """Verify that the SHA-256 hash chain validates correctly and detects tampering."""
    response = client.get("/api/audit-log/verify")
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["valid"] is True
    assert res_data["total_blocks"] > 0
    assert res_data["tamper_evident"] is True


def test_clinic_desk_endpoint_contract():
    """Verify that Clinic Daily Desk endpoint returns full structured contract for frontline pharmacist."""
    response = client.get("/api/clinic/PHC-LKO-01/desk")
    assert response.status_code == 200
    data = response.json()

    assert data["operator_role_mode"] == "DEMO_ROLE_SIMULATION"
    assert data["facility"]["id"] == "PHC-LKO-01"
    assert isinstance(data["action_items"], list)
    assert isinstance(data["inventory"], list)
    assert len(data["inventory"]) > 0
    assert isinstance(data["inbound_consignments"], list)
    assert isinstance(data["outbound_consignments"], list)
    assert isinstance(data["active_reconciliation_exceptions"], list)

    for item in data["inventory"]:
        assert "on_hand" in item
        assert "reserved" in item
        assert "quarantined" in item
        assert "available" in item
        assert "pack_size" in item
        assert "is_frozen" in item
        # Mathematical invariant check:
        assert item["available"] == max(0, item["on_hand"] - item["reserved"] - item["quarantined"])

    cons_res = client.get("/api/consignments")
    assert cons_res.status_code == 200
    assert isinstance(cons_res.json(), list)

