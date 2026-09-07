import math
import uuid
from typing import List, Dict, Tuple
from app.models import StockoutRiskAssessment, TransferRecommendation, Facility

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance in kilometers between two lat/lng coordinates."""
    R = 6371.0  # Earth radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(R * c, 1)

class RedistributionOptimizer:
    def __init__(self, facilities: Dict[str, dict], max_distance_km: float = 35.0):
        self.facilities = facilities
        self.max_distance_km = max_distance_km

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
        # Index inventory by (facility_id, medicine_id)
        inv_map = {(item["facility_id"], item["medicine_id"]): item for item in raw_inventory}

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

                for donor in donors:
                    if donor.facility_id == recipient.facility_id:
                        continue

                    donor_fac = self.facilities.get(donor.facility_id)
                    if not donor_fac:
                        continue

                    dist = haversine_distance(donor_fac["lat"], donor_fac["lng"], rec_fac["lat"], rec_fac["lng"])
                    if dist > self.max_distance_km:
                        continue

                    donor_inv = inv_map.get((donor.facility_id, med_id))
                    if not donor_inv:
                        continue

                    # Donor must retain at least 14 days of surge-adjusted safety stock (strictly ceiling rounded)
                    min_donor_stock = math.ceil(14.0 * donor.projected_daily_rate)

                    # Available stock considers reservations and quarantines
                    donor_avail = donor_inv.get("available", donor_inv.get("on_hand", donor.current_stock))
                    available_to_give = donor_avail - min_donor_stock

                    if available_to_give <= 0:
                        continue

                    # Packaging formula: Q = p * floor(max(0, Q_eligible) / p)
                    pack_size = donor_inv.get("pack_size", 10) or 10
                    eligible = min(units_needed, available_to_give)
                    transfer_qty = pack_size * (max(0, eligible) // pack_size)

                    if transfer_qty <= 0 or (donor_avail - transfer_qty) < min_donor_stock:
                        continue

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
                        batch_number=donor_inv.get("batch_number", "BAT-GEN-01"),
                        batch_expiry_days=donor.days_to_expiry,
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

        # Sort recommendations: highest impact first (expiry waste saved + short distance)
        recommendations.sort(key=lambda r: (0 if r.expiry_waste_prevented else 1, r.distance_km))
        return recommendations
