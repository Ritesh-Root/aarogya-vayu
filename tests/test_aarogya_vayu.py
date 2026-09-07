import pytest
import json
import copy
from fastapi.testclient import TestClient
from app.main import app, inventory_data, active_recommendations, audit_ledger, optimizer, surge_engine
from app.models import EnvironmentalReading, StockoutRiskAssessment, TransferRecommendation, VoiceIntakeRequest, ApprovalRequest
from app.audit_ledger import AuditLedger

client = TestClient(app)

def test_environmental_surge_multipliers():
    """Verify that climate signals correctly trigger epidemiological demand multipliers."""
    # Smog event (AQI 385)
    smog_env = EnvironmentalReading(aqi=385, pm25=245.0, temperature_c=18.0, smog_episode=True)
    mults = surge_engine.calculate_surge_multipliers(smog_env)
    assert mults["AQI / Smog"] >= 1.60, f"Expected AQI surge >= 1.60, got {mults['AQI / Smog']}"

    # Heatwave event (43.5C)
    heat_env = EnvironmentalReading(aqi=75, temperature_c=43.5, heatwave_alert=True, smog_episode=False)
    heat_mults = surge_engine.calculate_surge_multipliers(heat_env)
    assert heat_mults["Heatwave / Drought"] >= 1.68, f"Expected Heat surge >= 1.68, got {heat_mults['Heatwave / Drought']}"


def test_optimizer_constraints_and_donor_safety():
    """Verify that optimizer respects distance (<=35km) and protects donor surge reserves (>=14d)."""
    env = EnvironmentalReading(aqi=385, smog_episode=True)
    raw_inv = copy.deepcopy(inventory_data)
    risks = surge_engine.assess_facility_risks(raw_inv, env)
    recs = optimizer.optimize(risks, raw_inv)

    assert len(recs) > 0, "Expected at least one valid recommendation under severe smog"

    for rec in recs:
        # 1. Distance constraint
        assert rec.distance_km <= 35.0, f"Transfer {rec.id} exceeds 35km: {rec.distance_km}km"
        # 2. Positive batch transfer
        assert rec.units_to_transfer > 0 and rec.units_to_transfer % 10 == 0, f"Units must be positive multiple of 10: {rec.units_to_transfer}"
        # 3. Donor remaining days coverage >= 14 days
        assert rec.donor_remaining_coverage_days >= 14.0, f"Donor {rec.donor_facility_name} left with < 14d cover: {rec.donor_remaining_coverage_days}d"
        # 4. Donor min reserve units recorded
        assert rec.donor_min_reserve_units > 0, "Donor min reserve units must be recorded"


def test_inventory_conservation_on_transfer_approval():
    """Verify exact stock conservation: Delta(donor) + Delta(recipient) == 0."""
    # Find or recompute a pending recommendation
    env = EnvironmentalReading(aqi=385, smog_episode=True)
    risks = surge_engine.assess_facility_risks(inventory_data, env)
    recs = optimizer.optimize(risks, inventory_data)
    assert len(recs) > 0, "Need recommendations for testing"
    
    target_rec = recs[0]
    active_recommendations[target_rec.id] = target_rec

    donor_before = next(i["current_stock"] for i in inventory_data if i["facility_id"] == target_rec.donor_facility_id and i["medicine_id"] == target_rec.medicine_id)
    rec_before = next(i["current_stock"] for i in inventory_data if i["facility_id"] == target_rec.recipient_facility_id and i["medicine_id"] == target_rec.medicine_id)
    total_before = donor_before + rec_before

    response = client.post("/api/approve-transfer", json={
        "recommendation_id": target_rec.id,
        "officer_name": "Dr. Test CMO",
        "comments": "Unit test verified dispatch"
    })
    assert response.status_code == 200, f"Approval failed: {response.text}"
    data = response.json()
    assert data["status"] == "APPROVED"
    assert "dispatch_challan_id" in data
    assert "cryptographic_hash" in data

    donor_after = next(i["current_stock"] for i in inventory_data if i["facility_id"] == target_rec.donor_facility_id and i["medicine_id"] == target_rec.medicine_id)
    rec_after = next(i["current_stock"] for i in inventory_data if i["facility_id"] == target_rec.recipient_facility_id and i["medicine_id"] == target_rec.medicine_id)
    total_after = donor_after + rec_after

    # Strict conservation invariant
    assert total_before == total_after, f"Stock conservation violated: before={total_before}, after={total_after}"
    assert donor_before - donor_after == target_rec.units_to_transfer
    assert rec_after - rec_before == target_rec.units_to_transfer


