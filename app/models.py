from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class Facility(BaseModel):
    id: str
    name: str
    district: str
    type: str  # PHC or CHC
    lat: float
    lng: float
    population_served: int
    beds: int
    cold_storage: bool
    doctor: str

class Medicine(BaseModel):
    id: str
    name: str
    category: str
    unit: str
    climate_sensitive: str
    base_consumption_phc: float
    base_consumption_chc: float
    min_buffer_days: int
    critical_threshold_days: int
    pack_size: int = 10

class InventoryItem(BaseModel):
    facility_id: str
    facility_name: str
    medicine_id: str
    medicine_name: str
    batch_number: str
    expiry_date: str
    days_to_expiry: int
    daily_consumption_base: float
    on_hand: int = Field(description="All physical units physically present at the facility")
    reserved: int = Field(default=0, description="Usable units committed to approved outgoing transfers")
    quarantined: int = Field(default=0, description="Damaged, expired, or non-dispensable units held on site")
    available: int = Field(default=0, description="Usable stock: on_hand - reserved - quarantined")
    raw_available: int = Field(default=0, description="Exact on_hand - reserved - quarantined (can be negative if over-committed)")
    reconciliation_deficit: int = Field(default=0, description="Deficit amount if reserved + quarantined > on_hand")
    freeze_reason: Optional[str] = Field(default=None, description="Detailed explanation if batch is frozen")
    is_reconciliation_required: bool = Field(default=False, description="True if physical count is below commitments")
    current_stock: int = Field(default=0, description="Mirror of on_hand for backward compatibility")
    pack_size: int = Field(default=10, description="Standard packaging multiple")
    unit: str = Field(default="units", description="Dosage/dispensing unit")
    version: int = Field(default=1, description="Optimistic locking version")
    is_frozen: bool = Field(default=False, description="Frozen against dispatches if reconciliation exception occurs")
    last_updated: str
    last_verified_at: Optional[str] = None
    verified_by: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        if self.current_stock == 0 and self.on_hand > 0:
            self.current_stock = self.on_hand
        elif self.on_hand == 0 and self.current_stock > 0:
            self.on_hand = self.current_stock
        raw = self.on_hand - self.reserved - self.quarantined
        self.raw_available = raw
        if raw < 0:
            self.reconciliation_deficit = abs(raw)
            self.is_reconciliation_required = True
            self.is_frozen = True
        else:
            self.reconciliation_deficit = 0
            self.is_reconciliation_required = False
        self.available = max(0, raw)

class EnvironmentalReading(BaseModel):
    aqi: int = Field(default=385, description="Air Quality Index")
    pm25: float = Field(default=245.0, description="PM2.5 in ug/m3")
    temperature_c: float = Field(default=18.5, description="Ambient temperature in Celsius")
    humidity_pct: float = Field(default=75.0, description="Relative humidity %")
    heatwave_alert: bool = Field(default=False)
    smog_episode: bool = Field(default=True)
    corridor: str = Field(default="Lucknow-Unnao Industrial & Agricultural Corridor")

class StockoutRiskAssessment(BaseModel):
    facility_id: str
    facility_name: str
    medicine_id: str
    medicine_name: str
    current_stock: int
    projected_daily_rate: float
    days_of_coverage: float
    stockout_probability_7d: float
    status: str  # "CRITICAL", "WARNING", "HEALTHY", "SURPLUS"
    expiry_risk: bool
    days_to_expiry: int
    on_hand: Optional[int] = None
    available: Optional[int] = None

# EDL-UP-2026 Canonical Pharmaceutical Product Specifications
EDL_PRODUCT_SPEC: Dict[str, Dict[str, Any]] = {
    "MED-001": {
        "dosage_form": "Respirator Solution",
        "strength": "2.5mg",
        "unit": "Respules (vials)",
        "base_unit": "Respule",
        "pack_size": 10
    },
    "MED-002": {
        "dosage_form": "Oral Powder Sachets",
        "strength": "20.5g WHO Formula",
        "unit": "Sachets",
        "base_unit": "Sachet",
        "pack_size": 10
    },
    "MED-003": {
        "dosage_form": "Injection",
        "strength": "4mg/ml",
        "unit": "Ampoules",
        "base_unit": "Ampoule",
        "pack_size": 10
    },
    "MED-004": {
        "dosage_form": "Tablets",
        "strength": "625mg (500mg/125mg)",
        "unit": "Strips (10 tabs)",
        "base_unit": "Strip",
        "pack_size": 10
    },
    "MED-005": {
        "dosage_form": "IV Infusion",
        "strength": "1000mg/100ml",
        "unit": "Bottles",
        "base_unit": "Bottle",
        "pack_size": 10
    },
    "MED-006": {
        "dosage_form": "Tablets",
        "strength": "10mg",
        "unit": "Strips (10 tabs)",
        "base_unit": "Strip",
        "pack_size": 10
    }
}

