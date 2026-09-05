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

class InventoryItem(BaseModel):
    facility_id: str
    facility_name: str
    medicine_id: str
    medicine_name: str
    current_stock: int
    daily_consumption_base: float
    batch_number: str
    expiry_date: str
    days_to_expiry: int
    last_updated: str

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
    expiry_waste_prevented: bool
    rationale_en: str
    rationale_hi: str
    status: str = "PENDING_APPROVAL"

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
    reported_stock: int
    dispensed_yesterday: Optional[int]
    confidence_score: float
    detected_language: str
    quality_checks_passed: bool
    anomaly_flag: Optional[str] = None
    raw_transcript: str
    action_taken: str

class ApprovalRequest(BaseModel):
    recommendation_id: str
    officer_name: str = "Dr. S. K. Saxena (Chief Medical Officer, District Health Society)"
    comments: Optional[str] = None
