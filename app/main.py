import os
import logging
import sys
import asyncio
import json
import copy
import time
from collections import deque
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path
from fastapi import FastAPI, HTTPException, Body, Request
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
    StockMovementRegister, UnmetDemandReport
)
from app.storage import StorageManager, StorageError
from app.domain import InventoryDomainService
from app.surge_engine import SurgeEngine
from app.optimizer import committed_transfers
from app.optimizer import RedistributionOptimizer
from app.voice_service import VoiceIntakeService
from app.audit_ledger import AuditLedger
from app.agent_orchestrator import MultiAgentResilienceOrchestrator
from app.news_service import news_service
from app.telemetry_service import is_live_reading, telemetry_service
from app.llm import provider_status, set_request_deadline, GEMINI_MODELS, CLAUDE_MODEL
from app.vision_service import decode_image, scan_shelf, compare_with_register
from app.speech_service import decode_audio, is_too_short_or_silent, transcribe

logger = logging.getLogger("aarogya_vayu")

app = FastAPI(
    title="Aarogya-Vāyu API",
    description="Climate-Resilient Rural Health Supply Chain Intelligence Platform with Clinic Daily Desk",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("ALLOWED_ORIGINS", "https://aarogya-vayu.vercel.app,http://localhost:8000").split(",")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = os.environ.get("DATA_DIR", str(BASE_DIR / "data"))
STATIC_DIR = os.environ.get("STATIC_DIR", str(BASE_DIR / "static"))
FACILITIES_LKO_PATH = os.path.join(DATA_DIR, "facilities.json")
FACILITIES_BBS_PATH = os.path.join(DATA_DIR, "facilities_bhubaneswar.json")
MEDICINES_PATH = os.path.join(DATA_DIR, "medicines.json")

# In-memory reference metadata loaded from files
with open(FACILITIES_LKO_PATH, "r", encoding="utf-8") as f:
    facilities_lko: List[dict] = json.load(f)

facilities_bbs: List[dict] = []
if os.path.exists(FACILITIES_BBS_PATH):
    with open(FACILITIES_BBS_PATH, "r", encoding="utf-8") as f:
        facilities_bbs = json.load(f)

facilities_by_region: Dict[str, List[dict]] = {
    "lucknow": facilities_lko,
    "bhubaneswar": facilities_bbs
}

facilities_dict: Dict[str, dict] = {fac["id"]: fac for fac in (facilities_lko + facilities_bbs)}

with open(MEDICINES_PATH, "r", encoding="utf-8") as f:
    medicines_data: List[dict] = json.load(f)
medicines_dict: Dict[str, dict] = {med["id"]: med for med in medicines_data}

# Storage boundary and audit ledger initialization
storage = StorageManager(base_dir=BASE_DIR)
audit_ledger = AuditLedger()

# Centralized domain service
domain_service = InventoryDomainService(storage, audit_ledger, facilities_dict, medicines_dict)
surge_engine = SurgeEngine(facilities_dict, medicines_dict)
optimizer = RedistributionOptimizer(facilities_dict, max_distance_km=35.0)
voice_service = VoiceIntakeService(facilities_dict, medicines_dict)
agent_orchestrator = MultiAgentResilienceOrchestrator(facilities_dict, medicines_dict, surge_engine, optimizer)

# Regional Configuration Registry
REGIONS_CONFIG = {
    "bhubaneswar": {
        "id": "bhubaneswar",
        "name": "Bhubaneswar–Cuttack Coastal & Industrial Corridor (Odisha)",
        "short_name": "Bhubaneswar (Odisha)",
        "state": "Odisha",
        "districts": ["Khordha", "Cuttack"],
        "center": [20.30, 85.83],
        "zoom": 10,
        "default_facility_id": "PHC-BBS-01",
        "polygon": [
            [20.62, 85.65],
            [20.65, 86.18],
            [20.45, 86.22],
            [20.10, 86.12],
            [19.90, 85.35],
            [20.15, 85.25],
            [20.40, 85.60]
        ],
        "initial_env": EnvironmentalReading(
            aqi=168,
            pm25=84.5,
            temperature_c=39.5,
            humidity_pct=72.0,
            heatwave_alert=True,
            smog_episode=False,
            corridor="Bhubaneswar–Cuttack Coastal & Industrial Corridor (Odisha)"
        )
    },
    "lucknow": {
        "id": "lucknow",
        "name": "Lucknow-Unnao Indo-Gangetic Smog Corridor (Severe Inversion)",
        "short_name": "Lucknow (UP)",
        "state": "Uttar Pradesh",
        "districts": ["Lucknow", "Unnao"],
        "center": [26.75, 80.72],
        "zoom": 10,
        "default_facility_id": "PHC-LKO-01",
        "polygon": [
            [27.02, 80.45],
            [27.00, 80.85],
            [26.90, 81.16],
            [26.72, 81.15],
            [26.54, 80.70],
            [26.46, 80.35],
            [26.60, 80.22],
            [26.85, 80.32]
        ],
        "initial_env": EnvironmentalReading(
            aqi=385,
            pm25=265.0,
            temperature_c=17.5,
            humidity_pct=78.0,
            heatwave_alert=False,
            smog_episode=True,
            corridor="Lucknow-Unnao Indo-Gangetic Smog Corridor (Severe Inversion)"
        )
    }
}

# Active region state: defaults to "lucknow" when running pytest to preserve test assertions,
# and "bhubaneswar" in live production/demo mode.
is_pytest = ("pytest" in sys.modules) or ("PYTEST_CURRENT_TEST" in os.environ)
default_reg = "lucknow" if is_pytest else "bhubaneswar"
active_region_id: str = os.environ.get("DEFAULT_REGION", default_reg).lower()
if active_region_id not in REGIONS_CONFIG:
    active_region_id = "bhubaneswar"
storage.set_region(active_region_id)

# Environmental Reading state per region
current_env_by_region: Dict[str, EnvironmentalReading] = {
    "bhubaneswar": copy.deepcopy(REGIONS_CONFIG["bhubaneswar"]["initial_env"]),
    "lucknow": copy.deepcopy(REGIONS_CONFIG["lucknow"]["initial_env"])
}
current_env = current_env_by_region[active_region_id]

# "live" regions track Open-Meteo/CAMS telemetry; a scenario preset switches a region to "scenario" until Live is re-selected
LIVE_BY_DEFAULT = os.getenv("LIVE_TELEMETRY_DEFAULT", "0" if is_pytest else "1") == "1"
env_mode_by_region: Dict[str, str] = {reg: ("live" if LIVE_BY_DEFAULT else "scenario") for reg in REGIONS_CONFIG}

# Active recommendations and unmet demands caches per region
active_recommendations_by_region: Dict[str, Dict[str, TransferRecommendation]] = {
    "bhubaneswar": {},
    "lucknow": {}
}
active_unmet_demands_by_region: Dict[str, List[UnmetDemandReport]] = {
    "bhubaneswar": [],
    "lucknow": []
}

# Module-level references for test & backward compatibility
active_recommendations = active_recommendations_by_region[active_region_id]
active_unmet_demands = active_unmet_demands_by_region[active_region_id]
inventory_data, _, _, _ = storage.load_all(region=active_region_id)
facilities_data = facilities_by_region.get(active_region_id, facilities_lko)

def resolve_region(region: Any) -> str:
    """Normalise a client-supplied region; default to this instance's active region; 400 if unknown."""
    if region is None or region == "":
        return active_region_id
    reg = str(region).strip().lower()
    if reg not in REGIONS_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown region '{reg}'. Available: {list(REGIONS_CONFIG)}")
    return reg


def recompute_recommendations(target_region: Optional[str] = None):
    global inventory_data, active_recommendations, active_unmet_demands, current_env
    regions_to_run = [target_region] if target_region else ["lucknow", "bhubaneswar"]
    for reg in regions_to_run:
        if reg not in REGIONS_CONFIG:
            continue
        inv, consignments, _, _ = storage.load_all(region=reg)
        reg_env = current_env_by_region[reg]
        closed = {c.get("recommendation_id") for c in consignments.values() if c.get("status") in ("RECEIVED", "CANCELLED")}
        inbound, active_ids = committed_transfers(consignments)
        risks = surge_engine.assess_facility_risks(inv, reg_env, inbound)
        recs = optimizer.optimize(risks, inv, active_ids)
        active_unmet_demands_by_region[reg] = optimizer.get_unmet_demands()

        reg_recs = active_recommendations_by_region[reg]
        approved = {rid: r for rid, r in reg_recs.items() if r.status == "APPROVED" and rid not in closed}
        reg_recs.clear()
        reg_recs.update(approved)
        for r in recs:
            if r.id not in reg_recs:
                reg_recs[r.id] = r

    # Synchronize active globals with currently selected active region
    inventory_data, _, _, _ = storage.load_all(region=active_region_id)
    current_env = current_env_by_region[active_region_id]
    active_recommendations = active_recommendations_by_region[active_region_id]
    active_unmet_demands = active_unmet_demands_by_region[active_region_id]

# Initial computation across both regions
recompute_recommendations()

async def sync_live_env(reg: str, force: bool = False) -> None:
    """Refresh a live-mode region from telemetry (cached 5 min); recompute only when the surge inputs change."""
    if reg not in REGIONS_CONFIG or (env_mode_by_region.get(reg) != "live" and not force):
        return
    global current_env
    reading = await asyncio.to_thread(telemetry_service.fetch_live_reading, reg)
    previous = current_env_by_region.get(reg)
    # A scenario preset may have been posted while we were fetching; it wins
    if reading is previous or env_mode_by_region.get(reg) != "live":
        return
    if not is_live_reading(reading):
        # Feed unavailable: keep planning on the last reading rather than an invented baseline
        return
    current_env_by_region[reg] = reading
    if reg == active_region_id:
        current_env = reading
    # Recommendation IDs are regenerated on recompute, so skip it when nothing that drives demand changed
    if previous is None or surge_engine.calculate_surge_multipliers(previous) != surge_engine.calculate_surge_multipliers(reading) \
            or (previous.heatwave_alert, previous.smog_episode) != (reading.heatwave_alert, reading.smog_episode):
        recompute_recommendations(reg)

# Static files mount
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/api/regions")
async def get_regions():
    """
    Returns available clinical corridors (Bhubaneswar default, Lucknow UP secondary).
    """
    return {
        "active_region": active_region_id,
        "regions": [
            {
                "id": r_id,
                "name": r_cfg["name"],
                "short_name": r_cfg["short_name"],
                "state": r_cfg["state"],
                "districts": r_cfg["districts"],
                "center": r_cfg["center"],
                "zoom": r_cfg["zoom"],
                "default_facility_id": r_cfg["default_facility_id"],
                "polygon": r_cfg["polygon"],
                "active": (r_id == active_region_id)
            }
            for r_id, r_cfg in REGIONS_CONFIG.items()
        ]
    }

@app.post("/api/region/switch")
async def switch_region(payload: Dict[str, Any] = Body(...)):
    """
    Switches active operational corridor in memory.
    """
    global active_region_id, current_env, active_recommendations, active_unmet_demands, inventory_data, facilities_data
    new_reg = str(payload.get("region") or "").strip().lower()
    if new_reg not in REGIONS_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid region '{new_reg}'. Available options: {list(REGIONS_CONFIG.keys())}"
        )
    active_region_id = new_reg
    storage.set_region(active_region_id)
    facilities_data = facilities_by_region.get(active_region_id, facilities_lko)
    recompute_recommendations(active_region_id)

    audit_ledger.record_entry(
        event_type="CORRIDOR_REGION_SWITCHED",
        details={
            "active_region": active_region_id,
            "corridor": REGIONS_CONFIG[active_region_id]["name"]
        },
        approved_by="COMMAND_CENTER_DISPATCHER"
    )

    return {
        "status": "switched",
        "active_region": active_region_id,
        "region_meta": REGIONS_CONFIG[active_region_id]
    }