class CandidateRejectionDetail(BaseModel):
    donor_facility_id: str
    donor_facility_name: str
    distance_km: float
    donor_current_coverage_days: float
    donor_min_reserve_units: int
    rejection_reason: str

class UnmetDemandReport(BaseModel):
    facility_id: str
    facility_name: str
    medicine_id: str
    medicine_name: str
    dosage_form: str
    strength: str
    unit: str
    pack_size: int = 10
    current_available: int
    projected_daily_rate: float
    days_of_coverage: float
    shortage_severity: str  # "CRITICAL", "WARNING"
    unmet_units_needed: int
    infeasibility_reason: str
    rejection_breakdown: List[Dict[str, Any]]
    escalation_channel: str = "DISTRICT_REPLENISHMENT_REQUISITION"
    timestamp: Optional[str] = None

class TransferRecommendation(BaseModel):
    id: str
    donor_facility_id: str
    donor_facility_name: str
    recipient_facility_id: str
    recipient_facility_name: str
    medicine_id: str
    medicine_name: str
    units_to_transfer: int
    batch_number: str
    batch_expiry_days: int
    distance_km: float
    recipient_initial_coverage_days: float
    recipient_new_coverage_days: float
    donor_remaining_coverage_days: float
    donor_min_reserve_units: int = 0
    expiry_waste_prevented: bool
    rationale_en: str
    rationale_hi: str
    status: str = "PENDING_APPROVAL"
    challan_id: Optional[str] = None
    cryptographic_hash: Optional[str] = None
    authorized_by: Optional[str] = None
    approved_at: Optional[str] = None

class TransferConsignment(BaseModel):
    id: str
    recommendation_id: Optional[str] = None
    challan_id: str
    donor_facility_id: str
    donor_facility_name: str
    recipient_facility_id: str
    recipient_facility_name: str
    medicine_id: str
    medicine_name: str
    batch_number: str
    expiry_date: str
    days_to_expiry: int
    pack_size: int = 10
    distance_km: float
    units_requested: int
    units_dispatched: int = 0
    units_accepted: int = 0
    units_quarantined: int = 0
    units_missing: int = 0
    status: str = "APPROVED_RESERVED"  # "APPROVED_RESERVED", "DISPATCHED", "RECEIVED", "CANCELLED"
    authorized_by: str
    approved_at: str
    dispatched_by: Optional[str] = None
    dispatched_at: Optional[str] = None
    received_by: Optional[str] = None
    received_at: Optional[str] = None
    discrepancy_reason: Optional[str] = None
    condition_notes: Optional[str] = None
    vehicle_number: Optional[str] = None
    idempotency_key: Optional[str] = None
    cryptographic_hash: Optional[str] = None

class StockActionRequest(BaseModel):
    facility_id: str
    medicine_id: str
    batch_number: str
    action_type: str  # "PHYSICAL_COUNT", "STOCK_RECEIVED", "STOCK_ISSUED", "QUARANTINE_DAMAGED"
    quantity: int  # count target or delta
    reason: str
    operator_name: str = "Staff Pharmacist"
    operator_role: str = "PHARMACIST"
    expected_version: Optional[int] = None
    idempotency_key: Optional[str] = None

class StockActionResult(BaseModel):
    success: bool
    action_type: str
    facility_id: str
    medicine_id: str
    batch_number: str
    previous_on_hand: int
    new_on_hand: int
    new_reserved: int
    new_quarantined: int
    new_available: int
    raw_available: int = 0
    reconciliation_deficit: int = 0
    freeze_reason: Optional[str] = None
    version: int
    reconciliation_exception: bool = False
    message: str
    audit_hash: Optional[str] = None
    timestamp: str

class DispatchConsignmentRequest(BaseModel):
    consignment_id: str
    operator_name: str = "Staff Pharmacist"
    operator_role: str = "PHARMACIST"
    vehicle_number: Optional[str] = "UP-32-MED-4412"
    courier_notes: Optional[str] = None
    idempotency_key: Optional[str] = None

