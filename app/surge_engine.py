import json
import math
from typing import List, Dict, Tuple
from app.models import EnvironmentalReading, StockoutRiskAssessment, Facility, Medicine, InventoryItem

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
        Calculates category-specific consumption surge multipliers based on
        environmental readings (Air Quality, PM2.5, Temperature).
        """
        # Respiratory multiplier based on AQI
        if env.aqi <= 100:
            resp_mult = 1.0
        elif env.aqi <= 200:
            resp_mult = 1.18
        elif env.aqi <= 300:
            resp_mult = 1.35
        elif env.aqi <= 400:
            resp_mult = 1.62
        else:
            resp_mult = 1.90

        # Heat/Dehydration multiplier
        if env.temperature_c <= 35.0:
            heat_mult = 1.0
        elif env.temperature_c <= 40.0:
            heat_mult = 1.32
        elif env.temperature_c <= 44.0:
            heat_mult = 1.68
        else:
            heat_mult = 2.10

        if env.heatwave_alert:
            heat_mult = max(heat_mult, 1.75)

        if env.smog_episode:
            resp_mult = max(resp_mult, 1.55)

        return {
            "AQI / Smog": resp_mult,
            "Heatwave / Drought": heat_mult,
            "Secondary Respiratory": max(1.10, resp_mult * 0.85),
            "Heat / Infection": max(heat_mult * 0.8, resp_mult * 0.7),
            "Smog / Dust": resp_mult
        }

    def assess_facility_risks(
        self,
        inventory_items: List[dict],
        env: EnvironmentalReading
    ) -> List[StockoutRiskAssessment]:
        """
        Projects forward demand and calculates stockout probability within 7 days.
        Aggregates multiple batches per facility and medicine to evaluate true usable stock.
        """
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

            # Usable stock for dispensing is total_available
            days_of_cover = round(total_available / projected_rate, 1)

            # Cumulative stockout probability within 7 days using Poisson-approximated demand
            # Expected 7-day demand = 7 * projected_rate
            expected_7d_demand = 7 * projected_rate
            if total_available <= 0:
                stockout_prob = 1.0
            else:
                std_dev = math.sqrt(expected_7d_demand * 1.5)
                z_score = (total_available - expected_7d_demand) / (std_dev if std_dev > 0 else 1.0)
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
                available=total_available
            ))

        return assessments