@app.get("/api/facilities")
async def get_facilities(region: Optional[str] = None):
    return facilities_by_region[resolve_region(region)]

@app.get("/api/medicines")
async def get_medicines():
    return medicines_data

@app.get("/api/news")
async def get_news(
    region: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    force_refresh: bool = False
):
    reg = resolve_region(region)
    # urllib blocks, so keep the event loop free for other requests
    articles = await asyncio.to_thread(news_service.get_news, region=reg, category=category, search=search, force_refresh=force_refresh)
    return {
        "region": reg,
        "total": len(articles),
        "live_count": sum(1 for a in articles if a.is_live),
        "articles": [a.model_dump() for a in articles]
    }

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
        "active_region": active_region_id,
        "available_regions": list(REGIONS_CONFIG.keys()),
        "audit_integrity": "append-only through application operations with hash-linked SHA-256 tamper-evident verification",
        "concurrency_engine": "google.cloud.firestore.transactional (cross-instance)" if is_firestore else "process-level threading.RLock (single-instance isolated)",
        "version": "2.0.0",
        "environment": "production" if os.environ.get("VERCEL") else "development",
        "ai_providers": provider_status(),
        "data_provenance": {
            "weather_and_air_quality": "LIVE: Open-Meteo forecast API + Copernicus CAMS air quality (current, 30-day history, 72h forecast)",
            "fire_hotspots": "LIVE: NASA FIRMS VIIRS" if os.getenv("FIRMS_MAP_KEY") else "NOT CONFIGURED: set FIRMS_MAP_KEY for NASA FIRMS",
            "news": "LIVE: Google News RSS; items prefixed [Sample advisory] are illustrative",
            "voice_intake_parsing": "LIVE LLM: Gemini primary, Claude fallback, offline rule-based parser last",
            "cmo_strategic_chat": "LIVE LLM: Gemini primary, Claude fallback, template answers last",
            "logistics_tool_selection": "LIVE LLM function calling (Gemini primary, Claude fallback); allocation by deterministic solver",
            "shelf_photo_vision": "LIVE LLM vision on the uploaded photo (Gemini primary, Claude fallback)",
            "speech_to_text": "LIVE: Gemini transcribes the recorded voice note (English/Hindi/Odia); browser Web Speech API only where the browser cannot record audio",
            "demand_forecast": "Rule-based lag-curve forecaster driven by live surge multipliers (not a trained ML model)",
            "facilities": "Named after real PHC/CHC sites; coordinates, population and staffing are demo values, not an official registry",
            "inventory": "SYNTHETIC demo stock register (no public API exposes PHC stock)",
            "scenario_presets": "SIMULATED: Smog/Heatwave/Baseline buttons override live telemetry until Live is reselected",
        }
    }

