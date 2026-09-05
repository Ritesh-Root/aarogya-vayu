import json
import math
from typing import List, Dict, Tuple
from app.models import EnvironmentalReading, StockoutRiskAssessment, Facility, Medicine, InventoryItem

class SurgeEngine:
    def __init__(self, facilities_path: str, medicines_path: str):
        with open(facilities_path, "r") as f:
            self.facilities: Dict[str, dict] = {fac["id"]: fac for fac in json.load(f)}
        with open(medicines_path, "r") as f:
            self.medicines: Dict[str, dict] = {med["id"]: med for med in json.load(f)}

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
        """
        multipliers = self.calculate_surge_multipliers(env)
        assessments = []

        for item in inventory_items:
            med_id = item["medicine_id"]
            med_meta = self.medicines.get(med_id, {})
            climate_cat = med_meta.get("climate_sensitive", "General")
            
            surge_mult = multipliers.get(climate_cat, 1.0)
            base_rate = item["daily_consumption_base"]
            projected_rate = max(1.0, round(base_rate * surge_mult, 1))

            current_stock = item["current_stock"]
            days_of_cover = round(current_stock / projected_rate, 1)

            # Cumulative stockout probability within 7 days using Poisson-approximated demand
            # Expected 7-day demand = 7 * projected_rate
            # Variance modeled with uncertainty factor
            expected_7d_demand = 7 * projected_rate
            if current_stock <= 0:
                stockout_prob = 1.0
            else:
                # Normal approximation for demand distribution over 7 days
                std_dev = math.sqrt(expected_7d_demand * 1.5)
                z_score = (current_stock - expected_7d_demand) / (std_dev if std_dev > 0 else 1.0)
                # 1 - CDF(z)
                # Using error function approximation:
                cdf = 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0)))
                stockout_prob = max(0.0, min(1.0, round(1.0 - cdf, 3)))

            # Expiry risk: will the stock expire before current consumption can deplete it?
            days_to_deplete = days_of_cover
            days_to_expiry = item.get("days_to_expiry", 365)
            expiry_risk = days_to_expiry < days_to_deplete and days_to_expiry <= 90

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
                facility_id=item["facility_id"],
                facility_name=item["facility_name"],
                medicine_id=med_id,
                medicine_name=item["medicine_name"],
                current_stock=current_stock,
                projected_daily_rate=projected_rate,
                days_of_coverage=days_of_cover,
                stockout_probability_7d=stockout_prob,
                status=status,
                expiry_risk=expiry_risk,
                days_to_expiry=days_to_expiry
            ))

        return assessments
