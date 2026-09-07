import os
import json
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.models import (
    Facility, Medicine, InventoryItem, EnvironmentalReading,
    StockoutRiskAssessment, TransferRecommendation, TransferConsignment,
    VoiceIntakeRequest, VoiceIntakeResponse, ApprovalRequest,
    StockActionRequest, StockActionResult, DispatchConsignmentRequest,
    ReceiveConsignmentRequest, CancelConsignmentRequest, ClinicDeskResponse,
    DailyActionItem, ResolveReconciliationRequest, ResolveReconciliationResult,
    StockMovementRegister
)
from app.storage import StorageManager, StorageError
from app.domain import InventoryDomainService
from app.surge_engine import SurgeEngine
from app.optimizer import RedistributionOptimizer
from app.voice_service import VoiceIntakeService
from app.audit_ledger import AuditLedger
from app.agent_orchestrator import MultiAgentResilienceOrchestrator

app = FastAPI(
    title="Aarogya-Vāyu API",
    description="Climate-Resilient Rural Health Supply Chain Intelligence Platform with Clinic Daily Desk",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = os.environ.get("DATA_DIR", str(BASE_DIR / "data"))
STATIC_DIR = os.environ.get("STATIC_DIR", str(BASE_DIR / "static"))
FACILITIES_PATH = os.path.join(DATA_DIR, "facilities.json")
MEDICINES_PATH = os.path.join(DATA_DIR, "medicines.json")

# In-memory reference metadata loaded from files
with open(FACILITIES_PATH, "r", encoding="utf-8") as f:
    facilities_data: List[dict] = json.load(f)
facilities_dict = {fac["id"]: fac for fac in facilities_data}

with open(MEDICINES_PATH, "r", encoding="utf-8") as f:
    medicines_data: List[dict] = json.load(f)
medicines_dict = {med["id"]: med for med in medicines_data}

# Storage boundary and audit ledger initialization
storage = StorageManager(base_dir=BASE_DIR)
audit_ledger = AuditLedger()

# Centralized domain service
domain_service = InventoryDomainService(storage, audit_ledger, facilities_dict, medicines_dict)
surge_engine = SurgeEngine(FACILITIES_PATH, MEDICINES_PATH)
optimizer = RedistributionOptimizer(facilities_dict, max_distance_km=35.0)
voice_service = VoiceIntakeService(facilities_dict, medicines_dict)
agent_orchestrator = MultiAgentResilienceOrchestrator(facilities_dict, medicines_dict, surge_engine, optimizer)

# Environmental Reading state
current_env = EnvironmentalReading(
    aqi=385,
    pm25=265.0,
    temperature_c=17.5,
    humidity_pct=78.0,
    heatwave_alert=False,
    smog_episode=True,
    corridor="Lucknow-Unnao Indo-Gangetic Smog Corridor (Severe Inversion)"
)

# Active recommendations cache
active_recommendations: Dict[str, TransferRecommendation] = {}

# Backward compatibility reference to working inventory
inventory_data, _, _, _ = storage.load_all()

def recompute_recommendations():
    global inventory_data
    inventory_data, _, _, _ = storage.load_all()
    risks = surge_engine.assess_facility_risks(inventory_data, current_env)
    recs = optimizer.optimize(risks, inventory_data)
    approved = {rid: r for rid, r in active_recommendations.items() if r.status == "APPROVED"}
    active_recommendations.clear()
    active_recommendations.update(approved)
    for r in recs:
        if r.id not in active_recommendations:
            active_recommendations[r.id] = r

# Initial computation
recompute_recommendations()

# Static files mount
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/api/facilities")
async def get_facilities():
    return facilities_data

@app.get("/api/medicines")
async def get_medicines():
    return medicines_data

@app.get("/api/system/capabilities")
async def get_system_capabilities():
    """
    Exposes safe runtime capability metadata to clients and auditors:
    - storage_backend: 'demo' (local JSON) or 'firestore' (GCP Cloud Firestore)
    - auth_mode: 'demo_role_simulation' (header/client role simulation)
    - durable_storage: True if cloud/distributed persistent storage is configured, False for ephemeral serverless /tmp
    - audit_integrity: append-only with hash-linked SHA-256 tamper-evident verification
    - concurrency_engine: describes isolation boundaries
    """
    is_firestore = (storage.backend == "firestore")
    return {
        "storage_backend": storage.backend,
        "auth_mode": "demo_role_simulation",
        "durable_storage": is_firestore,
        "ephemeral_warning": not is_firestore,
        "audit_integrity": "append-only through application operations with hash-linked SHA-256 tamper-evident verification",
        "concurrency_engine": "google.cloud.firestore.transactional (cross-instance)" if is_firestore else "process-level threading.RLock (single-instance isolated)",
        "version": "0.1.0",
        "environment": "production" if os.environ.get("VERCEL") else "development"
    }

@app.get("/api/environmental")
async def get_environmental():
    multipliers = surge_engine.calculate_surge_multipliers(current_env)
    return {
        "telemetry": current_env.model_dump(),
        "surge_multipliers": multipliers
    }

@app.post("/api/environmental")
async def update_environmental(env: EnvironmentalReading):
    global current_env
    current_env = env
    recompute_recommendations()
    audit_ledger.record_entry(
        event_type="ENVIRONMENTAL_TELEMETRY_UPDATE",
        details={
            "aqi": env.aqi,
            "smog_episode": env.smog_episode,
            "heatwave_alert": env.heatwave_alert,
            "corridor": env.corridor
        },
        approved_by="SATELLITE_FEED_AGENT"
    )
    return {"status": "updated", "telemetry": current_env}

@app.get("/api/risks")
async def get_risks():
    inv, _, _, _ = storage.load_all()
    risks = surge_engine.assess_facility_risks(inv, current_env)
    return [r.model_dump() for r in risks]

@app.get("/api/recommendations")
async def get_recommendations():
    return [r.model_dump() for r in active_recommendations.values()]

@app.post("/api/voice-intake")
async def process_voice_intake(request: VoiceIntakeRequest):
    """
    Frontline voice intake: Parses and validates clinical speech grounded to EDL-UP-2026.
    STRICT AUTHORITY BOUNDARY: Generates a DRAFT report only. Master stock is never
    mutated without explicit Pharmacist/Storekeeper confirmation on the Clinic Daily Desk.
    """
    result = await voice_service.parse_and_validate(request)
    result.is_draft = True
    result.action_taken = "DRAFT_CREATED_AWAITING_CONFIRMATION"
    result.requires_confirmation = True

    audit_ledger.record_entry(
        event_type="FRONTLINE_VOICE_DRAFT_LOGGED",
        details={
            "facility_id": result.facility_id,
            "facility_name": result.facility_name,
            "medicine_id": result.medicine_id,
            "reported_stock": result.reported_stock,
            "dispensed_yesterday": result.dispensed_yesterday,
            "detected_language": result.detected_language,
            "raw_text": request.transcript_text,
            "is_draft": True
        },
        approved_by=f"STAFF@{result.facility_id}"
    )
    return result.model_dump()

@app.post("/api/approve-transfer")
async def approve_transfer(req: ApprovalRequest):
    """
    CMO / Authorized Officer transfer approval:
    Transitions recommendation into a durable TransferConsignment (status='APPROVED_RESERVED').
    Donor available stock is reserved. Recipient inventory is NOT credited until physical receipt.
    """
    rec = active_recommendations.get(req.recommendation_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    already_approved = (rec.status == "APPROVED")
    consignment = domain_service.approve_transfer_to_consignment(req, rec)
    recompute_recommendations()

    return {
        "status": "APPROVED",
        "already_approved": already_approved,
        "consignment_id": consignment.id,
        "dispatch_challan_id": consignment.challan_id,
        "authorized_by": consignment.authorized_by,
        "timestamp": consignment.approved_at,
        "cryptographic_hash": consignment.cryptographic_hash,
        "recommendation": rec.model_dump(),
        "consignment": consignment.model_dump()
    }

# ==============================================================================
# CLINIC DAILY DESK & CONSIGNMENT LIFECYCLE ENDPOINTS
# ==============================================================================

@app.get("/api/clinic/{facility_id}/desk")
async def get_clinic_desk(facility_id: str):
    """
    Returns the facility-scoped daily workspace for the frontline pharmacist / storekeeper:
    - Facility identity & Demo role banner
    - Prioritized daily action list
    - Batch inventory with segregated balances (on_hand, reserved, quarantined, available, in_transit)
    - Active inbound consignments awaiting physical inspection
    - Active outbound consignments awaiting packaging and dispatch
    - Reconciliation exceptions on frozen batches
    """
    fac = facilities_dict.get(facility_id) or {
        "id": facility_id,
        "name": f"Clinic {facility_id}",
        "district": "Lucknow",
        "type": "PHC",
        "lat": 26.85,
        "lng": 80.95,
        "population_served": 20000,
        "beds": 6,
        "cold_storage": True,
        "doctor": "Medical Officer On Duty"
    }

    actions = domain_service.get_facility_action_items(facility_id)
    inv = domain_service.get_facility_inventory(facility_id)
    
    _, consignments, _, _ = storage.load_all()
    inbound = [c for c in consignments.values() if c.get("recipient_facility_id") == facility_id]
    outbound = [c for c in consignments.values() if c.get("donor_facility_id") == facility_id]
    recon_exceptions = [i for i in inv if i.get("is_frozen", False)]

    return ClinicDeskResponse(
        facility=Facility(**fac),
        operator_role_mode="DEMO_ROLE_SIMULATION",
        action_items=actions,
        inventory=inv,
        inbound_consignments=inbound,
        outbound_consignments=outbound,
        active_reconciliation_exceptions=recon_exceptions
    )

@app.post("/api/clinic/{facility_id}/stock-action")
async def execute_clinic_stock_action(facility_id: str, req: StockActionRequest):
    """
    Executes a structured, verified daily stock action:
    - PHYSICAL_COUNT: sets on_hand; flags exception if below commitments.
    - STOCK_RECEIVED: increments on_hand.
    - STOCK_ISSUED: decrements on_hand; verifies available stock.
    - QUARANTINE_DAMAGED: segregates damaged units into quarantine.
    """
    if req.facility_id != facility_id:
        raise HTTPException(status_code=400, detail="Mismatched facility ID between URL and request payload.")
    result = domain_service.execute_stock_action(req)
    recompute_recommendations()
    return result

@app.post("/api/clinic/{facility_id}/resolve-reconciliation")
async def resolve_clinic_reconciliation(facility_id: str, req: ResolveReconciliationRequest):
    """
    MOIC / Supervisor Reconciliation Resolution:
    - Resolves over-commitment exception when physical count is below active reservations.
    - Options: SUPERVISOR_RECOUNT, CANCEL_RESERVATIONS, ADJUST_QUARANTINE.
    - Unfreezes batch once on_hand >= reserved + quarantined.
    """
    if req.facility_id != facility_id:
        raise HTTPException(status_code=400, detail="Mismatched facility ID between URL and request payload.")
    result = domain_service.resolve_reconciliation_exception(req)
    recompute_recommendations()
    return result

@app.get("/api/clinic/{facility_id}/stock-register")
async def get_clinic_stock_register(facility_id: str, medicine_id: str, batch_number: Optional[str] = None):
    """
    Per-medicine, per-batch operational stock movement register.
    Answers: 'Yesterday we had 120 units. Why are only 75 available today?'
    Outputs printable/exportable handover register with complete chronological deltas.
    Compliance note: Operational Working Register • Pre-validation e-Aushadhi / Form 16 Working Format.
    """
    return domain_service.get_stock_movement_register(facility_id, medicine_id, batch_number)

@app.post("/api/transfer/dispatch")
async def dispatch_consignment(req: DispatchConsignmentRequest):
    """
    Dispatches an approved consignment:
    - Donor physical on_hand drops by Q; donor reservation clears.
    - Recipient in_transit increases by Q; recipient available remains unchanged.
    """
    consignment = domain_service.dispatch_consignment(req)
    recompute_recommendations()
    return consignment

@app.post("/api/transfer/receive")
async def receive_consignment(req: ReceiveConsignmentRequest):
    """
    Single final receipt per consignment:
    - Validates invariant: Q_dispatched = accepted + quarantined + missing.
    - Recipient on_hand += accepted + quarantined.
    - Recipient quarantined += quarantined.
    - Newly available is strictly accepted units.
    - Missing units sealed as discrepancy in SHA-256 ledger.
    """
    consignment = domain_service.receive_consignment(req)
    recompute_recommendations()
    return consignment

@app.post("/api/transfer/cancel")
async def cancel_consignment(req: CancelConsignmentRequest):
    """
    Cancels an approved transfer prior to dispatch and releases the donor's reserved stock.
    """
    consignment = domain_service.cancel_consignment(req)
    recompute_recommendations()
    return consignment

@app.get("/api/consignments")
async def get_all_consignments():
    _, consignments, _, _ = storage.load_all()
    return list(consignments.values())

@app.get("/api/audit-log")
async def get_audit_log(limit: int = 15):
    return audit_ledger.get_recent_entries(limit=limit)

@app.get("/api/audit-log/verify")
async def verify_audit_ledger():
    return audit_ledger.verify_chain_integrity()

@app.post("/api/agents/run-resilience-pipeline")
async def run_resilience_pipeline(payload: Dict[str, Any] = Body(default={})):
    target_phc = payload.get("target_facility_id", "PHC-LKO-01")
    snippet = payload.get("voice_snippet", None)
    inv, _, _, _ = storage.load_all()
    result = agent_orchestrator.run_pipeline(current_env, inv, target_phc, snippet)
    recompute_recommendations()
    audit_ledger.record_entry(
        event_type="MULTI_AGENT_PIPELINE_RUN",
        details={
            "target_facility": target_phc,
            "status": result.get("status")
        },
        approved_by="GOOGLE_ADK_ORCHESTRATOR"
    )
    return result

@app.post("/api/agents/run")
async def run_agents_alias(payload: Dict[str, Any] = Body(default={})):
    return await run_resilience_pipeline(payload)

@app.post("/api/cmo/chat")
async def cmo_chat(payload: Dict[str, Any] = Body(...)):
    question = payload.get("question", "")
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")
    inv, _, _, _ = storage.load_all()
    response = agent_orchestrator.query_strategic_insight(question, current_env, inv)
    audit_ledger.record_entry(
        event_type="CMO_STRATEGIC_QUERY",
        details={"question": question, "query_type": response.get("query_type")},
        approved_by="DR_SAXENA_CMO"
    )
    return response

@app.post("/api/vision/verify-shelf-photo")
async def verify_shelf_photo(payload: Dict[str, Any] = Body(...)):
    """
    Gemini Multimodal Vision Simulation for medicine shelf inspection.
    EXPLICIT STATUS: Simulated computer vision evidence for demo purposes.
    It does not certify physical stock counts nor authorize automatic stock writes.
    """
    image_name = payload.get("image_name", "phc_kakori_shelf_01.jpg")
    facility_id = payload.get("facility_id", "PHC-LKO-01")
    reported_count = payload.get("reported_count", 15)

    detected_medicines = [
        {
            "brand": "Asthalin Respirator Solution (Salbutamol 2.5mg)",
            "batch_number": "BAT-842-26",
            "expiry_ocr": "NOV 2026",
            "days_to_expiry": 74,
            "visual_unit_estimate": 16,
            "packaging_condition": "Sealed ampoule strips",
            "confidence": 0.96
        },
        {
            "brand": "Electral ORS (WHO Formula)",
            "batch_number": "BAT-ORS-19",
            "expiry_ocr": "AUG 2027",
            "days_to_expiry": 340,
            "visual_unit_estimate": 120,
            "packaging_condition": "Intact foil sachets",
            "confidence": 0.98
        }
    ]

    target_item = detected_medicines[0]
    discrepancy = abs(target_item["visual_unit_estimate"] - reported_count)
    discrepancy_pct = round((discrepancy / reported_count) * 100, 1) if reported_count > 0 else 0
    verification_status = "VERIFIED_MATCH" if discrepancy <= 3 else "DISCREPANCY_FLAGGED"

    audit_ledger.record_entry(
        event_type="SHELF_PHOTO_VISION_VERIFICATION",
        details={
            "facility_id": facility_id,
            "visual_count": target_item["visual_unit_estimate"],
            "reported_count": reported_count,
            "status": verification_status,
            "batch_ocr": target_item["batch_number"],
            "expiry_ocr": target_item["expiry_ocr"],
            "is_simulated": True
        },
        approved_by="GEMINI_VISION_AGENT"
    )

    return {
        "status": verification_status,
        "facility_id": facility_id,
        "image_analyzed": image_name,
        "detected_items": detected_medicines,
        "visual_count": target_item["visual_unit_estimate"],
        "reported_count": reported_count,
        "discrepancy_units": discrepancy,
        "discrepancy_pct": discrepancy_pct,
        "ocr_batch": target_item["batch_number"],
        "ocr_expiry": target_item["expiry_ocr"],
        "is_simulated": True,
        "certified": False,
        "human_review_required": True,
        "disclaimer": "Simulated computer vision evidence. Physical verification and confirmation by staff pharmacist required before stock mutation.",
        "verification_summary": (
            f"[Simulated Vision Telemetry] Detected approximately {target_item['visual_unit_estimate']} units of Salbutamol (Batch: {target_item['batch_number']}). "
            f"Advisory evidence only; physical verification required."
        )
    }