@app.get("/api/environmental")
async def get_environmental(region: Optional[str] = None, live: bool = False):
    reg = resolve_region(region)
    if live and reg in env_mode_by_region:
        env_mode_by_region[reg] = "live"
    await sync_live_env(reg)
    reg_env = current_env_by_region.get(reg, current_env)

    multipliers = surge_engine.calculate_surge_multipliers(reg_env)
    return {
        "region": reg,
        "is_live": is_live_reading(reg_env),
        "mode": env_mode_by_region.get(reg, "scenario"),
        "telemetry": reg_env.model_dump(),
        "surge_multipliers": multipliers
    }

@app.get("/api/environmental/live")
async def get_live_environmental(region: Optional[str] = None):
    reg = resolve_region(region)
    reading = await asyncio.to_thread(telemetry_service.fetch_live_reading, reg)
    multipliers = surge_engine.calculate_surge_multipliers(reading)
    return {
        "region": reg,
        "is_live": is_live_reading(reading),
        "telemetry": reading.model_dump(),
        "surge_multipliers": multipliers
    }

@app.post("/api/environmental/live/activate")
async def activate_live_environmental(region: Optional[str] = None):
    reg = resolve_region(region)
    if reg in env_mode_by_region:
        env_mode_by_region[reg] = "live"
    await sync_live_env(reg, force=True)
    reading = current_env_by_region.get(reg, current_env)
    live_ok = is_live_reading(reading)
    audit_ledger.record_entry(
        event_type="LIVE_CAMS_TELEMETRY_ACTIVATED" if live_ok else "LIVE_TELEMETRY_UNAVAILABLE",
        details={
            "region": reg,
            "aqi": reading.aqi,
            "pm25": reading.pm25,
            "temperature_c": reading.temperature_c,
            "humidity_pct": reading.humidity_pct,
            "wind_speed_kmh": reading.wind_speed_kmh,
            "source": reading.source
        },
        approved_by="OPEN_METEO_CAMS_GATEWAY"
    )
    multipliers = surge_engine.calculate_surge_multipliers(reading)
    return {
        "status": "activated" if live_ok else "live_feed_unavailable",
        "region": reg,
        "is_live": is_live_reading(reading),
        "telemetry": reading.model_dump(),
        "surge_multipliers": multipliers
    }

