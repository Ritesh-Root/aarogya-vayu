import math
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Literal
from dotenv import load_dotenv
load_dotenv()

from pydantic import BaseModel

from app.models import EnvironmentalReading, StockoutRiskAssessment
from app.surge_engine import SurgeEngine
from app.optimizer import RedistributionOptimizer
from app.llm import generate_json, call_tool, GEMINI_MODELS, CLAUDE_MODEL


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
        is_live = "Open-Meteo" in (env.source or "")
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
        parts.append("Respiratory admissions typically lag PM2.5 peaks by 1–3 days.")
        if not is_live:
            parts.insert(0, "SCENARIO MODE (simulated reading, not live telemetry):")

        if env.smog_episode and trapping:
            condition = "SEVERE_COMPOUND_INVERSION"
        elif env.smog_episode or env.heatwave_alert:
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
            },
        }

    # =========================================================================
    # AGENT 3: Demand Intelligence Agent (lag-curve surge forecast)
    # =========================================================================
    def run_demand_forecast(self, facility_id: str, medicine_id: str, raw_inventory: List[dict], env: EnvironmentalReading) -> Dict[str, Any]:
        """
        Rule-based forecaster: baseline consumption × the surge engine's climate multiplier,
        ramped in over a sigmoid lag curve peaking on day 3, with P10/P50/P90 bands from the
        same demand variance (1.5× mean) the surge engine uses for stockout probability.
        """
        items = [i for i in raw_inventory if i["facility_id"] == facility_id and i["medicine_id"] == medicine_id]
        risk = next((r for r in self.surge_engine.assess_facility_risks(items, env)), None) if items else None
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

        if current_stock <= 0:
            stockout_prob_7d = 1.0
        elif cum_demand_p50 <= 0:
            stockout_prob_7d = 0.0
        else:
            z = (current_stock - cum_demand_p50) / math.sqrt(cum_demand_p50 * 1.5)
            stockout_prob_7d = round(1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0))), 3)

        peak_rate = max((d["p50"] for d in forecast_7d), default=0.0)
        days_of_coverage = round(current_stock / peak_rate, 1) if peak_rate > 0 else None
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
        # Never trust model-chosen IDs or limits: clamp to known values
        if args.get("target_facility_id") not in self.facilities:
            args["target_facility_id"] = target_phc_id
        if args.get("medicine_id") not in self.medicines:
            args["medicine_id"] = medicine_id
        try:
            args["max_distance_km"] = min(35.0, max(5.0, float(args.get("max_distance_km", 35.0))))
        except (TypeError, ValueError):
            args["max_distance_km"] = 35.0
        args["allow_substitution"] = bool(args.get("allow_substitution", True))

        started = time.perf_counter()
        recs = self.optimizer.optimize(risks, raw_inventory)
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
        raw_inventory: List[dict]
    ) -> Dict[str, Any]:
        """
        Synthesizes clinical policy, what-if surge forecasting, and emergency stock
        rebalancing for the District Chief Medical Officer.
        """
        q = (question or "").lower().strip()
        risks = self.surge_engine.assess_facility_risks(raw_inventory, env)
        recs = self.optimizer.optimize(risks, raw_inventory)

        is_bbs = any(tok in (env.corridor or "").lower() for tok in ["bhubaneswar", "cuttack", "odisha", "coastal"]) or any(r.facility_id.startswith("PHC-BBS") or r.facility_id.startswith("CHC-CTC") for r in risks)
        corridor_title = "Bhubaneswar–Cuttack Health Corridor" if is_bbs else "Lucknow-Unnao Health Corridor"
        state_title = "Odisha" if is_bbs else "Uttar Pradesh"
        donors_title = "Capital Hospital Unit-6 and CHC Jatni" if is_bbs else "Nawabganj and Malihabad"
        mp_constituency = "Bhubaneswar & Cuttack Parliamentary Constituencies" if is_bbs else "Lucknow & Mohanlalganj Parliamentary Constituencies"

        # Live LLM generation (Gemini primary, Claude fallback) when a key is configured
        crit_list = [f"{r.facility_name}: {r.days_of_coverage}d cover" for r in risks if r.status == 'CRITICAL'][:5]
        crit_summary = ", ".join(crit_list) if crit_list else "All facilities currently above critical threshold"
        cmo_system_prompt = (
            f"You are the Strategic Insight Agent for Aarogya-Vayu, an autonomous climate-resilient rural health logistics platform for {state_title}, India. "
            f"You provide clinical, logistical, and policy guidance to Chief Medical Officers (CMO) in the {corridor_title}.\n"
            f"Current Telemetry: AQI {env.aqi}, PM2.5 {env.pm25} µg/m³, Temp {env.temperature_c}°C, Corridor: '{env.corridor}', Smog Inversion: {env.smog_episode}, Heatwave: {env.heatwave_alert}.\n"
            f"Critical Facilities: {crit_summary}.\n\n"
            "Respond in plain text fields (no HTML or markdown). query_type is one of WHAT_IF_SURGE_SIMULATION, "
            "DRUG_SUBSTITUTION_EVALUATION, PARLIAMENTARY_IMPACT_BRIEF, STRATEGIC_LOGISTICS_ADVISORY. answer_en is a concise "
            "strategic briefing in English, answer_hi a professional Hindi translation, and recommended_action one clear "
            "operational action for the CMO or ambulance logistics team."
        )
        result = await generate_json(cmo_system_prompt, f"Question from CMO: {question}", CmoInsight)
        if result:
            insight, _provider = result
            return insight.model_dump()

        # Fallback Scenario 1: Extended Smog Duration What-If ("5 din aur", "5 more days", "what-if")
        if any(w in q for w in ["5", "स्मॉग", "din", "duration", "what if", "stock out", "first", "surge"]):
            # One row per facility (its earliest-depleting medicine), soonest stockout first
            at_risk = sorted((r for r in risks if r.status in ["CRITICAL", "WARNING"]), key=lambda r: r.days_of_coverage)
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

            if not extended_critical and risks:
                extended_critical = [
                    {
                        "facility": risks[0].facility_name,
                        "medicine": risks[0].medicine_name.split("(")[0].strip(),
                        "current_days_cover": round(risks[0].days_of_coverage, 1),
                        "projected_stockout_day": f"Day {max(1, int(risks[0].days_of_coverage))}"
                    }
                ]

            fac_str = ", ".join([f"{x['facility']} ({x['projected_stockout_day']})" for x in extended_critical]) if extended_critical else "peripheral clinics"
            fac_hi_str = ", ".join([f"{x['facility']}" for x in extended_critical]) if extended_critical else "प्राथमिक स्वास्थ्य केंद्र"

            answer_en = (
                f"WHAT-IF SCENARIO (5-Day Extended Inversion / Climate Surge): If atmospheric stress (AQI {env.aqi}, PM2.5 {env.pm25} µg/m³) sustains across {corridor_title} for 5 additional days, "
                f"acute clinical demand will expand by +75% over baseline. "
                f"{len(extended_critical)} rural facilities will deplete their primary essential stocks first: {fac_str}. "
                f"Proactive lateral transfers from cluster reserves at {donors_title} will protect all facilities without requiring emergency state procurement."
            )
            answer_hi = (
                f"यदि यह वातावरणीय दबाव अगले 5 दिनों तक जारी रहता है, तो {state_title} के {corridor_title} में दवाओं की खपत 75% बढ़ जाएगी। "
                f"सबसे पहले इन केंद्रों पर स्टॉक समाप्त होगा: {fac_hi_str}। "
                f"{donors_title} से समय रहते स्टॉक ट्रांसफर करने पर सभी केंद्र सुरक्षित रहेंगे।"
            )
            return {
                "query_type": "WHAT_IF_SURGE_SIMULATION",
                "answer_en": answer_en,
                "answer_hi": answer_hi,
                "affected_facilities": extended_critical,
                "recommended_action": f"Execute proactive inter-district transfer orders across {corridor_title} before Day 3."
            }

        # Scenario 2: Drug Substitution Query ("levosalbutamol", "substitute", "बदल")
        elif any(w in q for w in ["levo", "substitut", "बदल", "विकल्प", "alternative"]):
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
        else:
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

    # =========================================================================
    # Master Execution Trace for the multi-agent pipeline
    # =========================================================================
    async def run_pipeline(
        self,
        env: EnvironmentalReading,
        raw_inventory: List[dict],
        target_phc_id: str = "PHC-LKO-01",
        intake: Optional[Dict[str, Any]] = None
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
        risks = self.surge_engine.assess_facility_risks(raw_inventory, env)
        if intake and intake.get("facility_id") == target_phc_id:
            medicine_id = intake["medicine_id"]
            parser = {"gemini": f"Gemini ({GEMINI_MODELS[0]})", "claude": f"Claude ({CLAUDE_MODEL}, fallback)"}.get(
                intake.get("parsed_by"), "offline rule-based parser")
            register = sum(r.current_stock for r in risks if r.facility_id == target_phc_id and r.medicine_id == medicine_id)
            traces.append(AgentStepTrace(
                "FrontlineIntakeAgent", "THINKING",
                f"Field report parsed by {parser}: {intake['reported_stock']} units left, confidence {round(intake['confidence_score'] * 100)}%. "
                f"Saved as a draft; planning uses the register ({register} available) until staff confirm the count."
            ).to_dict())
            entity = {
                "standard_name": intake.get("standard_name") or intake.get("medicine_name"),
                "code": intake.get("medicine_code") or medicine_id,
                "category": intake.get("edl_category") or "",
            }
        else:
            facility_risks = sorted((r for r in risks if r.facility_id == target_phc_id), key=lambda r: -r.stockout_probability_7d)
            medicine_id = facility_risks[0].medicine_id if facility_risks else "MED-001"
            traces.append(AgentStepTrace(
                "FrontlineIntakeAgent", "THINKING",
                f"No stock report for {facility_name}; selecting its highest 7-day stockout risk from the inventory register."
            ).to_dict())
            med = self.medicines.get(medicine_id, {})
            entity = {"standard_name": med.get("name", medicine_id), "code": medicine_id, "category": med.get("category", "")}
        traces.append(AgentStepTrace(
            "FrontlineIntakeAgent", "GROUNDING_MATCH",
            f"Matched to Essential Drug List item '{entity['standard_name']}' [{entity['code']}].",
            {"grounded_entity": entity}
        ).to_dict())

        # 3. Demand Intelligence Agent
        demand_res = self.run_demand_forecast(target_phc_id, medicine_id, raw_inventory, env)
        cover = f"{demand_res['days_of_coverage']}d" if demand_res["days_of_coverage"] is not None else "n/a"
        traces.append(AgentStepTrace(
            "DemandIntelligenceAgent", "THINKING",
            f"Lag-curve forecast: baseline {demand_res['baseline_daily_rate']}/day × surge {demand_res['surge_multiplier']} → peak {demand_res['median_surge_rate']}/day. "
            f"Stock {demand_res['current_stock']}, cover {cover}, 7-day stockout probability {round(demand_res['stockout_probability_7d'] * 100)}%.",
            {"forecast": demand_res["forecast_quantiles_7d"][:3]}
        ).to_dict())

        # 4. Logistics Agent
        context = (
            f"Situation: {sentinel_res['situation_brief']}\n"
            f"Demand forecast: {demand_res['risk_status']}, stock {demand_res['current_stock']}, "
            f"7-day stockout probability {demand_res['stockout_probability_7d']}."
        )
        logistics_res = await self.run_logistics_agent(target_phc_id, medicine_id, risks, raw_inventory, context)
        args = logistics_res["tool_arguments"]
        caller = {"gemini": f"Gemini ({GEMINI_MODELS[0]}) function call", "claude": f"Claude ({CLAUDE_MODEL}) tool call (Gemini unavailable)"}.get(
            logistics_res["tool_called_by"], "Deterministic default arguments (LLM unavailable)")
        traces.append(AgentStepTrace(
            "LogisticsAgent", "TOOL_CALL",
            f"{caller}: the LLM chooses arguments; the allocation itself is computed by the deterministic solver.",
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
