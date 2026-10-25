# Aarogya-Vāyu: Hackathon Submission Brief & Pitch Kit
### *Build with AI: Code for Communities (2nd Edition) — Track 3: Smart Health & Supply Chain Resilience*

> **Revised 24 Oct 2026 for the finale.** The first version of this brief (and the submitted video) named
> Google Earth Engine, Sentinel-5P, Cloud Speech-to-Text v2, Vertex AI, Google ADK, a SciPy LP solver and
> Gemma edge models. None of those are in the code. This version describes only what the deployed app does;
> anything planned is marked **Roadmap**.

---

## 📋 Table of Contents
1. [Executive Summary (The 60-Second Elevator Pitch)](#1-executive-summary)
2. [The 3-Minute Live Demo Script](#2-the-3-minute-live-demo-script)
3. [7-Slide Presentation Deck Outline](#3-7-slide-presentation-deck-outline)
4. [Impact Model (Projections, Not Measurements)](#4-impact-model-projections-not-measurements)
5. [Anticipated Judge Q&A Defense](#5-anticipated-judge-qa-defense)

---

## 1. Executive Summary

**Project Name:** Aarogya-Vāyu (आरोग्य-वायु)  
**Track:** Track 3: Smart Health & Supply Chain Resilience  
**Tagline:** *Predicting rural health stockouts before the climate surge arrives.*

### The Problem
In rural India, Primary Health Centre (PHC) medicine availability hovers between **17% and 51%**, with stockouts lasting **4 to 14 weeks**. When winter smog blankets agricultural corridors or summer heatwaves strike, acute respiratory illnesses and heatstroke surge within days. Existing government systems (e-Aushadhi / DVDMS) rely on backward-looking monthly indent cycles and offer no horizontal inter-facility coordination. As a result, one clinic turns away breathless children while a neighbouring clinic 30 km away sits on surplus stock that will expire into bio-waste.

### The Solution
Aarogya-Vāyu is a multi-agent decision support system that links **live environmental telemetry** (Open-Meteo weather + Copernicus CAMS air quality, NASA FIRMS fire hotspots when keyed) with **frontline multilingual voice reporting** (Google Gemini 3.8 Flash transcribes and parses Hindi, Odia and English voice notes). It converts air quality and heat into surge multipliers, projects days of cover for each clinic and medicine, and uses a **deterministic constrained allocator** to propose surplus-to-deficit transfers within 35 km. Every transfer needs CMO sign-off and is written to a hash-chained audit ledger.

**What is AI and what is maths:** Gemini does the language and perception work (voice transcription, report parsing, function calling, shelf-photo reading, CMO answers), with Claude Haiku 5.5 as a text fallback. Quantities are never chosen by a model: the allocator computes them, and the model can only call it.

---

## 2. The 3-Minute Live Demo Script

The **Conditions** choice is per browser, so your demo can't be disturbed by judges clicking on their own laptops. Start on **📡 Live today**, switch to **🌫️ Smog (demo)** for the walkthrough.

| Timecode | On Screen | Spoken Script |
| :--- | :--- | :--- |
| **0:00 - 0:25** | Dashboard, Lucknow region, live AQI card. | *"Every winter across northern India, stubble fires and thermal inversions push air quality into the hazardous zone. The crisis shows up days later inside rural PHCs: respiratory cases climb and nebuliser solution runs out. Clinics order on monthly cycles. They cannot see the surge coming."* |
| **0:25 - 0:55** | Live telemetry panel (AQI, PM2.5, boundary-layer height, 72 h forecast), then click **Smog**. PHC Kakori turns red. | *"This is live data from Copernicus CAMS through Open-Meteo: AQI, PM2.5, aerosol optical depth and boundary-layer height, which tells us when pollution is trapped near the ground. Our surge engine turns that into demand multipliers. In this smog scenario, salbutamol demand rises 1.62×, and PHC Kakori has 15 respules left: half a day of cover."* |
| **0:55 - 1:30** | Click the mic, speak a Hindi stock report (or play the sample). The transcript appears, then the parsed draft. | *"A nurse doesn't learn a desktop ERP. She records a voice note in Hindi. Gemini transcribes it, extracts the facility, medicine and count, and grounds 'साँस की दवाई' to Salbutamol 2.5 mg on the state Essential Drug List. If she doesn't say a number, the system says so and asks her to confirm, rather than inventing one."* |
| **1:30 - 2:05** | Click **Run Agent Pipeline**. The console shows the Gemini function call and the allocator's answer. | *"Now the agents work. Gemini decides to call our transfer tool, but it never picks the quantity. A deterministic allocator searches every facility within 35 km, keeps a 14-day reserve at the donor, and sends the batch closest to expiry first. Here it finds a CHC that can spare stock and lifts Kakori from half a day to over a week of cover."* |
| **2:05 - 2:35** | Approve the transfer, open the challan, then the audit ledger and **Verify**. | *"No medicine moves without a human. The CMO reviews a bilingual action card and approves. A dispatch challan is generated, and every step goes into a SHA-256 hash-chained ledger. Edit any past record and verification fails."* |
| **2:35 - 3:00** | Ask the CMO advisor: "Which clinics will run out first?" | *"Finally, the CMO can ask questions in plain language. The answer uses only the system's own figures. No new hardware, an overlay on e-Aushadhi rather than a replacement, so that when the next climate shock hits rural India, the medicine is already on its way."* |

---

## 3. 7-Slide Presentation Deck Outline

### Slide 1: Title & The Vision
- **Header:** Aarogya-Vāyu (आरोग्य-वायु)
- **Subheader:** Climate-aware medicine redistribution for rural health centres
- **Key Badges:** Build with AI: Code for Communities • Track 3: Smart Health & Supply Chain Resilience.

### Slide 2: The Ground Reality & Paradox
- **Key Stat:** 17%–51% medicine availability in rural clinics; 4–14 week stockout duration.
- **The Paradox:** PHC Kakori is down to 15 salbutamol respules while a CHC within 35 km holds stock it can spare.
- **The Core Flaw:** backward-looking indents, no horizontal coordination, no climate early warning.

### Slide 3: The Causal Resilience Loop
- **Flow:** Live air quality & heat → surge multipliers → days-of-cover projection → voice stock reports → constrained allocator → CMO approval → dispatch & audit.
- **Core Principle:** maths for quantities; AI for language, perception and reasoning.

### Slide 4: Multi-Agent Architecture (Python orchestrator)
- *Environmental Sentinel:* Open-Meteo + Copernicus CAMS (live, 30-day history, 72 h forecast); NASA FIRMS when keyed.
- *Frontline Intake:* Gemini 3.8 Flash audio transcription + structured parsing, grounded to the state EDL.
- *Demand Forecaster:* rule-based surge engine (climate multipliers × baseline consumption → days of cover, 7-day stockout probability).
- *Logistics Agent:* Gemini function calling → deterministic constrained allocator (35 km, 14-day donor reserve, FEFO).
- *Governance:* SHA-256 hash-chained audit ledger, bilingual action cards, human approval.

### Slide 5: The Interactive Dashboard (Live Demonstration)
- Two regions: Lucknow/Unnao (UP) and Khordha/Cuttack (Odisha), 20 facilities each.
- Clinic desk: stock actions, dispatch, receipt, reconciliation.
- Pipeline console showing the Gemini function call and the allocator result.
- Shelf-photo check: Gemini counts units in a photo and compares them with the register.

### Slide 6: Impact Model & Policy Alignment
- **Coverage of the demo dataset:** 40 facilities across two states (synthetic inventory).
- **Mechanism:** surplus near-expiry stock moves to clinics about to run out, before the surge peaks.
- **Policy Alignment:** National Health Mission (NHM), Ayushman Bharat Health & Wellness Centres, Digital India, DPDP Act 2023 (no patient data handled).

### Slide 7: Scalability & Implementation Roadmap
- **Phase 1:** Pilot on one district's real e-Aushadhi stock export, read-only.
- **Phase 2:** e-Aushadhi / DVDMS API integration; real login and role-based signing.
- **Phase 3:** Indo-Gangetic smog and pre-monsoon heatwave districts; learned demand forecast once enough real consumption history exists.

---

## 4. Impact Model (Simulation and Projections, Not Field Measurements)

**Simulation** (`scripts/simulate_impact.py`; the app's own engine and allocator on its 40 sample clinics, 20 runs, no store deliveries inside the window):

| Surge window | Smog, Lucknow-Unnao | Heatwave, Bhubaneswar-Cuttack |
|---|:-:|:-:|
| First 7 days | **−42%** clinic-days out of stock, −32% doses missed | **−83%** clinic-days, −69% doses missed |
| First 14 days | −6% / −5% | −32% / −21% |
| First 21 days | −1% | −7% |

Transfers prevent most stockouts in the first week. After about two weeks the whole district is short and needs resupply, which the app flags as unmet demand.

**Running cost:** about $10 (under ₹1,000) a month per 20-clinic district at published Gemini prices (estimate; prices double from Jan 2027).

These remain assumptions to validate in a pilot:
1. **Fewer climate-surge stockouts:** transfers are proposed while a clinic still has days of cover, not after it hits zero.
2. **Less expiry waste:** donors send the batch nearest expiry first, so stock that would expire is used.
3. **Low transport cost:** transfers stay within 35 km and can use existing 108/102 ambulance return trips.
4. **Less reporting time:** a voice note replaces manual data entry for a stock update.

---

## 5. Anticipated Judge Q&A Defense

#### Q1: "Why use a solver instead of letting Gemini decide the transfer amounts?"
**Answer:** LLMs are strong at language and tool orchestration but unreliable at multi-constraint arithmetic. A wrong quantity could cause a second stockout at the donor. So Gemini calls `calculate_optimal_transfer` with the facility and medicine, and a deterministic allocator computes the quantity under hard rules: 35 km radius, 14-day reserve at the donor, earliest expiry first. The model cannot change those limits.

#### Q2: "What happens if a rural PHC has no internet connectivity?"
**Answer:** Today: if the AI services are unreachable, a rule-based parser still reads typed reports and flags anything it had to guess, and the browser's own speech recogniser is used when recording isn't supported. **Roadmap:** an on-device model for offline transcription, queued sync when the network returns, and SMS alerts for critical stockouts.

#### Q3: "Does this require replacing India's existing e-Aushadhi / DVDMS software?"
**Answer:** No. Aarogya-Vāyu is designed as a decision-support overlay. It would read facility lists and stock balances from e-Aushadhi exports or APIs and return proposed transfers for approval. The current demo uses synthetic inventory because no public stock API exists.

#### Q4: "How does the system ensure data privacy and prevent unauthorized medicine diversion?"
**Answer:**
1. **No patient data:** only aggregate facility stock and batch codes.
2. **Tamper-evident ledger:** every stock action, voice report, approval and dispatch is SHA-256 hash-chained; editing any past entry breaks verification. It is not digitally signed yet, so it proves tampering, not who did it.
3. **Human approval:** no transfer moves without approval. The demo simulates roles; a pilot would add real login and role-based signing.

#### Q5: "Is the forecast a trained model?"
**Answer:** No, deliberately. It is a transparent rule-based surge engine: climate multipliers applied to baseline consumption, giving days of cover and a 7-day stockout probability. Training a model needs real consumption history, which a pilot would provide.

#### Q6: "Where do the multipliers (×1.62 etc.) come from?"
**Answer:** They are planning assumptions, and we checked them against the literature. The direction and timing are well supported: a meta-analysis of 37 studies finds asthma ER visits rise about 2.3% per 10 µg/m³ PM2.5, strongest 1–3 days later (Zheng 2015, *PLoS ONE*), and Indian ambulance data shows a same-day rise lasting about a week (Kawano 2026, *npj Clean Air*). Our top smog bands are higher than Delhi ER data, where children's respiratory visits rose 21–29% on polluted days (Yadav 2021, AIIMS). So they err toward warning early; a pilot would calibrate them against real consumption. Heat multipliers follow the 2010 Ahmedabad heatwave mortality ratio (×1.76–2.12); no study measures ORS demand directly.

#### Q7: "Does it actually reduce stockouts?"
**Answer:** In simulation on our sample clinics: 42% fewer clinic-days out of stock in the first week of a smog surge, 83% in a heatwave. It also shows the limit honestly: after about two weeks the whole district is short, redistribution stops helping, and the app escalates unmet demand for resupply. Field evidence needs a pilot.

#### Q8: "Is this really multi-agent?"
**Answer:** It is a pipeline of five specialised steps. The genuinely AI decisions are Gemini's: reading voice and photos, answering questions, and deciding to call the transfer tool. Quantities come from a deterministic allocator by design, because a wrong number in healthcare can cause a second stockout.

#### Q9: "What does it cost?"
**Answer:** About $10 (under ₹1,000) a month for a 20-clinic district at Google's published Gemini prices: voice reports, transfer checks, CMO questions, read-aloud and photo checks. It runs on existing phones and needs no new hardware.