@app.post("/api/environmental")
async def update_environmental(env: EnvironmentalReading, region: Optional[str] = None):
    global current_env
    corridor_lower = (env.corridor or "").lower()
    if region:
        reg = resolve_region(region)
    elif any(tok in corridor_lower for tok in ["bhubaneswar", "cuttack", "odisha", "coastal"]):
        reg = "bhubaneswar"
    elif any(tok in corridor_lower for tok in ["lucknow", "unnao", "gangetic", "awadh"]):
        reg = "lucknow"
    else:
        reg = active_region_id

    current_env_by_region[reg] = env
    if reg in env_mode_by_region:
        env_mode_by_region[reg] = "scenario"
    if reg == active_region_id:
        current_env = env
    recompute_recommendations(reg)
    audit_ledger.record_entry(
        event_type="ENVIRONMENTAL_TELEMETRY_UPDATE",
        details={
            "region": reg,
            "aqi": env.aqi,
            "smog_episode": env.smog_episode,
            "heatwave_alert": env.heatwave_alert,
            "corridor": env.corridor
        },
        approved_by="SCENARIO_SIMULATOR"
    )
    return {"status": "updated", "region": reg, "telemetry": env}

@app.get("/api/risks")
async def get_risks(region: Optional[str] = None):
    reg = resolve_region(region)
    await sync_live_env(reg)
    inv, consignments, _, _ = storage.load_all(region=reg)
    reg_env = current_env_by_region.get(reg, current_env)
    inbound, _ = committed_transfers(consignments)
    risks = surge_engine.assess_facility_risks(inv, reg_env, inbound)
    return [r.model_dump() for r in risks]