def test_approval_idempotency():
    """Verify that re-approving an already approved transfer returns cached challan without double-decrementing."""
    # Pick the already approved recommendation from previous test or create one
    recs = [r for r in active_recommendations.values() if r.status == "APPROVED"]
    assert len(recs) > 0
    approved_rec = recs[0]

    donor_stock_before = next(i["current_stock"] for i in inventory_data if i["facility_id"] == approved_rec.donor_facility_id and i["medicine_id"] == approved_rec.medicine_id)

    # Re-attempt approval
    response = client.post("/api/approve-transfer", json={
        "recommendation_id": approved_rec.id,
        "officer_name": "Dr. Test CMO"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "APPROVED"
    assert data.get("already_approved") is True

    donor_stock_after = next(i["current_stock"] for i in inventory_data if i["facility_id"] == approved_rec.donor_facility_id and i["medicine_id"] == approved_rec.medicine_id)
    assert donor_stock_before == donor_stock_after, "Stock was decremented on idempotent re-approval!"


def test_overspending_and_concurrency_rejection():
    """Verify that transfers that would deplete donor below reserve or exceed available stock return HTTP 409 Conflict."""
    fake_rec_id = "REC-CONFLICT-TEST"
    active_recommendations[fake_rec_id] = TransferRecommendation(
        id=fake_rec_id,
        donor_facility_id="PHC-LKO-01",
        donor_facility_name="PHC Kakori",
        recipient_facility_id="CHC-LKO-04",
        recipient_facility_name="CHC Chinhat",
        medicine_id="MED-001",
        medicine_name="Salbutamol Respirator Solution",
        units_to_transfer=99999,  # Far exceeds any facility stock
        batch_number="BAT-TEST",
        batch_expiry_days=90,
        distance_km=15.0,
        recipient_initial_coverage_days=2.0,
        recipient_new_coverage_days=10.0,
        donor_remaining_coverage_days=15.0,
        donor_min_reserve_units=500,
        expiry_waste_prevented=False,
        rationale_en="Test",
        rationale_hi="Test",
        status="PENDING_APPROVAL"
    )

    response = client.post("/api/approve-transfer", json={
        "recommendation_id": fake_rec_id,
        "officer_name": "Dr. Test CMO"
    })
    assert response.status_code == 409, f"Expected 409 Conflict for overspending, got {response.status_code}"
    assert "conflict" in response.text.lower() or "insufficient" in response.text.lower()


def test_audit_ledger_hash_chain_integrity():
    """Verify that the SHA-256 hash chain validates correctly and detects tampering."""
    # Test through live endpoint
    response = client.get("/api/audit-log/verify")
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["valid"] is True
    assert res_data["total_blocks"] > 0
    assert res_data["tamper_evident"] is True

    # Test tampering detection on a fresh test ledger
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
        test_ledger = AuditLedger(ledger_file=tmp.name)
        test_ledger.record_entry("TEST_EVENT_1", {"units": 100}, approved_by="TEST_OFFICER_A")
        test_ledger.record_entry("TEST_EVENT_2", {"units": 200}, approved_by="TEST_OFFICER_B")
        
        # Valid state
        check = test_ledger.verify_chain_integrity()
        assert check["valid"] is True
        assert check["total_blocks"] == 3  # Genesis + 2 events

        # Introduce tamper in middle block
        test_ledger.entries[1]["details"]["units"] = 999
        tamper_check = test_ledger.verify_chain_integrity()
        assert tamper_check["valid"] is False
        assert tamper_check["compromised_index"] == 1
        assert "Tampering detected" in tamper_check["error"]


def test_frontline_voice_grounding_hindi_dialect():
    """Verify that Hindi colloquial speech is correctly grounded to EDL-UP-2026."""
    payload = {
        "transcript_text": "PHC काकोरी से बोल रहे हैं, सांस की दवाई के सिर्फ 15 रेस्प्यूल बचे हैं, कल 40 मरीज आए थे।",
        "facility_id": "PHC-LKO-01",
        "language": "hi"
    }
    response = client.post("/api/voice-intake", json=payload)
    assert response.status_code == 200
    res = response.json()
    assert res["medicine_id"] == "MED-001"
    assert "Salbutamol" in res["medicine_name"]
    assert res["reported_stock"] == 15
    assert res["dispensed_yesterday"] == 40
    assert res["quality_checks_passed"] is True
    assert res["confidence_score"] >= 0.85
    assert "EDL-UP-2026" in res.get("edl_category", "")


def test_frontline_voice_anomaly_flagging():
    """Verify that negative or implausibly high stock reports trigger an anomaly flag."""
    payload = {
        "transcript_text": "Stock count is 99999 units at PHC Kakori",
        "facility_id": "PHC-LKO-01"
    }
    response = client.post("/api/voice-intake", json=payload)
    assert response.status_code == 200
    res = response.json()
    assert res["quality_checks_passed"] is False
    assert res["anomaly_flag"] is not None
