"""
Domain integrity checks (stock, consignments, planning). Every test runs on a private copy of the
demo data in tmp_path, so the tracked data/ files are never written.
"""

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.audit_ledger import AuditLedger
from app.domain import InventoryDomainService
from app.models import (
    ApprovalRequest, DispatchConsignmentRequest, EnvironmentalReading,
    ReceiveConsignmentRequest, ResolveReconciliationRequest, StockActionRequest,
)
from app.optimizer import RedistributionOptimizer, committed_transfers
from app.storage import StorageManager, refresh_days_to_expiry
from app.surge_engine import SurgeEngine

REPO_DATA = Path(__file__).resolve().parent.parent / "data"


def _load(name):
    return json.loads((REPO_DATA / name).read_text())


FACILITIES = {f["id"]: f for f in _load("facilities.json") + _load("facilities_bhubaneswar.json")}
MEDICINES = {m["id"]: m for m in _load("medicines.json")}


def _env(aqi=155, temp=30.0):
    return EnvironmentalReading(aqi=aqi, pm25=60.0, temperature_c=temp, humidity_pct=70.0,
                                heatwave_alert=False, smog_episode=False, corridor="test")


@pytest.fixture
def world(tmp_path):
    shutil.copytree(REPO_DATA, tmp_path / "data", ignore=shutil.ignore_patterns("*.py"))
    storage = StorageManager(base_dir=tmp_path)
    ledger = AuditLedger(str(tmp_path / "data" / "audit_log.json"))
    domain = InventoryDomainService(storage, ledger, FACILITIES, MEDICINES)
    return storage, domain


def _plan(storage, region, env=None):
    inv, consignments, _, _ = storage.load_all(region=region)
    inbound, active_ids = committed_transfers(consignments)
    risks = SurgeEngine(FACILITIES, MEDICINES).assess_facility_risks(inv, env or _env(), inbound)
    opt = RedistributionOptimizer(FACILITIES)
    return opt.optimize(risks, inv, active_ids), opt.get_unmet_demands()


def _approve_first(storage, domain, region="lucknow"):
    recs, _ = _plan(storage, region)
    rec = recs[0]
    return rec, domain.approve_transfer_to_consignment(ApprovalRequest(recommendation_id=rec.id), rec)


def test_unmet_demand_lists_are_independent_per_region(world):
    storage, _ = world
    env = _env(aqi=420)  # severe smog so both regions have unmet demand
    inv_l, _, _, _ = storage.load_all(region="lucknow")
    inv_b, _, _, _ = storage.load_all(region="bhubaneswar")
    engine, opt = SurgeEngine(FACILITIES, MEDICINES), RedistributionOptimizer(FACILITIES)
    opt.optimize(engine.assess_facility_risks(inv_l, env), inv_l)
    lucknow = opt.get_unmet_demands()
    opt.optimize(engine.assess_facility_risks(inv_b, env), inv_b)
    assert lucknow and all(u.facility_id.startswith(("PHC-LKO", "CHC-LKO", "PHC-UNN", "CHC-UNN")) for u in lucknow)
    assert all(u.facility_id not in {x.facility_id for x in lucknow} for u in opt.get_unmet_demands())
    # the peer count is the same-region cohort, not both corridors
    region_size = sum(1 for f in FACILITIES.values() if f["district"] in ("Lucknow", "Unnao"))
    assert f"0 of {region_size - 1} peer" in lucknow[0].infeasibility_reason


def test_recommendation_ids_are_stable_and_approved_transfers_are_not_reproposed(world):
    storage, domain = world
    first, _ = _plan(storage, "lucknow")
    again, _ = _plan(storage, "lucknow")
    assert [r.id for r in first] == [r.id for r in again]

    rec, consignment = _approve_first(storage, domain)
    assert consignment.status == "APPROVED_RESERVED" and consignment.recommendation_id == rec.id
    after, _ = _plan(storage, "lucknow")
    assert rec.id not in {r.id for r in after}
    # IDs of the other proposals survive the approval
    untouched = {r.id for r in first if r.recipient_facility_id != rec.recipient_facility_id and r.donor_facility_id != rec.donor_facility_id}
    assert untouched <= {r.id for r in after}


def test_inbound_transfer_counts_toward_recipient_cover(world):
    storage, domain = world
    rec, consignment = _approve_first(storage, domain)
    inv, consignments, _, _ = storage.load_all(region="lucknow")
    inbound, _ = committed_transfers(consignments)
    assert inbound[(rec.recipient_facility_id, rec.medicine_id)] == consignment.units_requested
    engine = SurgeEngine(FACILITIES, MEDICINES)
    key = lambda r: (r.facility_id, r.medicine_id) == (rec.recipient_facility_id, rec.medicine_id)
    without = next(r for r in engine.assess_facility_risks(inv, _env()) if key(r))
    with_inbound = next(r for r in engine.assess_facility_risks(inv, _env(), inbound) if key(r))
    assert with_inbound.inbound_units == consignment.units_requested
    assert with_inbound.days_of_coverage > without.days_of_coverage
    # the need already covered is not planned a second time
    planned = sum(r.units_to_transfer for r in _plan(storage, "lucknow")[0]
                  if (r.recipient_facility_id, r.medicine_id) == (rec.recipient_facility_id, rec.medicine_id))
    assert planned < rec.units_to_transfer