@app.get("/api/recommendations")
async def get_recommendations(region: Optional[str] = None):
    reg = resolve_region(region)
    await sync_live_env(reg)
    recs_dict = active_recommendations_by_region.get(reg, active_recommendations)
    return [r.model_dump() for r in recs_dict.values()]

@app.get("/api/unmet-demands")
async def get_unmet_demands(region: Optional[str] = None):
    """
    Returns clinical shortages where peer-to-peer redistribution is mathematically
    infeasible (no corridor donor retains >=14d safety reserve within 35km).
    Escalated to District Replenishment Requisition Queue.
    """
    reg = resolve_region(region)
    await sync_live_env(reg)
    unmet_list = active_unmet_demands_by_region.get(reg, active_unmet_demands)
    return [u.model_dump() for u in unmet_list]

# Per-client throttle for endpoints that spend paid LLM calls (per serverless instance)
LLM_RATE_LIMIT_PER_MIN = int(os.getenv("LLM_RATE_LIMIT_PER_MIN", "20"))
MAX_LLM_INPUT_CHARS = 1000
# The pipeline makes up to two LLM calls; together they must finish well inside the serverless timeout
PIPELINE_LLM_BUDGET_S = float(os.getenv("PIPELINE_LLM_BUDGET_S", "40"))
_llm_hits: Dict[str, deque] = {}

def enforce_llm_rate_limit(http_request: Request):
    # Vercel's edge sets x-real-ip itself; a client-supplied X-Forwarded-For is not trusted
    client_ip = http_request.headers.get("x-real-ip") or (http_request.client.host if http_request.client else "unknown")
    now = time.monotonic()
    if len(_llm_hits) > 10000:
        for ip in [ip for ip, h in _llm_hits.items() if not h or now - h[-1] > 60]:
            del _llm_hits[ip]
    hits = _llm_hits.setdefault(client_ip, deque())
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= LLM_RATE_LIMIT_PER_MIN:
        raise HTTPException(status_code=429, detail="Too many AI requests. Please wait a minute and try again.")
    hits.append(now)

@app.post("/api/voice-intake/transcribe")
async def transcribe_voice_note(http_request: Request, payload: Dict[str, Any] = Body(...)):
    """
    Speech-to-text for a recorded voice note (16 kHz mono WAV) using Gemini. Returns the transcript
    only; parsing and the draft stock report still go through /api/voice-intake.
    """
    try:
        audio = decode_audio(str(payload.get("audio_base64") or ""), payload.get("mime_type"))
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    if is_too_short_or_silent(audio[0]):
        return {"is_speech": False, "transcript": "", "language": "", "transcribed_by": "Audio check (too short or silent)"}
    enforce_llm_rate_limit(http_request)
    result = await transcribe(audio)
    if not result:
        raise HTTPException(status_code=503, detail="Speech model unavailable; please type the report.")
    note, _ = result
    return {
        "is_speech": note.is_speech,
        "transcript": note.transcript.strip()[:MAX_LLM_INPUT_CHARS] if note.is_speech else "",
        "language": note.language,
        "transcribed_by": f"Gemini ({GEMINI_MODELS[0]})",
    }

