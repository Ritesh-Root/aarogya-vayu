import math
import re
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Literal, Set, Tuple
from dotenv import load_dotenv
load_dotenv()

from pydantic import BaseModel

from app.models import EnvironmentalReading, StockoutRiskAssessment
from app.surge_engine import SurgeEngine
from app.optimizer import RedistributionOptimizer, committed_transfers
from app.llm import generate_json, call_tool, GEMINI_MODELS, CLAUDE_MODEL
from app.telemetry_service import is_live_reading


class CmoInsight(BaseModel):
    query_type: Literal[
        "WHAT_IF_SURGE_SIMULATION", "DRUG_SUBSTITUTION_EVALUATION",
        "PARLIAMENTARY_IMPACT_BRIEF", "STRATEGIC_LOGISTICS_ADVISORY",
    ]
    answer_en: str
    answer_hi: str
    recommended_action: str

# -------------------------------------------------------------
# Knowledge Base: Drug Substitution Graph (Therapeutic Equivalence)
# -------------------------------------------------------------
DRUG_SUBSTITUTION_GRAPH = {
    "MED-001": {
        "standard_name": "Salbutamol Respirator Solution (Respules 2.5mg)",
        "therapeutic_class": "Short-Acting Beta-2 Agonist (Bronchodilator)",
        "substitutes": [
            {
                "substitute_id": "SUB-LEV-01",
                "name": "Levosalbutamol Respules (1.25mg/2.5ml)",
                "equivalence_ratio": 0.95,
                "clinical_notes": "Therapeutically equivalent single-isomer; lower cardiovascular tachycardia side-effect; requires 0.5x dosage."
            },
            {
                "substitute_id": "SUB-IPR-02",
                "name": "Ipratropium Bromide Respules (500mcg/2ml)",
                "equivalence_ratio": 0.75,
                "clinical_notes": "Anticholinergic bronchodilator; highly effective for COPD flare-ups; complementary to beta-agonists."
            }
        ]
    },
    "MED-002": {
        "standard_name": "Oral Rehydration Salts (ORS Sachets, WHO Formula)",
        "therapeutic_class": "Electrolyte & Fluid Replacement",
        "substitutes": [
            {
                "substitute_id": "SUB-ZNC-01",
                "name": "Zinc + ORS Pediatric Co-pack",
                "equivalence_ratio": 0.98,
                "clinical_notes": "Enhanced pediatric formulation recommended under NHM diarrhea management guidelines."
            }
        ]
    },
    "MED-003": {
        "standard_name": "Dexamethasone Sodium Phosphate Injection (4mg/ml)",
        "therapeutic_class": "Systemic Corticosteroid",
        "substitutes": [
            {
                "substitute_id": "SUB-HYD-01",
                "name": "Hydrocortisone Sodium Succinate 100mg Injection",
                "equivalence_ratio": 0.85,
                "clinical_notes": "Rapid-onset systemic steroid; suitable for acute emergency anaphylaxis and severe status asthmaticus."
            }
        ]
    }
}

# -------------------------------------------------------------
# Grounding Knowledge Base: District Essential Drug List (EDL)
# -------------------------------------------------------------
class AgentStepTrace:
    def __init__(self, agent_name: str, step_type: str, message: str, payload: Optional[Dict[str, Any]] = None):
        self.timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        self.agent_name = agent_name
        self.step_type = step_type  # "THINKING", "TOOL_CALL", "TOOL_RESULT", "GROUNDING_MATCH", "DISPATCH"
        self.message = message
        self.payload = payload or {}

    def to_dict(self):
        return {
            "timestamp": self.timestamp,
            "agent": self.agent_name,
            "type": self.step_type,
            "message": self.message,
            "payload": self.payload
        }

