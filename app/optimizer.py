import math
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Any
from app.models import (
    StockoutRiskAssessment, TransferRecommendation, Facility,
    UnmetDemandReport, EDL_PRODUCT_SPEC
)

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance in kilometers between two lat/lng coordinates."""
    R = 6371.0  # Earth radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(R * c, 1)

def get_batch_available(b: dict) -> int:
    if "available" in b:
        return b["available"]
    on_hand = b.get("on_hand", b.get("current_stock", 0))
    reserved = b.get("reserved", 0)
    quarantined = b.get("quarantined", 0)
    return max(0, on_hand - reserved - quarantined)

class RedistributionOptimizer:
    def __init__(self, facilities: Dict[str, dict], max_distance_km: float = 35.0):
        self.facilities = facilities
        self.max_distance_km = max_distance_km
        self.unmet_demands: List[UnmetDemandReport] = []

    def get_unmet_demands(self) -> List[UnmetDemandReport]:
        return self.unmet_demands

    def validate_transfer_invariants(
        self,
        rec: TransferRecommendation,
        donor_current_stock: int
    ) -> Tuple[bool, str]:
        """
        Independent invariant validator to guarantee mathematical feasibility
        before emitting or approving any transfer recommendation.
        """
        if rec.units_to_transfer <= 0:
            return False, f"Non-positive transfer units: {rec.units_to_transfer}"

        if rec.distance_km > self.max_distance_km:
            return False, f"Transfer distance ({rec.distance_km} km) exceeds maximum limit ({self.max_distance_km} km)"

        if donor_current_stock < rec.units_to_transfer:
            return False, f"Donor current stock ({donor_current_stock}) is less than transfer units ({rec.units_to_transfer})"

        rem_donor_stock = donor_current_stock - rec.units_to_transfer
        if rem_donor_stock < rec.donor_min_reserve_units:
            return False, f"Donor remaining stock ({rem_donor_stock}) violates clinical reserve floor ({rec.donor_min_reserve_units})"

        if rec.batch_expiry_days < 30:
            return False, f"Batch expiry too close ({rec.batch_expiry_days} days); clinical safety threshold is 30 days"

        return True, "Valid"

    def optimize(
        self,
        risk_assessments: List[StockoutRiskAssessment],
        raw_inventory: List[dict]
    ) -> List[TransferRecommendation]:
        """
        Solves the constrained redistribution problem to match surplus facilities
        with deficit/stockout-threatened facilities.

        Objective:
        1. Maximize coverage of critical deficits (PHCs with < 4-8 days).
        2. Prioritize near-expiry batches (30-90 days) to prevent pharmaceutical waste.
        3. Minimize transit distance within maximum service radius (<= 35 km).
        4. Guarantee donor facility retains >= 14 days of surge-adjusted safety stock.
        """
        self.unmet_demands.clear()

        # Group inventory by (facility_id, medicine_id) to handle multi-batch holdings
        facility_med_batches: Dict[Tuple[str, str], List[dict]] = {}
        for item in raw_inventory:
            key = (item["facility_id"], item["medicine_id"])
            facility_med_batches.setdefault(key, []).append(item)

        # Group assessments by medicine
        med_assessments: Dict[str, List[StockoutRiskAssessment]] = {}
        for a in risk_assessments:
            med_assessments.setdefault(a.medicine_id, []).append(a)

        recommendations: List[TransferRecommendation] = []

        for med_id, assessments in med_assessments.items():
            # Identify Deficit (Critical & Warning) and Potential Donors (Surplus & Healthy)
            recipients = [a for a in assessments if a.status in ["CRITICAL", "WARNING"]]
            recipients.sort(key=lambda x: x.days_of_coverage)  # most critical first

            # Eligible donors must have >= 16 days of surge-adjusted cover and >= 30 days before expiry
            donors = [
                a for a in assessments 
                if a.days_of_coverage >= 16.0 and a.days_to_expiry >= 30
            ]
            # Prioritize donors with stock expiring sooner (30-90 days) to eliminate expiration waste
            donors.sort(key=lambda x: (0 if x.expiry_risk else 1, x.days_to_expiry, -x.days_of_coverage))

            for recipient in recipients:
                rec_fac = self.facilities.get(recipient.facility_id)
                if not rec_fac:
                    continue

                # Target: bring recipient up to resilient 14 days cover
                target_coverage_days = 14.0
                units_needed = max(10, int((target_coverage_days - recipient.days_of_coverage) * recipient.projected_daily_rate))

                # Record candidate evaluation reasons for all other facilities in corridor
                rejections: List[Dict[str, Any]] = []

                # Evaluate every peer facility in the regional cohort to prove no feasible redistribution donor exists
                rejections = []
                cohort_fac_ids = {a.facility_id for a in assessments}
                for other_id in sorted(cohort_fac_ids):
                    if other_id == recipient.facility_id:
                        continue
                    other_fac = self.facilities.get(other_id)
                    if not other_fac:
                        continue

                    dist = haversine_distance(other_fac["lat"], other_fac["lng"], rec_fac["lat"], rec_fac["lng"])
                    cand_assessment = next((a for a in assessments if a.facility_id == other_id), None)
                    cand_batches = facility_med_batches.get((other_id, med_id), [])
                    cand_avail = sum(get_batch_available(b) for b in cand_batches)
                    cand_rate = cand_assessment.projected_daily_rate if cand_assessment else 15.0
                    cand_cov = cand_assessment.days_of_coverage if cand_assessment else round(cand_avail / cand_rate, 1)
                    cand_min_reserve = math.ceil(14.0 * cand_rate)

                    if dist > self.max_distance_km:
                        rejection_reason = f"Distance radius breach: {dist} km exceeds maximum transport radius ({self.max_distance_km} km)"
                    elif cand_cov < 16.0:
                        rejection_reason = (
                            f"Clinical safety reserve breach: Coverage {cand_cov}d < 16.0d donor threshold; "
                            f"available stock ({cand_avail}) <= 14-day safety reserve ({cand_min_reserve} units)"
                        )
                    elif not any(b.get("days_to_expiry", 365) >= 30 for b in cand_batches):
                        rejection_reason = "Pharmaceutical safety: All batches expire in < 30 days"
                    elif (cand_avail - cand_min_reserve) < 10:
                        rejection_reason = f"Insufficient surplus: Available to give ({cand_avail - cand_min_reserve}) < pack size (10)"
                    else:
                        rejection_reason = "Candidate eligible but matched to higher priority or exhausted"

                    rejections.append({
                        "donor_facility_id": other_id,
                        "donor_facility_name": other_fac["name"],
                        "distance_km": dist,
                        "donor_current_coverage_days": cand_cov,
                        "donor_min_reserve_units": cand_min_reserve,
                        "rejection_reason": rejection_reason
                    })

                # Sort rejections by distance for readable reporting
                rejections.sort(key=lambda r: r["distance_km"])

                for donor in donors:
                    if donor.facility_id == recipient.facility_id:
                        continue

                    donor_fac = self.facilities.get(donor.facility_id)
                    if not donor_fac:
                        continue

                    dist = haversine_distance(donor_fac["lat"], donor_fac["lng"], rec_fac["lat"], rec_fac["lng"])
                    if dist > self.max_distance_km:
                        continue

                    donor_batches = facility_med_batches.get((donor.facility_id, med_id), [])
                    if not donor_batches:
                        continue

                    # Donor must retain at least 14 days of surge-adjusted safety stock (strictly ceiling rounded)
                    min_donor_stock = math.ceil(14.0 * donor.projected_daily_rate)

                    # Available stock considers reservations and quarantines across batches, bounded by remaining stock
                    donor_avail = min(sum(get_batch_available(b) for b in donor_batches), donor.current_stock)
                    available_to_give = donor_avail - min_donor_stock

                    if available_to_give <= 0:
                        continue

                    # Packaging formula: Q = p * floor(max(0, Q_eligible) / p)
                    pack_size = donor_batches[0].get("pack_size", 10) or 10
                    eligible = min(units_needed, available_to_give)
                    transfer_qty = pack_size * (max(0, eligible) // pack_size)

                    if transfer_qty <= 0 or (donor_avail - transfer_qty) < min_donor_stock:
                        continue

                    # Select FEFO candidate batch for physical consignment
                    fefo_candidates = [
                        b for b in donor_batches
                        if b.get("days_to_expiry", 365) >= 30 and get_batch_available(b) > 0
                    ]
                    fefo_candidates.sort(key=lambda b: b.get("days_to_expiry", 365))
                    selected_batch = next(
                        (b for b in fefo_candidates if get_batch_available(b) >= transfer_qty),
                        fefo_candidates[0] if fefo_candidates else donor_batches[0]
                    )

                    # Update projected coverages
                    rec_initial_days = recipient.days_of_coverage
                    rec_new_days = round(rec_initial_days + (transfer_qty / recipient.projected_daily_rate), 1)
                    donor_rem_days = round((donor.current_stock - transfer_qty) / donor.projected_daily_rate, 1)

                    expiry_waste_saved = donor.expiry_risk or donor.days_to_expiry <= 90

                    # Rationale generation
                    med_name = recipient.medicine_name.split("(")[0].strip()
                    rat_en = (
                        f"Transfer {transfer_qty} units of {med_name} from {donor.facility_name} ({dist} km away). "
                        f"Prevents impending stockout at {recipient.facility_name} (coverage boosts from {rec_initial_days}d to {rec_new_days}d). "
                        f"Donor retains a resilient {donor_rem_days} days of surge-adjusted safety stock. "
                        + (f"Crucially prevents batch expiration waste (expires in {donor.days_to_expiry} days)." if expiry_waste_saved else "")
                    )

                    rat_hi = (
                        f"{donor.facility_name} ({dist} किमी दूर) से {transfer_qty} यूनिट {med_name} स्थानांतरित करें। "
                        f"{recipient.facility_name} पर स्टॉकआउट को रोका गया (कवरेज {rec_initial_days} दिन से बढ़कर {rec_new_days} दिन)। "
                        f"दाता केंद्र के पास {donor_rem_days} दिन का सुरक्षित बफर उपलब्ध रहेगा।"
                    )

                    rec_id = f"REC-{uuid.uuid4().hex[:8].upper()}"
                    rec = TransferRecommendation(
                        id=rec_id,
                        donor_facility_id=donor.facility_id,
                        donor_facility_name=donor.facility_name,
                        recipient_facility_id=recipient.facility_id,
                        recipient_facility_name=recipient.facility_name,
                        medicine_id=med_id,
                        medicine_name=recipient.medicine_name,
                        units_to_transfer=transfer_qty,
                        batch_number=selected_batch.get("batch_number", "BAT-GEN-01"),
                        batch_expiry_days=selected_batch.get("days_to_expiry", donor.days_to_expiry),
                        distance_km=dist,
                        recipient_initial_coverage_days=rec_initial_days,
                        recipient_new_coverage_days=rec_new_days,
                        donor_remaining_coverage_days=donor_rem_days,
                        donor_min_reserve_units=min_donor_stock,
                        expiry_waste_prevented=expiry_waste_saved,
                        rationale_en=rat_en,
                        rationale_hi=rat_hi,
                        status="PENDING_APPROVAL"
                    )

                    # Invariant verification pass
                    is_valid, reason = self.validate_transfer_invariants(rec, donor.current_stock)
                    if not is_valid:
                        continue

                    recommendations.append(rec)

                    # Deduct from donor available stock for next iterations and recalculate coverage
                    donor.current_stock -= transfer_qty
                    donor.days_of_coverage = round(donor.current_stock / donor.projected_daily_rate, 1)
                    units_needed -= transfer_qty
                    if units_needed <= 0:
                        break

                # If after checking all donors, there is still an unmet clinical deficit:
                if units_needed > 0:
                    spec = EDL_PRODUCT_SPEC.get(med_id, {
                        "dosage_form": "General",
                        "strength": "Standard",
                        "unit": "units",
                        "pack_size": 10
                    })
                    now_iso = datetime.now(timezone.utc).isoformat() + "Z"
                    unmet = UnmetDemandReport(
                        facility_id=recipient.facility_id,
                        facility_name=recipient.facility_name,
                        medicine_id=med_id,
                        medicine_name=recipient.medicine_name,
                        dosage_form=spec["dosage_form"],
                        strength=spec["strength"],
                        unit=spec["unit"],
                        pack_size=spec.get("pack_size", 10),
                        current_available=recipient.current_stock,
                        projected_daily_rate=recipient.projected_daily_rate,
                        days_of_coverage=recipient.days_of_coverage,
                        shortage_severity=recipient.status,
                        unmet_units_needed=units_needed,
                        infeasibility_reason=(
                            f"MACRO_DEFICIT_NO_SAFE_PEER_DONOR: 0 of {len(self.facilities) - 1} peer facilities in corridor "
                            f"can donate without breaching their own 14-day clinical safety reserve under acute surge."
                        ),
                        rejection_breakdown=rejections,
                        escalation_channel="DISTRICT_REPLENISHMENT_REQUISITION",
                        timestamp=now_iso
                    )
                    self.unmet_demands.append(unmet)

        # Sort recommendations: highest impact first (expiry waste saved + short distance)
        recommendations.sort(key=lambda r: (0 if r.expiry_waste_prevented else 1, r.distance_km))
        return recommendations