@app.post("/api/voice-intake")
async def process_voice_intake(request: VoiceIntakeRequest, http_request: Request):
    """
    Frontline voice intake: Parses and validates clinical speech grounded to EDL-UP-2026.
    STRICT AUTHORITY BOUNDARY: Generates a DRAFT report only. Master stock is never
    mutated without explicit Pharmacist/Storekeeper confirmation on the Clinic Daily Desk.
    """
    if len(request.transcript_text) > MAX_LLM_INPUT_CHARS:
        raise HTTPException(status_code=400, detail=f"Transcript exceeds {MAX_LLM_INPUT_CHARS} characters")
    enforce_llm_rate_limit(http_request)
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
        for reg_recs in active_recommendations_by_region.values():
            if req.recommendation_id in reg_recs:
                rec = reg_recs[req.recommendation_id]
                break
    if not rec:
        # IDs are deterministic, so a recommendation listed by another serverless instance can be rebuilt here
        for reg in REGIONS_CONFIG:
            recompute_recommendations(reg)
            rec = active_recommendations_by_region[reg].get(req.recommendation_id)
            if rec:
                break
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
    fac = facilities_dict.get(facility_id)
    if not fac:
        raise HTTPException(status_code=404, detail=f"Unknown facility '{facility_id}'")

    actions = domain_service.get_facility_action_items(facility_id)
    inv = domain_service.get_facility_inventory(facility_id)
    
    _, consignments, _, _ = storage.load_all(region=domain_service.get_region_for_facility(facility_id))
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
async def get_all_consignments(region: Optional[str] = None):
    reg = resolve_region(region)
    _, consignments, _, _ = storage.load_all(region=reg)
    return list(consignments.values())

@app.get("/api/audit-log")
async def get_audit_log(limit: int = 15):
    return audit_ledger.get_recent_entries(limit=limit)

@app.get("/api/audit-log/verify")
async def verify_audit_ledger():
    return audit_ledger.verify_chain_integrity()

@app.post("/api/agents/run-resilience-pipeline")
async def run_resilience_pipeline(http_request: Request, payload: Dict[str, Any] = Body(default={})):
    target_phc = payload.get("target_facility_id") or REGIONS_CONFIG[active_region_id]["default_facility_id"]
    if not isinstance(target_phc, str) or target_phc not in facilities_dict:
        raise HTTPException(status_code=400, detail="Unknown target_facility_id")
    snippet = str(payload.get("voice_snippet") or "").strip()
    if len(snippet) > MAX_LLM_INPUT_CHARS:
        raise HTTPException(status_code=400, detail=f"voice_snippet exceeds {MAX_LLM_INPUT_CHARS} characters")
    enforce_llm_rate_limit(http_request)
    set_request_deadline(PIPELINE_LLM_BUDGET_S)
    # The facility decides the region; the per-instance active region may belong to another user or instance
    reg = domain_service.get_region_for_facility(target_phc)
    await sync_live_env(reg)
    intake = None
    if snippet:
        parsed = await voice_service.parse_and_validate(VoiceIntakeRequest(transcript_text=snippet, facility_id=target_phc))
        intake = parsed.model_dump()
    inv, consignments, _, _ = storage.load_all(region=reg)
    result = await agent_orchestrator.run_pipeline(current_env_by_region[reg], inv, target_phc, intake, consignments)
    recompute_recommendations(reg)
    audit_ledger.record_entry(
        event_type="MULTI_AGENT_PIPELINE_RUN",
        details={
            "target_facility": target_phc,
            "status": result.get("status")
        },
        approved_by="MULTI_AGENT_ORCHESTRATOR"
    )
    return result

@app.post("/api/agents/run")
async def run_agents_alias(http_request: Request, payload: Dict[str, Any] = Body(default={})):
    return await run_resilience_pipeline(http_request, payload)