class ReceiveConsignmentRequest(BaseModel):
    consignment_id: str
    operator_name: str = "Staff Pharmacist"
    operator_role: str = "PHARMACIST"
    accepted_units: int
    quarantined_units: int = 0
    missing_units: int = 0
    condition_intact: bool = True
    discrepancy_notes: Optional[str] = None
    idempotency_key: Optional[str] = None

class CancelConsignmentRequest(BaseModel):
    consignment_id: str
    operator_name: str = "Dr. Authorized MOIC"
    operator_role: str = "MOIC"
    reason: str
    idempotency_key: Optional[str] = None

class ResolveReconciliationRequest(BaseModel):
    facility_id: str
    medicine_id: str
    batch_number: str
    resolution_type: str  # "SUPERVISOR_RECOUNT", "CANCEL_RESERVATIONS", "ADJUST_QUARANTINE"
    verified_physical_count: Optional[int] = None
    cancelled_consignment_ids: Optional[List[str]] = None
    quarantine_adjustment: Optional[int] = None
    supervisor_name: str = "Dr. S. K. Saxena (MOIC)"
    supervisor_role: str = "MOIC"
    resolution_notes: str
    idempotency_key: Optional[str] = None

class ResolveReconciliationResult(BaseModel):
    success: bool
    facility_id: str
    medicine_id: str
    batch_number: str
    previous_deficit: int
    new_on_hand: int
    new_reserved: int
    new_quarantined: int
    new_available: int
    raw_available: int
    is_frozen: bool
    resolution_type: str
    message: str
    audit_hash: Optional[str] = None
    timestamp: str

class StockMovementEntry(BaseModel):
    index: int
    timestamp: str
    event_type: str
    movement_type: str
    delta_physical: int
    delta_available: int
    resulting_on_hand: int
    resulting_available: int
    resulting_reserved: int
    resulting_quarantined: int
    operator_name: str
    operator_role: str
    reason: str
    linked_consignment_id: Optional[str] = None
    audit_hash: str

class StockMovementRegister(BaseModel):
    facility_id: str
    facility_name: str
    medicine_id: str
    medicine_name: str
    batch_number: str
    pack_size: int
    opening_on_hand: int
    opening_available: int
    closing_on_hand: int
    closing_available: int
    closing_reserved: int
    closing_quarantined: int
    reconciliation_deficit: int = 0
    is_frozen: bool = False
    freeze_reason: Optional[str] = None
    movements: List[StockMovementEntry]
    generated_at: str
    register_title: str = "Facility Stock Movement Register (Daily Handover & Discrepancy Ledger)"
    compliance_notice: str = "Operational Working Register • Pre-validation e-Aushadhi / Form 16 Working Format"


class DailyActionItem(BaseModel):
    id: str
    urgency: str  # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    action_type: str  # "IMPENDING_STOCKOUT", "INBOUND_TRANSFER_PENDING", "OUTBOUND_DISPATCH_PENDING", "RECONCILIATION_REQUIRED", "EXPIRY_WARNING", "UNVERIFIED_STOCK"
    title: str
    description: str
    target_medicine_id: Optional[str] = None
    target_consignment_id: Optional[str] = None
    target_batch: Optional[str] = None
    cta_label: str

class ClinicDeskResponse(BaseModel):
    facility: Facility
    operator_role_mode: str = "DEMO_ROLE_SIMULATION"
    action_items: List[DailyActionItem]
    inventory: List[Dict[str, Any]]
    inbound_consignments: List[Dict[str, Any]]
    outbound_consignments: List[Dict[str, Any]]
    active_reconciliation_exceptions: List[Dict[str, Any]]

class VoiceIntakeRequest(BaseModel):
    facility_id: Optional[str] = None
    transcript_text: str
    audio_base64: Optional[str] = None
    language: str = "en"  # "en", "hi", "hinglish"

class VoiceIntakeResponse(BaseModel):
    facility_id: str
    facility_name: str
    medicine_id: str
    medicine_name: str
    medicine_code: str = ""
    standard_name: str = ""
    dosage_form: str = ""
    strength: str = ""
    edl_category: str = ""
    reported_stock: int
    dispensed_yesterday: Optional[int]
    confidence_score: float
    detected_language: str
    quality_checks_passed: bool
    requires_confirmation: bool = True
    is_draft: bool = True
    anomaly_flag: Optional[str] = None
    raw_transcript: str
    action_taken: str = "DRAFT_CREATED_AWAITING_CONFIRMATION"

class ApprovalRequest(BaseModel):
    recommendation_id: str
    officer_name: str = "Dr. S. K. Saxena (Chief Medical Officer, District Health Society)"
    comments: Optional[str] = None
    idempotency_key: Optional[str] = None