def test_receipt_rejects_negative_counts_and_changed_second_receipt(world):
    storage, domain = world
    _, consignment = _approve_first(storage, domain)
    dispatched = domain.dispatch_consignment(DispatchConsignmentRequest(consignment_id=consignment.id))
    units = dispatched.units_dispatched

    with pytest.raises(ValidationError):
        ReceiveConsignmentRequest(consignment_id=consignment.id, accepted_units=units + 500, quarantined_units=-100, missing_units=-400)
    forged = ReceiveConsignmentRequest.model_construct(
        consignment_id=consignment.id, accepted_units=units + 500, quarantined_units=-100, missing_units=-400,
        operator_name="x", operator_role="PHARMACIST", condition_intact=True, discrepancy_notes=None, idempotency_key=None)
    with pytest.raises(HTTPException) as e:
        domain.receive_consignment(forged)
    assert e.value.status_code == 400

    ok = ReceiveConsignmentRequest(consignment_id=consignment.id, accepted_units=units)
    assert domain.receive_consignment(ok).status == "RECEIVED"
    assert domain.receive_consignment(ok).units_accepted == units  # same breakdown: idempotent
    with pytest.raises(HTTPException) as e:
        domain.receive_consignment(ReceiveConsignmentRequest(consignment_id=consignment.id, accepted_units=units - 10, missing_units=10))
    assert e.value.status_code == 409


def test_cancel_reservations_requires_matching_medicine(world):
    storage, domain = world
    rec, consignment = _approve_first(storage, domain)
    inv, _, _, _ = storage.load_all(region="lucknow")
    other = next(i for i in inv if i["facility_id"] == rec.donor_facility_id and i["medicine_id"] != rec.medicine_id)
    with pytest.raises(HTTPException) as e:
        domain.resolve_reconciliation_exception(ResolveReconciliationRequest(
            facility_id=rec.donor_facility_id, medicine_id=other["medicine_id"], batch_number=other["batch_number"],
            resolution_type="CANCEL_RESERVATIONS", cancelled_consignment_ids=[consignment.id], resolution_notes="test"))
    assert e.value.status_code == 400
    _, consignments, _, _ = storage.load_all(region="lucknow")
    assert consignments[consignment.id]["status"] == "APPROVED_RESERVED"


def test_unknown_batch_is_rejected_not_written_elsewhere(world):
    storage, domain = world
    inv, _, _, _ = storage.load_all(region="lucknow")
    item = inv[0]
    with pytest.raises(HTTPException) as e:
        domain.execute_stock_action(StockActionRequest(
            facility_id=item["facility_id"], medicine_id=item["medicine_id"], batch_number="TYPO-BATCH",
            action_type="PHYSICAL_COUNT", quantity=3, reason="count"))
    assert e.value.status_code == 404
    after, _, _, _ = storage.load_all(region="lucknow")
    assert after[0]["on_hand"] == item["on_hand"]


def test_stock_action_requires_a_reason(world):
    storage, domain = world
    item = storage.load_all(region="lucknow")[0][0]
    with pytest.raises(HTTPException) as e:
        domain.execute_stock_action(StockActionRequest(
            facility_id=item["facility_id"], medicine_id=item["medicine_id"], batch_number=item["batch_number"],
            action_type="PHYSICAL_COUNT", quantity=item["on_hand"], reason="   "))
    assert e.value.status_code == 400


def test_days_to_expiry_is_derived_from_expiry_date(world):
    storage, _ = world
    item = {"expiry_date": "2026-11-13", "days_to_expiry": 999}
    refresh_days_to_expiry(item, today=date(2026, 10, 24))
    assert item["days_to_expiry"] == 20
    inv, _, _, _ = storage.load_all(region="bhubaneswar")
    from app.storage import IST
    from datetime import datetime
    today = datetime.now(IST).date()
    assert all(i["days_to_expiry"] == (date.fromisoformat(i["expiry_date"]) - today).days for i in inv)
    assert all(i["days_to_expiry"] < 999 for i in inv)
    assert date.fromisoformat(inv[0]["expiry_date"]) > today - timedelta(days=1)


def test_partial_surge_categories_are_neutral_at_baseline():
    m = SurgeEngine(FACILITIES, MEDICINES).calculate_surge_multipliers(_env(aqi=60, temp=28.0))
    assert set(m.values()) == {1.0}


def test_audit_log_limit_is_clamped(tmp_path):
    ledger = AuditLedger(str(tmp_path / "ledger.json"))
    for i in range(120):
        ledger.record_entry("TEST", {"i": i})
    assert len(ledger.get_recent_entries(0)) == 1
    assert len(ledger.get_recent_entries(10_000)) == 100
