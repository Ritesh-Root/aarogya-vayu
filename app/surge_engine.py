import json
import math
from typing import List, Dict, Optional, Tuple
from app.models import EnvironmentalReading, StockoutRiskAssessment, Facility, Medicine, InventoryItem

# ---- Heavy rain / floods and cold waves (sources in the README, "How weather changes demand") ----
# Rain bands use IMD's 24 h categories (SOP for Weather Forecasting and Warning): heavy 64.5 mm,
# extremely heavy 204.5 mm. Diarrhoea admissions rise about x1.5 after heavy rain (Bush 2014, Chennai,
# RR 1.60; Kraay 2020 meta-analysis 1.23-1.56) and about x2 in real floods (Hashizume 2008, Dhaka).
FLOOD_BANDS = [(64.5, 1.5), (204.5, 2.0)]
FLOOD_ALERT_MIN = 1.5
# Cold bands use IMD's plains cold-wave minimums (cold wave <= 4 °C, severe <= 2 °C). Pneumonia
# admissions rise about x1.23 in cold spells and up to x1.69 at the peak (Feng 2023; Wu 2024; both China:
# no Indian morbidity study exists). The <= 10 °C band (IMD's cold-wave eligibility) is a low-confidence x1.1.
COLD_BANDS = [(10.0, 1.1), (4.0, 1.25), (2.0, 1.5)]
COLD_ALERT_MIN = 1.25
# Share of a hazard's surge that partly sensitive categories take (indirect evidence; low confidence)
FLOOD_SHARE = {"Heat / Infection": 0.4}             # fever medicine: about x1.2 in the acute phase
COLD_SHARE = {"AQI / Smog": 0.6, "Heat / Infection": 0.6}  # salbutamol ~x1.15 (x1.3 severe); paracetamol ~x1.15