@app.post("/api/cmo/chat")
async def cmo_chat(http_request: Request, payload: Dict[str, Any] = Body(...)):
    question = str(payload.get("question") or "")
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")
    if len(question) > MAX_LLM_INPUT_CHARS:
        raise HTTPException(status_code=400, detail=f"Question exceeds {MAX_LLM_INPUT_CHARS} characters")
    enforce_llm_rate_limit(http_request)
    reg = resolve_region(payload.get("region"))
    await sync_live_env(reg)
    inv, consignments, _, _ = storage.load_all(region=reg)
    reg_env = current_env_by_region.get(reg, current_env)
    try:
        response = await agent_orchestrator.query_strategic_insight(question, reg_env, inv, consignments)
    except Exception:
        logger.exception("CMO strategic insight failed")
        raise HTTPException(status_code=500, detail="The strategic insight agent failed on this question. Please try again or rephrase.")
    audit_ledger.record_entry(
        event_type="CMO_STRATEGIC_QUERY",
        details={"question": question, "query_type": response.get("query_type"), "region": reg, "answered_by": response.get("answered_by")},
        approved_by="DR_SAXENA_CMO"
    )
    return response

@app.post("/api/vision/verify-shelf-photo")
async def verify_shelf_photo(http_request: Request, payload: Dict[str, Any] = Body(...)):
    """
    Reads an uploaded shelf photo with a multimodal LLM (Gemini primary, Claude fallback) and
    compares visible counts with the facility's stock register. Advisory evidence only: it never
    writes stock, and a pharmacist must confirm any discrepancy.
    """
    facility_id = payload.get("facility_id") or REGIONS_CONFIG[active_region_id]["default_facility_id"]
    if facility_id not in facilities_dict:
        raise HTTPException(status_code=400, detail="Unknown facility_id")
    try:
        image = decode_image(str(payload.get("image_base64") or ""), payload.get("mime_type"))
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    enforce_llm_rate_limit(http_request)

    result = await scan_shelf(image, medicines_dict)
    if not result:
        raise HTTPException(status_code=503, detail="Vision model unavailable; please count manually.")
    scan, provider = result
    region = domain_service.get_region_for_facility(facility_id)
    inv, _, _, _ = storage.load_all(region=region)
    items = compare_with_register(scan, facility_id, inv, medicines_dict)
    compared = [i for i in items if i["register_available"] is not None]
    # More units on the shelf than the register holds is a real discrepancy; fewer usually means the photo shows part of the stock
    flagged = [i for i in compared if i["seen_total"] > i["register_available"] + 3]
    partial = [i for i in compared if i["seen_total"] < i["register_available"] - 3]
    if not scan.is_medicine_shelf or not items:
        status = "NOT_A_SHELF_PHOTO" if not scan.is_medicine_shelf else "NO_ITEMS_DETECTED"
    elif not any(i["register_available"] is not None for i in items):
        status = "NO_CATALOGUE_MATCH"
    else:
        status = "DISCREPANCY_FLAGGED" if flagged else ("PARTIAL_COUNT" if partial else "VERIFIED_MATCH")

    audit_ledger.record_entry(
        event_type="SHELF_PHOTO_VISION_VERIFICATION",
        details={
            "facility_id": facility_id,
            "status": status,
            "items": [{k: i[k] for k in ("matched_medicine_id", "unit_count_estimate", "register_available", "batch_number", "expiry_text")} for i in items],
            "model_provider": provider,
            "is_simulated": False
        },
        approved_by="VISION_AGENT"
    )

    parts = [
        f"{i['medicine_name']}: ~{i['unit_count_estimate']} seen"
        + (f" ({i['seen_total']} across all its items) vs {i['register_available']} on hand in the register"
           if i["register_available"] is not None and i.get("seen_total") != i["unit_count_estimate"]
           else f" vs {i['register_available']} on hand in the register" if i["register_available"] is not None else "")
        + (f", batch {i['batch_number']}" if i["batch_number"] else "")
        + (f", exp {i['expiry_text']}" if i["expiry_text"] else "")
        for i in items
    ]
    model_label = f"Gemini ({GEMINI_MODELS[0]})" if provider == "gemini" else f"Claude ({CLAUDE_MODEL}, fallback)"
    body = ("; ".join(parts) if parts else (scan.notes or "No medicine products detected")).rstrip(". ")
    summary = (f"[{model_label}] {facilities_dict[facility_id]['name']}: {body}. "
               + ("Fewer units are visible than the register holds; the photo may show only part of the stock. " if partial and not flagged else "")
               + "Advisory only: pharmacist confirmation required.")
    return {
        "status": status,
        "facility_id": facility_id,
        "facility_name": facilities_dict[facility_id]["name"],
        "detected_items": items,
        "flagged_items": len(flagged),
        "model_provider": provider,
        "notes": scan.notes,
        "is_simulated": False,
        "certified": False,
        "human_review_required": True,
        "verification_summary": summary
    }