class MultiAgentResilienceOrchestrator:
    def __init__(self, facilities: Dict[str, dict], medicines: Dict[str, dict], surge_engine: SurgeEngine, optimizer: RedistributionOptimizer):
        self.facilities = facilities
        self.medicines = medicines
        self.surge_engine = surge_engine
        self.optimizer = optimizer

    # =========================================================================
    # AGENT 1: Environmental Sentinel Agent (Compound Reasoning)
    # =========================================================================
    def run_sentinel_agent(self, env: EnvironmentalReading) -> Dict[str, Any]:
        """
        Reasons over compound atmospheric factors from live telemetry: AQI/PM2.5 now and the
        72h CAMS forecast peak, wind, boundary-layer height (trapping), CAMS aerosol optical
        depth vs its 30-day baseline, and NASA FIRMS fire detections when configured.
        """
        is_live = is_live_reading(env)
        wind = env.wind_speed_kmh
        blh = env.boundary_layer_m
        # A shallow mixing layer with light wind traps particulates near the surface
        trapping = blh is not None and blh < 300 and (wind is None or wind < 8.0)

        parts = [f"Surface AQI={env.aqi}, PM2.5={env.pm25} µg/m³, {env.temperature_c}°C."]
        if wind is not None:
            parts.append(f"Wind {wind} km/h.")
        if blh is not None:
            parts.append(f"Boundary layer {round(blh)} m{' (shallow: particulates trapped near ground)' if trapping else ''}.")
        if env.aod is not None:
            sigma = f" ({env.aod_anomaly_sigma:+.1f}σ vs 30-day CAMS baseline)" if env.aod_anomaly_sigma is not None else ""
            parts.append(f"Aerosol optical depth {env.aod}{sigma}.")
        if env.forecast_peak_aqi_72h is not None:
            parts.append(f"CAMS forecast: AQI peaks at {env.forecast_peak_aqi_72h} in ~{env.forecast_peak_in_hours}h.")
        if env.forecast_max_temp_72h is not None:
            parts.append(f"Max forecast temperature {env.forecast_max_temp_72h}°C in 72h.")
        if env.fire_hotspots is not None:
            parts.append(f"NASA FIRMS: {env.fire_hotspots} VIIRS fire detections within ~165 km (48h).")
        if env.rain_24h_mm is not None and env.rain_24h_mm >= 64.5:
            parts.append(f"Heavy rain: up to {env.rain_24h_mm} mm in 24 h; diarrhoea and fever cases rise in the days after.")
        if env.min_temp_c is not None and env.min_temp_c <= 10:
            parts.append(f"Cold: minimum temperature {env.min_temp_c}°C; chest infections rise during cold spells.")
        parts.append("Respiratory admissions typically lag PM2.5 peaks by 1–3 days.")
        if not is_live:
            parts.insert(0, "SCENARIO MODE (simulated reading, not live telemetry):")

        if env.smog_episode and trapping:
            condition = "SEVERE_COMPOUND_INVERSION"
        elif env.smog_episode or env.heatwave_alert or env.flood_alert or env.cold_wave_alert:
            condition = "ELEVATED_SURGE"
        elif max(env.aqi, env.forecast_peak_aqi_72h or 0) > 150:
            condition = "WATCH"
        else:
            condition = "BASELINE"

        multipliers = self.surge_engine.calculate_surge_multipliers(env)
        return {
            "agent": "EnvironmentalSentinelAgent",
            "condition": condition,
            "situation_brief": " ".join(parts),
            "telemetry": {
                "aqi": env.aqi,
                "pm25": env.pm25,
                "rain_24h_mm": env.rain_24h_mm,
                "min_temp_c": env.min_temp_c,
                "flood_alert": env.flood_alert,
                "cold_wave_alert": env.cold_wave_alert,
                "wind_speed_kmh": wind,
                "boundary_layer_m": blh,
                "aod": env.aod,
                "aod_anomaly_sigma": env.aod_anomaly_sigma,
                "forecast_peak_aqi_72h": env.forecast_peak_aqi_72h,
                "forecast_peak_in_hours": env.forecast_peak_in_hours,
                "firms_hotspots": env.fire_hotspots,
                "source": env.source or "Scenario preset",
                "is_live": is_live,
            },
            "surge_multipliers": {
                "respiratory": multipliers["AQI / Smog"],
                "heat_dehydration": multipliers["Heatwave / Drought"],
                "flood_heavy_rain": multipliers["Flood / Heavy rain"],
                "cold_wave": multipliers["Cold wave"],
            },
        }

    # =========================================================================
    # AGENT 3: Demand Intelligence Agent (lag-curve surge forecast)
    # =========================================================================
    def run_demand_forecast(self, facility_id: str, medicine_id: str, raw_inventory: List[dict], env: EnvironmentalReading,
                            inbound: Optional[Dict[Tuple[str, str], int]] = None) -> Dict[str, Any]:
        """
        Rule-based forecaster: baseline consumption × the surge engine's climate multiplier,
        ramped in over a sigmoid lag curve peaking on day 3, with P10/P50/P90 bands from the
        same demand variance (1.5× mean) the surge engine uses. The 7-day stockout probability and
        days of cover are the surge engine's own figures for this item.
        """
        items = [i for i in raw_inventory if i["facility_id"] == facility_id and i["medicine_id"] == medicine_id]
        risk = next((r for r in self.surge_engine.assess_facility_risks(items, env, inbound)), None) if items else None
        base_rate = items[0].get("daily_consumption_base", 15.0) if items else 0.0
        current_stock = risk.current_stock if risk else 0
        climate_cat = self.medicines.get(medicine_id, {}).get("climate_sensitive", "General")
        surge_mult = self.surge_engine.calculate_surge_multipliers(env).get(climate_cat, 1.0)

        forecast_7d = []
        cum_demand_p50 = 0.0
        for day in range(1, 8):
            lag_factor = 1.0 + (surge_mult - 1.0) / (1.0 + math.exp(-1.2 * (day - 3)))
            day_p50 = base_rate * lag_factor
            band = 1.2816 * math.sqrt(day_p50 * 1.5)  # z(0.9) under the surge engine's variance model
            cum_demand_p50 += day_p50
            forecast_7d.append({
                "day": day,
                "p10": round(max(0.0, day_p50 - band), 1),
                "p50": round(day_p50, 1),
                "p90": round(day_p50 + band, 1),
            })

        # Probability and cover come from the same surge-engine assessment as the risk table, so the
        # pipeline never shows a different figure for the same item; None when there is no stock record
        stockout_prob_7d = risk.stockout_probability_7d if risk else None
        days_of_coverage = risk.days_of_coverage if risk else None
        peak_rate = max((d["p50"] for d in forecast_7d), default=0.0)
        return {
            "agent": "DemandIntelligenceAgent",
            "model": "lag_curve_surge_forecaster (rule-based)",
            "facility_id": facility_id,
            "medicine_id": medicine_id,
            "current_stock": current_stock,
            "baseline_daily_rate": base_rate,
            "surge_multiplier": surge_mult,
            "median_surge_rate": round(peak_rate, 1),
            "days_of_coverage": days_of_coverage,
            "stockout_probability_7d": stockout_prob_7d,
            "forecast_quantiles_7d": forecast_7d,
            "risk_status": risk.status if risk else "NO_STOCK_RECORD"
        }

    # =========================================================================
    # AGENT 4: Logistics Redistribution Agent (LLM function calling + solver)
    # =========================================================================
    SOLVER_TOOL = {
        "name": "calculate_optimal_transfer",
        "description": (
            "Run the deterministic constrained redistribution solver for one facility and medicine. "
            "It finds donor facilities within the distance limit that keep their own safety reserve, "
            "preferring near-expiry batches (FEFO)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target_facility_id": {"type": "string", "description": "Facility that needs stock"},
                "medicine_id": {"type": "string", "description": "Medicine ID, e.g. MED-001"},
                "max_distance_km": {"type": "number", "description": "Maximum donor distance in km. District policy is 35; use 35 unless the context requires a closer limit"},
                "allow_substitution": {"type": "boolean", "description": "Evaluate a therapeutic substitute if no donor is feasible"},
            },
            "required": ["target_facility_id", "medicine_id", "max_distance_km", "allow_substitution"],
        },
    }

    async def run_logistics_agent(
        self,
        target_phc_id: str,
        medicine_id: str,
        risks: List[StockoutRiskAssessment],
        raw_inventory: List[dict],
        context: str = "",
        active_ids: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """
        Asks the LLM (Gemini, Claude fallback) to choose the solver arguments via forced function
        calling, validates them, then runs the deterministic solver. LLMs never compute the allocation.
        """
        tool = self.SOLVER_TOOL
        default_args = {"target_facility_id": target_phc_id, "medicine_id": medicine_id, "max_distance_km": 35.0, "allow_substitution": True}
        result = await call_tool(
            "You are the logistics agent for a district medicine supply network. Decide the solver arguments for this "
            "situation and call the tool. Use only facility and medicine IDs that appear in the context.",
            f"{context}\nTarget facility: {target_phc_id} ({self.facilities.get(target_phc_id, {}).get('name', '')}). "
            f"Medicine: {medicine_id} ({self.medicines.get(medicine_id, {}).get('name', '')}).",
            tool["name"], tool["description"], tool["parameters"],
        )
        args, called_by = (result if result else (default_args, "deterministic_default"))
        # Never trust model-chosen IDs or limits: the target and medicine are fixed by the request,
        # and only the radius (clamped) and substitution flag come from the model
        args["target_facility_id"] = target_phc_id
        args["medicine_id"] = medicine_id
        try:
            args["max_distance_km"] = min(35.0, max(5.0, float(args.get("max_distance_km", 35.0))))
        except (TypeError, ValueError):
            args["max_distance_km"] = 35.0
        sub = args.get("allow_substitution", True)
        args["allow_substitution"] = sub if isinstance(sub, bool) else str(sub).strip().lower() == "true"

        started = time.perf_counter()
        recs = self.optimizer.optimize(risks, raw_inventory, active_ids)
        solver_ms = round((time.perf_counter() - started) * 1000, 2)
        matches = [r for r in recs if r.recipient_facility_id == args["target_facility_id"] and r.medicine_id == args["medicine_id"]]
        chosen_rec = next((r for r in matches if r.distance_km <= args["max_distance_km"]), None)
        # A model-chosen radius must never hide a transfer the 35 km policy allows
        radius_widened = False
        if not chosen_rec and matches:
            chosen_rec = matches[0]
            radius_widened = True

        substitution_info = None
        if not chosen_rec and args["allow_substitution"]:
            sub_meta = DRUG_SUBSTITUTION_GRAPH.get(args["medicine_id"])
            if sub_meta and sub_meta["substitutes"]:
                best_sub = sub_meta["substitutes"][0]
                substitution_info = {
                    "original_medicine": sub_meta["standard_name"],
                    "substitute_name": best_sub["name"],
                    "therapeutic_equivalence": best_sub["equivalence_ratio"],
                    "clinical_rationale": best_sub["clinical_notes"],
                    "requires_special_cmo_signoff": True
                }

        return {
            "agent": "LogisticsRedistributionAgent",
            "tool_called": tool["name"],
            "tool_called_by": called_by,
            "tool_arguments": args,
            "recommendation": chosen_rec.model_dump() if chosen_rec else None,
            "drug_substitution": substitution_info,
            "solver_runtime_ms": solver_ms,
            "radius_widened_to_policy": radius_widened,
            "status": "TRANSFER_OPTIMIZED" if chosen_rec else "UNMET_DEMAND_ESCALATED"
        }

    # =========================================================================
    # AGENT 5: Governance & Strategic Decision Agent (CMO Chat & Policy Advisory)
    # =========================================================================
    async def query_strategic_insight(
        self,
        question: str,
        env: EnvironmentalReading,
        raw_inventory: List[dict],
        consignments: Optional[Dict[str, dict]] = None,
    ) -> Dict[str, Any]:
        """
        Synthesizes clinical policy, what-if surge forecasting, and emergency stock
        rebalancing for the District Chief Medical Officer.
        """
        q = (question or "").lower().strip()
        inbound, active_ids = committed_transfers(consignments or {})
        risks = self.surge_engine.assess_facility_risks(raw_inventory, env, inbound)
        recs = self.optimizer.optimize(risks, raw_inventory, active_ids)

        is_bbs = any(tok in (env.corridor or "").lower() for tok in ["bhubaneswar", "cuttack", "odisha", "coastal"]) or any(r.facility_id.startswith("PHC-BBS") or r.facility_id.startswith("CHC-CTC") for r in risks)
        corridor_title = "Bhubaneswar–Cuttack Health Corridor" if is_bbs else "Lucknow-Unnao Health Corridor"
        state_title = "Odisha" if is_bbs else "Uttar Pradesh"
        mp_constituency = "Bhubaneswar & Cuttack Parliamentary Constituencies" if is_bbs else "Lucknow & Mohanlalganj Parliamentary Constituencies"

        multipliers = self.surge_engine.calculate_surge_multipliers(env)
        at_risk = sorted((r for r in risks if r.status in ["CRITICAL", "WARNING"]), key=lambda r: r.days_of_coverage)
        donor_names = list(dict.fromkeys(r.donor_facility_name for r in recs))[:2]
        donors_title = " and ".join(donor_names) if donor_names else "corridor surplus facilities"

        # Everything the model may quote is computed here; it is told not to invent other figures
        risk_lines = "\n".join(
            f"- {r.facility_name}: {r.medicine_name.split('(')[0].strip()} {r.available if r.available is not None else r.current_stock} units, "
            f"{r.days_of_coverage} days cover, 7-day stockout probability {round(r.stockout_probability_7d * 100)}% ({r.status})"
            for r in at_risk[:8]
        ) or "- No facility is below the warning threshold"
        rec_lines = "\n".join(
            f"- {r.donor_facility_name} -> {r.recipient_facility_name}: {r.units_to_transfer} units {r.medicine_name.split('(')[0].strip()}, {r.distance_km} km"
            for r in recs[:6]
        ) or "- None"
        mult_line = ", ".join(f"{k} x{round(v, 2)}" for k, v in multipliers.items())
        region_fac_ids = {i["facility_id"] for i in raw_inventory}
        population = sum(self.facilities.get(f, {}).get("population_served", 0) for f in region_fac_ids)
        expiry_units = sum(r.units_to_transfer for r in recs if r.expiry_waste_prevented)
        cmo_system_prompt = (
            f"You are the Strategic Insight Agent for Aarogya-Vayu, a climate-resilient rural health logistics platform for {state_title}, India. "
            f"You advise the Chief Medical Officer (CMO) of the {corridor_title}.\n"
            f"Telemetry ({'live' if is_live_reading(env) else 'scenario'}): AQI {env.aqi}, PM2.5 {env.pm25} µg/m³, {env.temperature_c}°C, "
            f"smog episode {env.smog_episode}, heatwave {env.heatwave_alert}, flood/heavy rain {env.flood_alert}"
            f"{f' ({env.rain_24h_mm} mm/24 h)' if env.rain_24h_mm is not None else ''}, cold wave {env.cold_wave_alert}"
            f"{f' (min {env.min_temp_c}°C)' if env.min_temp_c is not None else ''}.\n"
            f"Demand surge multipliers by medicine class (rule-based): {mult_line}.\n"
            f"Facilities at risk, soonest stockout first:\n{risk_lines}\n"
            f"Proposed transfers awaiting CMO approval:\n{rec_lines}\n"
            f"Coverage: {len(region_fac_ids)} monitored PHCs/CHCs serving {population:,} people (demo registry figures); "
            f"{expiry_units} near-expiry units are in the proposed transfers.\n\n"
            "Use only the figures above; never invent numbers, facilities, depots, medicines or percentages. If the question needs "
            "data that is not here, say so. If the question is not about this district's health supply chain, say briefly that "
            "you only answer questions about it. Respond in plain text fields (no HTML or markdown). query_type is one of WHAT_IF_SURGE_SIMULATION, "
            "DRUG_SUBSTITUTION_EVALUATION, PARLIAMENTARY_IMPACT_BRIEF, STRATEGIC_LOGISTICS_ADVISORY. answer_en is a concise "
            "strategic briefing in English, answer_hi a professional Hindi translation, and recommended_action one clear "
            "operational action for the CMO or logistics team."
        )
        result = await generate_json(cmo_system_prompt, f"Question from CMO: {question}", CmoInsight)
        if result:
            insight, provider = result
            answered_by = f"Gemini ({GEMINI_MODELS[0]})" if provider == "gemini" else f"Claude ({CLAUDE_MODEL}, fallback)"
            return {**insight.model_dump(), "answered_by": answered_by}

        answer = self._scripted_insight(q, env, risks, recs, at_risk, multipliers, corridor_title, state_title, donors_title, mp_constituency, raw_inventory)
        return {**answer, "answered_by": "Scripted answer (no LLM available)"}

    def _scripted_insight(self, q, env, risks, recs, at_risk, multipliers, corridor_title, state_title, donors_title, mp_constituency, raw_inventory) -> Dict[str, Any]:
        def asks(*patterns):
            return any(re.search(p, q) for p in patterns)

        # Fallback Scenario 1: Extended surge what-if ("5 din aur", "5 more days", "what if")
        if asks(r"\bwhat[- ]?if\b", r"\bdin\b", r"\bmore days?\b", r"\bduration\b", r"\bstock ?outs?\b", r"\bsurge\b", "स्मॉग", "दिन"):
            # One row per facility (its earliest-depleting medicine), soonest stockout first
            seen_facilities = set()
            extended_critical = []
            for r in at_risk:
                if r.facility_id in seen_facilities:
                    continue
                seen_facilities.add(r.facility_id)
                extended_critical.append({
                    "facility": r.facility_name,
                    "medicine": r.medicine_name.split("(")[0].strip(),
                    "current_days_cover": round(r.days_of_coverage, 1),
                    "projected_stockout_day": f"Day {max(1, int(r.days_of_coverage))}"
                })
            extended_critical = extended_critical[:4]

            top_class, top_mult = max(multipliers.items(), key=lambda kv: kv[1])
            surge_pct = round((top_mult - 1) * 100)
            surge_en = (f"demand for {top_class} medicines runs {surge_pct:+d}% against baseline under the current multiplier"
                        if surge_pct else "demand stays at baseline under current conditions")
            fac_str = ", ".join(f"{x['facility']} ({x['projected_stockout_day']})" for x in extended_critical) or "no facility below the warning threshold"
            fac_hi_str = ", ".join(x["facility"] for x in extended_critical) or "कोई केंद्र चेतावनी स्तर से नीचे नहीं"

            answer_en = (
                f"WHAT-IF (conditions persist): at AQI {env.aqi}, PM2.5 {env.pm25} µg/m³ and {env.temperature_c}°C across {corridor_title}, "
                f"{surge_en}. Earliest projected stockouts: {fac_str}. "
                f"Transfers proposed from {donors_title} are awaiting approval."
            )
            answer_hi = (
                f"यदि मौजूदा स्थिति बनी रहती है ({state_title}, {corridor_title}): मांग गुणक {round(top_mult, 2)} ({top_class})। "
                f"सबसे पहले स्टॉक समाप्त होने का अनुमान: {fac_hi_str}। {donors_title} से स्थानांतरण प्रस्ताव अनुमोदन हेतु लंबित हैं।"
            )
            return {
                "query_type": "WHAT_IF_SURGE_SIMULATION",
                "answer_en": answer_en,
                "answer_hi": answer_hi,
                "affected_facilities": extended_critical,
                "recommended_action": f"Approve the pending transfers for the earliest-stockout facilities in {corridor_title}."
            }

        # Scenario 2: Drug Substitution Query ("levosalbutamol", "substitute", "बदल")
        elif asks(r"levo", r"substitut", r"\balternatives?\b", "बदल", "विकल्प"):
            sub = DRUG_SUBSTITUTION_GRAPH["MED-001"]["substitutes"][0]
            answer_en = (
                f"THERAPEUTIC SUBSTITUTION VERIFIED: Yes, Levosalbutamol Respules (1.25mg/2.5ml) is approved as an emergency alternative "
                f"for Salbutamol (2.5mg) under National Health Mission clinical guidelines with 95% therapeutic equivalence. "
                f"Note: Due to enhanced single-isomer receptor affinity, required dosage is halved. "
                f"A specialized CMO Clinical Sign-off is prepared for dispatch across {corridor_title}."
            )
            answer_hi = (
                f"हाँ, साल्बुटामोल की जगह लेवोसल्बुटामोल (1.25mg) भेजा जा सकता है। यह 95% चिकित्सीय रूप से समकक्ष है "
                f"और इसमें धड़कन तेज होने (टैचीकार्डिया) के दुष्प्रभाव भी कम होते हैं।"
            )
            return {
                "query_type": "DRUG_SUBSTITUTION_EVALUATION",
                "answer_en": answer_en,
                "answer_hi": answer_hi,
                "substitution_details": sub,
                "clinical_gate_required": True
            }

        # Scenario 3: MP Impact & Accountability Report ("mp", "report", "रिपोर्ट", "साहब")
        elif asks(r"\bmp\b", r"parliament", r"\breport\b", r"\bbrief\b", r"constituenc", "रिपोर्ट", "सांसद", "साहब"):
            region_fac_ids = {i["facility_id"] for i in raw_inventory}
            population = sum(self.facilities.get(f, {}).get("population_served", 0) for f in region_fac_ids)
            at_risk_covered = len({(r.recipient_facility_id, r.medicine_id) for r in recs})
            expiry_prevented = sum(r.units_to_transfer for r in recs if r.expiry_waste_prevented)
            answer_en = (
                f"PARLIAMENTARY CONSTITUENCY IMPACT REPORT ({mp_constituency}):\n"
                f"• Population Served: {population:,} people across {len(region_fac_ids)} monitored PHCs/CHCs.\n"
                f"• Stockout Risks Addressed: {at_risk_covered} facility-medicine shortfalls in {corridor_title} have a proposed transfer awaiting CMO approval.\n"
                f"• Medicine Waste Avoided: {expiry_prevented} units of near-expiry stock routed to where they will be used before expiry.\n"
                f"• Governance Footprint: every approved movement is recorded in a SHA-256 hash-chained audit ledger."
            )
            answer_hi = (
                f"सांसद महोदय के लिए संसदीय क्षेत्र रिपोर्ट ({mp_constituency}):\n"
                f"• सेवा प्राप्त जनसंख्या: {len(region_fac_ids)} स्वास्थ्य केंद्रों के अंतर्गत {population:,} नागरिक।\n"
                f"• स्टॉकआउट जोखिम: {corridor_title} में {at_risk_covered} कमियों के लिए स्थानांतरण प्रस्ताव CMO अनुमोदन हेतु लंबित।\n"
                f"• एक्सपायरी की बचत: {expiry_prevented} यूनिट दवाइयां समय रहते उपयोग हेतु भेजी जा रही हैं।"
            )
            return {
                "query_type": "PARLIAMENTARY_IMPACT_BRIEF",
                "answer_en": answer_en,
                "answer_hi": answer_hi,
                "metrics": {
                    "population_served": population,
                    "facilities_covered": len(region_fac_ids),
                    "stockout_risks_addressed": at_risk_covered,
                    "near_expiry_units_salvaged": expiry_prevented
                }
            }

        # Anything else: a factual status summary from the current assessment
        top = at_risk[:3]
        top_str = "; ".join(f"{r.facility_name} {r.medicine_name.split('(')[0].strip()} ({r.days_of_coverage}d cover)" for r in top) or "none"
        pending_n = len(recs)
        return {
            "query_type": "STRATEGIC_LOGISTICS_ADVISORY",
            "answer_en": (f"{corridor_title} status: {len(at_risk)} facility-medicine pairs are at warning or critical level. "
                          f"Most urgent: {top_str}. {pending_n} transfer proposal(s) are awaiting CMO approval."),
            "answer_hi": (f"{corridor_title} स्थिति: {len(at_risk)} दवा-केंद्र जोड़े चेतावनी या गंभीर स्तर पर हैं। "
                          f"{pending_n} स्थानांतरण प्रस्ताव CMO अनुमोदन हेतु लंबित हैं।"),
            "recommended_action": "Review the pending transfer recommendations, starting with the lowest days of cover.",
        }

    # =========================================================================
    # Master Execution Trace for the multi-agent pipeline
    # =========================================================================
    async def run_pipeline(
        self,
        env: EnvironmentalReading,
        raw_inventory: List[dict],
        target_phc_id: str = "PHC-LKO-01",
        intake: Optional[Dict[str, Any]] = None,
        consignments: Optional[Dict[str, dict]] = None,
    ) -> Dict[str, Any]:
        traces: List[Dict[str, Any]] = []
        facility_name = self.facilities.get(target_phc_id, {}).get("name", target_phc_id)

        # 1. Sentinel Agent
        sentinel_res = self.run_sentinel_agent(env)
        if sentinel_res["telemetry"]["is_live"]:
            polling = "Fetching Open-Meteo weather and Copernicus CAMS air-quality forecast" + (" + NASA FIRMS fires" if env.fire_hotspots is not None else "") + "..."
        else:
            polling = "Scenario mode: using the selected preset reading instead of live telemetry."
        traces.append(AgentStepTrace("EnvironmentalSentinelAgent", "THINKING", polling).to_dict())
        traces.append(AgentStepTrace("EnvironmentalSentinelAgent", "DISPATCH", sentinel_res["situation_brief"], sentinel_res["telemetry"]).to_dict())

        # 2. Frontline Intake Agent: use the parsed field report when it is about this facility,
        # otherwise pick the facility's highest-risk medicine from the live risk assessment
        # Stock already approved or on its way counts as cover, and its transfers are not proposed again
        inbound, active_ids = committed_transfers(consignments or {})
        risks = self.surge_engine.assess_facility_risks(raw_inventory, env, inbound)
        if intake and intake.get("facility_id") == target_phc_id:
            medicine_id = intake["medicine_id"]
            parser = {"gemini": f"Gemini ({GEMINI_MODELS[0]})", "claude": f"Claude ({CLAUDE_MODEL}, fallback)"}.get(
                intake.get("parsed_by"), "offline rule-based parser")
            register = sum(r.current_stock for r in risks if r.facility_id == target_phc_id and r.medicine_id == medicine_id)
            traces.append(AgentStepTrace(
                "FrontlineIntakeAgent", "THINKING",
                f"Field report parsed by {parser}: "
                + (f"{intake['reported_stock']} units left" if intake.get("reported_stock") is not None else "no stock count stated")
                + f", confidence {round(intake['confidence_score'] * 100)}%. "
                f"Treated as unconfirmed: planning uses the register ({register} available) until staff confirm the count on the Clinic Desk."
            ).to_dict())
            entity = {
                "standard_name": intake.get("standard_name") or intake.get("medicine_name"),
                "code": intake.get("medicine_code") or medicine_id,
                "category": intake.get("edl_category") or "",
            }
        else:
            facility_risks = sorted((r for r in risks if r.facility_id == target_phc_id),
                                    key=lambda r: (-r.stockout_probability_7d, r.days_of_coverage))
            medicine_id = facility_risks[0].medicine_id if facility_risks else "MED-001"
            other = intake.get("facility_name") if intake else None
            note = (f"The field report is about {other}, not {facility_name}, so it is not used here. " if other
                    else f"No stock report for {facility_name}. ")
            traces.append(AgentStepTrace(
                "FrontlineIntakeAgent", "THINKING",
                note + "Selecting its most at-risk medicine from the inventory register."
            ).to_dict())
            med = self.medicines.get(medicine_id, {})
            entity = {"standard_name": med.get("name", medicine_id), "code": medicine_id, "category": med.get("category", "")}
        traces.append(AgentStepTrace(
            "FrontlineIntakeAgent", "GROUNDING_MATCH",
            f"Matched to Essential Drug List item '{entity['standard_name']}' [{entity['code']}].",
            {"grounded_entity": entity}
        ).to_dict())

        # 3. Demand Intelligence Agent
        demand_res = self.run_demand_forecast(target_phc_id, medicine_id, raw_inventory, env, inbound)
        cover = f"{demand_res['days_of_coverage']}d" if demand_res["days_of_coverage"] is not None else "n/a"
        prob = demand_res["stockout_probability_7d"]
        prob_pct = f"{round(prob * 100)}%" if prob is not None else "n/a (no stock record)"
        traces.append(AgentStepTrace(
            "DemandIntelligenceAgent", "THINKING",
            f"Lag-curve forecast: baseline {demand_res['baseline_daily_rate']}/day × surge {demand_res['surge_multiplier']} → peak {demand_res['median_surge_rate']}/day. "
            f"Stock {demand_res['current_stock']}, cover {cover}, 7-day stockout probability {prob_pct}.",
            {"forecast": demand_res["forecast_quantiles_7d"][:3]}
        ).to_dict())

        # A facility with healthy cover needs no transfer: don't call the model or escalate anything
        if demand_res["risk_status"] not in ("CRITICAL", "WARNING", "NO_STOCK_RECORD"):
            traces.append(AgentStepTrace(
                "LogisticsAgent", "THINKING",
                f"{facility_name} has {cover} of cover for this medicine ({demand_res['risk_status']}); no transfer is needed."
            ).to_dict())
            traces.append(AgentStepTrace("GovernanceAgent", "DISPATCH", "No action required.", {"status": "NO_ACTION_NEEDED"}).to_dict())
            return {"status": "PIPELINE_COMPLETE", "traces": traces, "sentinel": sentinel_res, "demand_forecast": demand_res, "logistics": None}

        # 4. Logistics Agent
        context = (
            f"Situation: {sentinel_res['situation_brief']}\n"
            f"Demand forecast: {demand_res['risk_status']}, stock {demand_res['current_stock']}, "
            f"7-day stockout probability {prob_pct}."
        )
        logistics_res = await self.run_logistics_agent(target_phc_id, medicine_id, risks, raw_inventory, context, active_ids)
        args = logistics_res["tool_arguments"]
        caller = {"gemini": f"Gemini ({GEMINI_MODELS[0]}) function call", "claude": f"Claude ({CLAUDE_MODEL}) tool call (Gemini unavailable)"}.get(
            logistics_res["tool_called_by"])
        tool_msg = (f"{caller}: the LLM chooses the search radius and substitution policy; the allocation itself is computed by the deterministic solver."
                    if caller else "No LLM available, so the solver runs with policy defaults (35 km, substitution allowed).")
        traces.append(AgentStepTrace(
            "LogisticsAgent", "TOOL_CALL",
            tool_msg,
            {"tool": logistics_res["tool_called"], "arguments": args, "called_by": logistics_res["tool_called_by"]}
        ).to_dict())

        rec = logistics_res.get("recommendation")
        if rec:
            widened = (f"No donor within the requested {args['max_distance_km']} km, so the search used the 35 km policy radius. "
                       if logistics_res.get("radius_widened_to_policy") else "")
            solver_msg = widened + (
                f"Solver ({logistics_res['solver_runtime_ms']} ms) matched donor {rec['donor_facility_name']} ({rec['distance_km']} km): "
                f"{rec['units_to_transfer']} units from batch {rec.get('batch_number') or 'n/a'}"
                + (f", expiring in {rec['batch_expiry_days']} days." if rec.get("batch_expiry_days") is not None else ".")
            )
            tool_res_payload = dict(rec)
        else:
            solver_msg = (
                f"Solver ({logistics_res['solver_runtime_ms']} ms): no donor within {args['max_distance_km']} km can spare stock "
                f"without breaching its 14-day reserve. Escalated to the district requisition queue."
            )
            tool_res_payload = {"no_feasible_donor": True, "drug_substitution": logistics_res.get("drug_substitution")}
        traces.append(AgentStepTrace("LogisticsAgent", "TOOL_RESULT", solver_msg, tool_res_payload).to_dict())

        # 5. Governance Agent
        traces.append(AgentStepTrace(
            "GovernanceAgent", "DISPATCH",
            "Transfer recommendation queued for CMO review. Nothing moves until a human signs off; the decision is sealed in the SHA-256 audit chain."
            if rec else "Unmet demand report queued for the District Health Society. Any substitution needs CMO sign-off.",
            {"status": "AWAITING_CMO_SIGN_OFF" if rec else "ESCALATED_UNMET_DEMAND"}
        ).to_dict())

        return {
            "status": "PIPELINE_COMPLETE",
            "traces": traces,
            "sentinel": sentinel_res,
            "demand_forecast": demand_res,
            "logistics": logistics_res
        }