class SurgeEngine:
    def __init__(self, facilities_path, medicines_path):
        if isinstance(facilities_path, dict):
            self.facilities = facilities_path
        elif isinstance(facilities_path, list):
            self.facilities = {fac["id"]: fac for fac in facilities_path}
        else:
            with open(facilities_path, "r", encoding="utf-8") as f:
                self.facilities = {fac["id"]: fac for fac in json.load(f)}

        if isinstance(medicines_path, dict):
            self.medicines = medicines_path
        elif isinstance(medicines_path, list):
            self.medicines = {med["id"]: med for med in medicines_path}
        else:
            with open(medicines_path, "r", encoding="utf-8") as f:
                self.medicines = {med["id"]: med for med in json.load(f)}

    def calculate_surge_multipliers(self, env: EnvironmentalReading) -> Dict[str, float]:
        """
        Category-specific consumption multipliers from the environment: air quality, heat,
        heavy rain / floods and cold waves. Each medicine category takes the strongest of the
        hazards that drive it (a share of a hazard's surge where it is only partly driven by it).
        """
        # Plan against the worse of now and the 72h forecast peak (live telemetry only)
        aqi = max(env.aqi, env.forecast_peak_aqi_72h or 0)
        temperature_c = max(env.temperature_c, env.forecast_max_temp_72h if env.forecast_max_temp_72h is not None else env.temperature_c)

        # Respiratory multiplier based on AQI
        if aqi <= 100:
            resp_mult = 1.0
        elif aqi <= 200:
            resp_mult = 1.18
        elif aqi <= 300:
            resp_mult = 1.35
        elif aqi <= 400:
            resp_mult = 1.62
        else:
            resp_mult = 1.90

        # Heat/Dehydration multiplier
        if temperature_c <= 35.0:
            heat_mult = 1.0
        elif temperature_c <= 40.0:
            heat_mult = 1.32
        elif temperature_c <= 44.0:
            heat_mult = 1.68
        else:
            heat_mult = 2.10

        if env.heatwave_alert:
            heat_mult = max(heat_mult, 1.75)

        if env.smog_episode:
            resp_mult = max(resp_mult, 1.55)

        flood_mult = self._flood_multiplier(env)
        cold_mult = self._cold_multiplier(env)

        def share(mult: float, fraction: float) -> float:
            return 1 + fraction * (mult - 1)

        return {
            # Salbutamol, dexamethasone: air quality; cold air also triggers asthma/COPD flare-ups
            "AQI / Smog": round(max(resp_mult, share(cold_mult, COLD_SHARE["AQI / Smog"])), 3),
            # ORS: heat, and diarrhoea after floods
            "Heatwave / Drought": round(max(heat_mult, flood_mult), 3),
            # Partly sensitive categories take a share of each surge, and are exactly 1.0 at baseline
            "Secondary Respiratory": round(max(share(resp_mult, 0.85), cold_mult), 3),
            "Heat / Infection": round(max(share(heat_mult, 0.8), share(resp_mult, 0.7),
                                          share(flood_mult, FLOOD_SHARE["Heat / Infection"]), share(cold_mult, COLD_SHARE["Heat / Infection"])), 3),
            "Smog / Dust": resp_mult,
            # Hazard levels themselves, for display
            "Flood / Heavy rain": flood_mult,
            "Cold wave": cold_mult,
        }

    @staticmethod
    def _flood_multiplier(env: EnvironmentalReading) -> float:
        """Diarrhoeal and fever demand after heavy rain, banded on IMD 24 h rainfall categories."""
        rain = env.rain_24h_mm or 0.0
        mult = 1.0
        for threshold, value in FLOOD_BANDS:
            if rain >= threshold:
                mult = value
        if env.flood_alert:
            mult = max(mult, FLOOD_ALERT_MIN)
        return mult

    @staticmethod
    def _cold_multiplier(env: EnvironmentalReading) -> float:
        """Respiratory-infection demand in cold spells, banded on the minimum temperature."""
        tmin = env.min_temp_c if env.min_temp_c is not None else env.temperature_c
        mult = 1.0
        for threshold, value in COLD_BANDS:
            if tmin <= threshold:
                mult = value
        if env.cold_wave_alert:
            mult = max(mult, COLD_ALERT_MIN)
        return mult

    def assess_facility_risks(
        self,
        inventory_items: List[dict],
        env: EnvironmentalReading,
        inbound: Optional[Dict[Tuple[str, str], int]] = None
    ) -> List[StockoutRiskAssessment]:
        """
        Projects forward demand and calculates stockout probability within 7 days.
        Aggregates multiple batches per facility and medicine to evaluate true usable stock.
        `inbound` maps (facility_id, medicine_id) to units already approved or dispatched to that
        facility; they count toward cover so the same need is not planned twice.
        """
        inbound = inbound or {}
        multipliers = self.calculate_surge_multipliers(env)
        assessments = []

        # Group inventory items by (facility_id, medicine_id)
        grouped: Dict[Tuple[str, str], List[dict]] = {}
        for item in inventory_items:
            key = (item["facility_id"], item["medicine_id"])
            grouped.setdefault(key, []).append(item)

        for (fac_id, med_id), batch_items in grouped.items():
            first_item = batch_items[0]
            med_meta = self.medicines.get(med_id, {})
            climate_cat = med_meta.get("climate_sensitive", "General")
            
            surge_mult = multipliers.get(climate_cat, 1.0)
            base_rate = first_item.get("daily_consumption_base", 15.0)
            projected_rate = max(1.0, round(base_rate * surge_mult, 1))

            total_on_hand = sum(item.get("on_hand", item.get("current_stock", 0)) for item in batch_items)
            total_reserved = sum(item.get("reserved", 0) for item in batch_items)
            total_quarantined = sum(item.get("quarantined", 0) for item in batch_items)
            total_available = sum(
                item.get("available", max(0, item.get("on_hand", item.get("current_stock", 0)) - item.get("reserved", 0) - item.get("quarantined", 0)))
                for item in batch_items
            )

            # Usable stock is what is on the shelf plus transfers already committed to this facility
            inbound_units = inbound.get((fac_id, med_id), 0)
            usable = total_available + inbound_units
            days_of_cover = round(usable / projected_rate, 1)

            # Cumulative stockout probability within 7 days using Poisson-approximated demand
            # Expected 7-day demand = 7 * projected_rate
            expected_7d_demand = 7 * projected_rate
            if usable <= 0:
                stockout_prob = 1.0
            else:
                std_dev = math.sqrt(expected_7d_demand * 1.5)
                z_score = (usable - expected_7d_demand) / (std_dev if std_dev > 0 else 1.0)
                cdf = 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0)))
                stockout_prob = max(0.0, min(1.0, round(1.0 - cdf, 3)))

            # Expiry risk: evaluate batches under FEFO
            batches_with_stock = [b for b in batch_items if b.get("available", b.get("on_hand", 0)) > 0] or batch_items
            min_days_to_expiry = min(b.get("days_to_expiry", 365) for b in batches_with_stock)
            days_to_deplete = days_of_cover
            expiry_risk = any(
                b.get("days_to_expiry", 365) < days_to_deplete and b.get("days_to_expiry", 365) <= 90
                for b in batches_with_stock
            )

            # Classification
            if days_of_cover < 4.0 or stockout_prob >= 0.75:
                status = "CRITICAL"
            elif days_of_cover < 8.0 or stockout_prob >= 0.40:
                status = "WARNING"
            elif days_of_cover >= 22.0:
                status = "SURPLUS"
            else:
                status = "HEALTHY"

            assessments.append(StockoutRiskAssessment(
                facility_id=fac_id,
                facility_name=first_item["facility_name"],
                medicine_id=med_id,
                medicine_name=first_item["medicine_name"],
                current_stock=total_available,
                projected_daily_rate=projected_rate,
                days_of_coverage=days_of_cover,
                stockout_probability_7d=stockout_prob,
                status=status,
                expiry_risk=expiry_risk,
                days_to_expiry=min_days_to_expiry,
                on_hand=total_on_hand,
                available=total_available,
                inbound_units=inbound_units
            ))

        return assessments
