import os
import sys
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from pptx.dml.color import RGBColor

OUT_DIR = "/home/ritesh/Downloads"
PPTX_PATH = os.path.join(OUT_DIR, "Aarogya_Vayu_Pitch_Deck.pptx")

# Light & Vibrant Dashboard Theme Colors
BG_LIGHT = RGBColor(248, 250, 252)       # #F8FAFC Clean Soft Slate Canvas
CARD_BG = RGBColor(255, 255, 255)        # #FFFFFF Pure White Floating Card
CARD_BORDER = RGBColor(226, 232, 240)    # #E2E8F0 Clean Slate Border
TEXT_HEAD = RGBColor(15, 23, 42)         # #0F172A Deep Slate 900
TEXT_BODY = RGBColor(51, 65, 85)         # #334155 Slate 700
TEXT_MUTED = RGBColor(100, 116, 139)     # #64748B Slate 500
TERRACOTTA = RGBColor(222, 107, 72)      # #DE6B48 Primary Brand Coral
EMERALD = RGBColor(5, 150, 105)          # #059669 Vibrant Emerald
AMBER = RGBColor(217, 119, 6)            # #D97706 Vibrant Amber
BLUE_ACCENT = RGBColor(37, 99, 235)      # #2563EB Google Royal Blue
RED_ALERT = RGBColor(220, 38, 38)        # #DC2626 Critical Alert Red
LIGHT_GREEN_BG = RGBColor(236, 253, 245) # Soft Emerald Tint
LIGHT_AMBER_BG = RGBColor(254, 243, 199) # Soft Amber Tint
LIGHT_BLUE_BG = RGBColor(239, 246, 255)  # Soft Blue Tint

# Real Project Screenshots
SHOT_DIR = "/home/ritesh/aarogya_vayu/screenshots"
IMG_DASHBOARD = os.path.join(SHOT_DIR, "proj_dashboard_overview.png")
IMG_FACILITY = os.path.join(SHOT_DIR, "proj_facility_command_center.png")
IMG_TERMINAL = os.path.join(SHOT_DIR, "proj_agent_pipeline_console.png")
IMG_CHALLAN = os.path.join(SHOT_DIR, "proj_official_transfer_challan.png")
IMG_GIS_MAP = os.path.join(SHOT_DIR, "proj_facility_map.png")
IMG_CMO_STUDIO = os.path.join(SHOT_DIR, "proj_cmo_ai_studio.png")
IMG_VISION = os.path.join(SHOT_DIR, "proj_vision_ocr_verification.png")
IMG_LEDGER = os.path.join(SHOT_DIR, "proj_cryptographic_ledger.png")
IMG_IMPACT = os.path.join(os.path.dirname(SHOT_DIR), "docs", "impact.png")

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
blank_slide_layout = prs.slide_layouts[6]

def set_slide_background(slide):
    bg_shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(7.5)
    )
    bg_shape.fill.solid()
    bg_shape.fill.fore_color.rgb = BG_LIGHT
    bg_shape.line.fill.background()
    return bg_shape

def add_header(slide, tag, title, subtitle=None):
    tag_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.35), Inches(11.7), Inches(0.35))
    tf_tag = tag_box.text_frame
    tf_tag.word_wrap = True
    tf_tag.margin_left = tf_tag.margin_top = tf_tag.margin_right = tf_tag.margin_bottom = 0
    p_tag = tf_tag.paragraphs[0]
    p_tag.text = tag.upper()
    p_tag.font.size = Pt(11)
    p_tag.font.bold = True
    p_tag.font.color.rgb = TERRACOTTA
    
    title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.68), Inches(11.7), Inches(0.65))
    tf_title = title_box.text_frame
    tf_title.word_wrap = True
    tf_title.margin_left = tf_title.margin_top = tf_title.margin_right = tf_title.margin_bottom = 0
    p_title = tf_title.paragraphs[0]
    p_title.text = title
    p_title.font.size = Pt(22)
    p_title.font.bold = True
    p_title.font.color.rgb = TEXT_HEAD
    
    if subtitle:
        p_sub = tf_title.add_paragraph()
        p_sub.text = subtitle
        p_sub.font.size = Pt(11.5)
        p_sub.font.color.rgb = TEXT_MUTED

def add_card(slide, left, top, width, height, bg_color=CARD_BG, border_color=CARD_BORDER, corner_radius=0.025):
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    card.fill.solid()
    card.fill.fore_color.rgb = bg_color
    if hasattr(card, "adjustments") and len(card.adjustments) > 0:
        card.adjustments[0] = corner_radius
    if border_color:
        card.line.color.rgb = border_color
        card.line.width = Pt(1.5)
    else:
        card.line.fill.background()
    return card

def add_image_card(slide, left, top, width, height, img_path, title, caption=None, border_color=CARD_BORDER):
    card = add_card(slide, left, top, width, height, bg_color=CARD_BG, border_color=border_color, corner_radius=0.025)
    
    tb = slide.shapes.add_textbox(left + Inches(0.2), top + Inches(0.14), width - Inches(0.4), Inches(0.32))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.text = title.upper()
    p.font.size = Pt(10)
    p.font.bold = True
    p.font.color.rgb = TERRACOTTA
    
    img_w = width - Inches(0.4)
    img_h = img_w * (9.0 / 16.0)
    
    if os.path.exists(img_path):
        slide.shapes.add_picture(img_path, left + Inches(0.2), top + Inches(0.48), img_w, img_h)
    
    if caption:
        caption_top = top + Inches(0.55) + img_h
        caption_h = height - (caption_top - top) - Inches(0.12)
        tb_c = slide.shapes.add_textbox(left + Inches(0.2), caption_top, width - Inches(0.4), caption_h)
        tf_c = tb_c.text_frame
        tf_c.word_wrap = True
        tf_c.margin_left = tf_c.margin_top = tf_c.margin_right = tf_c.margin_bottom = 0
        p_c = tf_c.paragraphs[0]
        p_c.text = caption
        p_c.font.size = Pt(9.5)
        p_c.font.color.rgb = TEXT_MUTED

# ==============================================================================
# SLIDE 1: Cover Slide (Clean Light Interactive Theme + Live App Preview)
# ==============================================================================
slide1 = prs.slides.add_slide(blank_slide_layout)
set_slide_background(slide1)

left_card = add_card(slide1, Inches(0.8), Inches(0.8), Inches(5.8), Inches(5.9), bg_color=CARD_BG, border_color=CARD_BORDER, corner_radius=0.025)
tb1 = slide1.shapes.add_textbox(Inches(1.1), Inches(1.05), Inches(5.2), Inches(5.4))
tf1 = tb1.text_frame
tf1.word_wrap = True

p = tf1.paragraphs[0]
p.text = "BUILD WITH AI: CODE FOR COMMUNITIES (2ND EDITION)"
p.font.size = Pt(10)
p.font.bold = True
p.font.color.rgb = BLUE_ACCENT
p.space_after = Pt(8)

p = tf1.add_paragraph()
p.text = "Aarogya-Vāyu\n(आरोग्य-वायु)"
p.font.size = Pt(32)
p.font.bold = True
p.font.color.rgb = TEXT_HEAD
p.space_after = Pt(8)

p = tf1.add_paragraph()
p.text = "Atmosphere-Aware Autonomous Health Logistics & Supply Chain Intelligence"
p.font.size = Pt(13)
p.font.bold = True
p.font.color.rgb = TERRACOTTA
p.space_after = Pt(14)

p = tf1.add_paragraph()
p.text = "• Challenge Track: Track 3 — Smart Health & Supply Chain Resilience\n" \
         "• System Architect: Ritesh Kumar Mahato (Solo Participant)\n" \
         "• Dual Corridors: Bhubaneswar–Cuttack (Odisha, Default) & Lucknow–Unnao (UP)\n" \
         "• Live Web App: https://aarogya-vayu.vercel.app\n" \
         "• Demo Video: https://youtu.be/D8w2qviTuW4\n" \
         "• GitHub Repository: https://github.com/Ritesh-Root/aarogya-vayu\n" \
         "• Google AI: Gemini 3.8 Flash (language, function calling, audio, vision) • Data: Copernicus CAMS via Open-Meteo"
p.font.size = Pt(10)
p.font.color.rgb = TEXT_BODY
p.space_after = Pt(12)

p = tf1.add_paragraph()
p.text = "LIVE SYSTEM DEMONSTRATION & PRODUCTION PITCH"
p.font.size = Pt(11)
p.font.bold = True
p.font.color.rgb = EMERALD

add_image_card(
    slide1, 
    Inches(6.8), Inches(0.8), Inches(5.7), Inches(5.9), 
    IMG_DASHBOARD, 
    "Live Production Interface — Civic Command Center",
    "Figure 1: Aarogya-Vāyu command center (FastAPI + Leaflet) with live Copernicus CAMS air quality, transfer recommendations and the stockout watch."
)

# ==============================================================================
# SLIDE 2: The Problem & Ground Reality (Real Facility Telemetry)
# ==============================================================================
slide2 = prs.slides.add_slide(blank_slide_layout)
set_slide_background(slide2)
add_header(slide2, "01 / THE CRISIS & GROUND REALITY", "The Rural Stockout Paradox & Climate Shocks", "Why static supply chains fail under Indo-Gangetic smog inversions")

card_stat = add_card(slide2, Inches(0.8), Inches(1.45), Inches(5.7), Inches(5.5), bg_color=CARD_BG, border_color=CARD_BORDER, corner_radius=0.025)
tb_s = slide2.shapes.add_textbox(Inches(1.05), Inches(1.65), Inches(5.2), Inches(5.1))
tf_s = tb_s.text_frame
tf_s.word_wrap = True

p = tf_s.paragraphs[0]
p.text = "THE GROUND PARADOX IN UTTAR PRADESH"
p.font.size = Pt(11)
p.font.bold = True
p.font.color.rgb = RED_ALERT
p.space_after = Pt(10)

stats = [
    ("17% – 51%", "Baseline availability of critical respiratory medicines (Salbutamol, Dexamethasone) in rural primary health centres.", RED_ALERT),
    ("4 – 14 Weeks", "Typical duration of a stockout at a rural PHC under monthly indent cycles.", AMBER),
    ("+30% – 50%", "Surge in acute respiratory admissions during winter boundary-layer smog trapping events across the Gangetic belt.", TERRACOTTA),
    ("No Climate Signal", "Clinics rely on static monthly quotas with no link to air quality or heat forecasts.", TEXT_HEAD)
]

for val, desc, col in stats:
    p = tf_s.add_paragraph()
    p.text = val
    p.font.size = Pt(17)
    p.font.bold = True
    p.font.color.rgb = col
    
    p = tf_s.add_paragraph()
    p.text = desc
    p.font.size = Pt(10)
    p.font.color.rgb = TEXT_BODY
    p.space_after = Pt(6)

add_image_card(
    slide2, 
    Inches(6.8), Inches(1.45), Inches(5.7), Inches(5.5), 
    IMG_FACILITY, 
    "Facility View — PHC Kakori (Smog Scenario)",
    "Figure 2: Facility view in the smog scenario (AQI 385): PHC Kakori is down to 15 salbutamol respules, 0.5 days of cover (demo data)."
)

# ==============================================================================
# SLIDE 3: The Causal Resilience Loop (Architecture Pipeline)
# ==============================================================================
slide3 = prs.slides.add_slide(blank_slide_layout)
set_slide_background(slide3)
add_header(
    slide3, 
    "02 / THE SOLUTION ARCHITECTURE", 
    "The Causal Resilience Loop: From Atmosphere to Delivery", 
    "From live air-quality telemetry to an approved, audited medicine transfer"
)

steps = [
    ("1. SENSE", "Atmospheric Telemetry", 
     "• Live Copernicus CAMS air quality + Open-Meteo weather.\n"
     "• AQI, PM2.5, heat, rainfall and minimum temperature, 72h forecast.\n"
     "• NASA FIRMS fire hotspots when an API key is set.", 
     BLUE_ACCENT, LIGHT_BLUE_BG),
    
    ("2. FORECAST", "Rule-Based Surge Engine", 
     "• Smog, heat, floods and cold waves become demand multipliers per medicine.\n"
     "• Projects days of cover from baseline consumption × multiplier.\n"
     "• Outputs a 7-day stockout probability (transparent, no training data needed).", 
     AMBER, LIGHT_AMBER_BG),
    
    ("3. LISTEN", "Frontline Voice Intake", 
     "• Gemini 3.8 Flash transcribes Hindi, Odia and English voice notes.\n"
     "• Frontline ASHA/ANM workers report shelf stock in Hindi dialect.\n"
     "• Parsed and grounded to the state Essential Drug List; staff confirm.", 
     EMERALD, LIGHT_GREEN_BG),
    
    ("4. SOLVE", "Constrained Allocator", 
     "• Gemini function call → deterministic allocator picks the quantity.\n"
     "• Enforces 35 km ambulance radius & 14-day donor safety buffer.\n"
     "• Prioritizes near-expiry medicine batches to eliminate waste.", 
     TERRACOTTA, CARD_BG),
    
    ("5. GOVERN", "Human-in-the-Loop", 
     "• Chief Medical Officer approves every transfer.\n"
     "• Dispatch challan; every step in a SHA-256 hash-chained ledger.\n"
     "• Gemini vision checks shelf photos against the register.", 
     BLUE_ACCENT, LIGHT_BLUE_BG)
]

c_w = Inches(2.22)
c_h = Inches(4.0)
c_gap = Inches(0.15)
start_x = Inches(0.8)

for i, (num_tag, step_title, step_desc, col, bg_col) in enumerate(steps):
    x = start_x + i * (c_w + c_gap)
    add_card(slide3, x, Inches(1.45), c_w, c_h, bg_color=bg_col, border_color=CARD_BORDER, corner_radius=0.03)
    
    tb = slide3.shapes.add_textbox(x + Inches(0.12), Inches(1.6), c_w - Inches(0.24), c_h - Inches(0.3))
    tf = tb.text_frame
    tf.word_wrap = True
    
    p = tf.paragraphs[0]
    p.text = num_tag
    p.font.size = Pt(11)
    p.font.bold = True
    p.font.color.rgb = col
    p.space_after = Pt(2)
    
    p = tf.add_paragraph()
    p.text = step_title
    p.font.size = Pt(13)
    p.font.bold = True
    p.font.color.rgb = TEXT_HEAD
    p.space_after = Pt(8)
    
    p = tf.add_paragraph()
    p.text = step_desc
    p.font.size = Pt(9.5)
    p.font.color.rgb = TEXT_BODY

# Lower Architectural Integration Panel
card_flow = add_card(slide3, Inches(0.8), Inches(5.65), Inches(11.7), Inches(1.3), bg_color=CARD_BG, border_color=CARD_BORDER, corner_radius=0.02)
tb_fl = slide3.shapes.add_textbox(Inches(1.0), Inches(5.75), Inches(11.3), Inches(1.1))
tf_fl = tb_fl.text_frame
tf_fl.word_wrap = True

p = tf_fl.paragraphs[0]
p.text = "CLOSED LOOP, HUMAN IN CHARGE"
p.font.size = Pt(11)
p.font.bold = True
p.font.color.rgb = EMERALD
p.space_after = Pt(4)

p = tf_fl.add_paragraph()
p.text = "Live CAMS air quality ➔ Surge multipliers & days of cover ➔ Gemini voice & photo stock checks ➔ Deterministic allocator (35 km, 14-day reserve, FEFO) ➔ CMO approval, challan & hash-chained audit."
p.font.size = Pt(10)
p.font.color.rgb = TEXT_BODY

# ==============================================================================
# SLIDE 4: Multi-Agent Pipeline (Python orchestrator)
# ==============================================================================
slide4 = prs.slides.add_slide(blank_slide_layout)
set_slide_background(slide4)
add_header(
    slide4, 
    "03 / MULTI-AGENT ORCHESTRATION", 
    "Five Agents, One Auditable Pipeline", 
    "A Python orchestrator chains specialised agents and shows every step"
)

card_mesh = add_card(slide4, Inches(0.8), Inches(1.45), Inches(5.7), Inches(5.5), bg_color=CARD_BG, border_color=CARD_BORDER, corner_radius=0.025)
tb_m = slide4.shapes.add_textbox(Inches(1.05), Inches(1.65), Inches(5.2), Inches(5.1))
tf_m = tb_m.text_frame
tf_m.word_wrap = True

p = tf_m.paragraphs[0]
p.text = "THE 4 SPECIALISED AGENTS"
p.font.size = Pt(11)
p.font.bold = True
p.font.color.rgb = BLUE_ACCENT
p.space_after = Pt(8)

agents = [
    ("🛰️ Environmental Sentinel Agent", "Reads live Copernicus CAMS air quality and Open-Meteo weather (boundary layer, aerosol anomaly, rainfall, minimum temperature, 72h forecast) and flags smog, heatwaves, floods and cold waves using IMD thresholds.", BLUE_ACCENT),
    ("🎙️ Frontline Intake Agent", "Gemini 3.8 Flash transcribes nurses' voice notes and extracts facility, medicine and count, mapping colloquial terms ('सांस की दवाई') to state EDL codes.", EMERALD),
    ("📈 Demand Intelligence Agent", "Rule-based surge engine: climate multipliers × baseline consumption give days of cover and a 7-day stockout probability per clinic and medicine.", AMBER),
    ("📦 Logistics Redistribution Agent", "Gemini 3.8 Flash function calling invokes the deterministic allocator; the model cannot change the 35 km radius, the donor reserve or the quantity.", TERRACOTTA)
]

for ag_t, ag_d, ag_c in agents:
    p = tf_m.add_paragraph()
    p.text = ag_t
    p.font.size = Pt(12.5)
    p.font.bold = True
    p.font.color.rgb = ag_c
    
    p = tf_m.add_paragraph()
    p.text = ag_d
    p.font.size = Pt(9.5)
    p.font.color.rgb = TEXT_BODY
    p.space_after = Pt(6)

add_image_card(
    slide4, 
    Inches(6.8), Inches(1.45), Inches(5.7), Inches(5.5), 
    IMG_TERMINAL, 
    "Agent Pipeline Console",
    "Figure 3: Pipeline console showing each agent step, the Gemini function call (calculate_optimal_transfer) and the allocator's result."
)

# ==============================================================================
# SLIDE 5: AI & Data Stack (2x4 grid)
# ==============================================================================
slide5 = prs.slides.add_slide(blank_slide_layout)
set_slide_background(slide5)
add_header(
    slide5, 
    "04 / AI & DATA STACK", 
    "What Runs in the Deployed App", 
    "Gemini does the language and perception work; deterministic code does the maths"
)

g_tools = [
    ("⚡ Gemini 3.8 Flash: Reasoning & Function Calling",
     "• Parses stock reports into structured JSON with a fixed schema.\n"
     "• Function calling (`calculate_optimal_transfer`) hands the maths to the allocator.\n"
     "• CMO advisor answers only from the system's own figures, in English or Hindi.",
     TERRACOTTA),
    
    ("🎙️ Gemini 3.8 Flash: Speech-to-Text",
     "• Transcribes Hindi, Odia and English voice notes recorded in the browser.\n"
     "• Silent or too-short clips are rejected before they reach the model.\n"
     "• Browser speech recognition is the fallback when recording isn't supported.",
     EMERALD),
    
    ("📷 Gemini 3.8 Flash: Vision",
     "• Reads uploaded shelf photos: medicine, batch and visible unit count.\n"
     "• Compares the count with the stock register and flags discrepancies.\n"
     "• Partial counts are reported as partial, never as a match.",
     AMBER),
    
    ("🛡️ Resilience: Fallbacks",
     "• Gemini 3.5 Flash-Lite, then Claude Haiku 5.5, if the primary model fails.\n"
     "• Rule-based parser when no model is reachable; guesses are flagged.\n"
     "• Per-request time budget so the pipeline always answers.",
     BLUE_ACCENT),
    
    ("🛰️ Copernicus CAMS via Open-Meteo",
     "• Live AQI, PM2.5, aerosol optical depth and dust for each corridor.\n"
     "• Boundary-layer height to detect pollution trapped near the ground.\n"
     "• 30-day history and 72h forecast; no API key needed.",
     EMERALD),
    
    ("🔥 NASA FIRMS & News Signals",
     "• VIIRS fire hotspots near each corridor when a FIRMS key is set.\n"
     "• Google News RSS headlines tagged by keyword for situational awareness.\n"
     "• Every data source is labelled live, simulated or demo in the UI.",
     BLUE_ACCENT),
    
    ("📦 Deterministic Constrained Allocator",
     "• Most critical recipients first; donors by soonest expiry.\n"
     "• 35 km straight-line radius and a 14-day donor reserve are hard limits.\n"
     "• Explains every rejected donor; escalates unmet demand to the district.",
     AMBER),
    
    ("🔗 Hash-Chained Audit Ledger",
     "• Every stock action, approval, dispatch and AI query is SHA-256 chained.\n"
     "• One-click verification walks the whole chain.\n"
     "• Tamper-evident today; digital signatures are on the roadmap.",
     TERRACOTTA)
]

gw = Inches(5.7)
gh = Inches(1.22)
gx1, gx2 = Inches(0.8), Inches(6.8)
gy_start = Inches(1.45)
gy_gap = Inches(0.12)

for idx, (tool_name, tool_desc, tool_col) in enumerate(g_tools):
    col_x = gx1 if idx < 4 else gx2
    row_y = gy_start + (idx % 4) * (gh + gy_gap)
    
    add_card(slide5, col_x, row_y, gw, gh, bg_color=CARD_BG, border_color=CARD_BORDER, corner_radius=0.035)
    tb = slide5.shapes.add_textbox(col_x + Inches(0.18), row_y + Inches(0.08), gw - Inches(0.36), gh - Inches(0.16))
    tf = tb.text_frame
    tf.word_wrap = True
    
    p = tf.paragraphs[0]
    p.text = tool_name
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = tool_col
    p.space_after = Pt(2)
    
    p = tf.add_paragraph()
    p.text = tool_desc
    p.font.size = Pt(9.5)
    p.font.color.rgb = TEXT_BODY

g_badge = add_card(slide5, Inches(0.8), Inches(6.85), Inches(11.7), Inches(0.45), bg_color=LIGHT_GREEN_BG, border_color=EMERALD, corner_radius=0.04)
tb_gb = slide5.shapes.add_textbox(Inches(1.0), Inches(6.88), Inches(11.3), Inches(0.4))
tf_gb = tb_gb.text_frame
tf_gb.word_wrap = True
p = tf_gb.paragraphs[0]
p.text = "Deployed today: FastAPI on Vercel. Inventory is synthetic demo data; telemetry and AI calls are live."
p.font.size = Pt(11)
p.font.bold = True
p.font.color.rgb = EMERALD

# ==============================================================================
# SLIDE 6: Mathematical Optimization vs. LLM Hallucinations
# ==============================================================================
slide6 = prs.slides.add_slide(blank_slide_layout)
set_slide_background(slide6)
add_header(
    slide6, 
    "05 / MATHEMATICAL FOUNDATION", 
    "Why the Model Never Picks the Quantity", 
    "Gemini decides to call the tool; deterministic code computes the transfer"
)

card_lp = add_card(slide6, Inches(0.8), Inches(1.45), Inches(5.7), Inches(5.5), bg_color=CARD_BG, border_color=CARD_BORDER, corner_radius=0.025)
tb = slide6.shapes.add_textbox(Inches(1.05), Inches(1.65), Inches(5.2), Inches(5.1))
tf = tb.text_frame
tf.word_wrap = True

p = tf.paragraphs[0]
p.text = "THE OPTIMIZATION FORMULATION"
p.font.size = Pt(11)
p.font.bold = True
p.font.color.rgb = TERRACOTTA
p.space_after = Pt(6)

p = tf.add_paragraph()
p.text = "Greedy Constrained Allocation:"
p.font.size = Pt(13)
p.font.bold = True
p.font.color.rgb = TEXT_HEAD
p.space_after = Pt(4)

p = tf.add_paragraph()
p.text = "for recipient j by cover ↑ :  for donor i by expiry ↑ :  x_ij = min(need_j, surplus_i)"
p.font.size = Pt(11.5)
p.font.bold = True
p.font.color.rgb = EMERALD
p.space_after = Pt(10)

p = tf.add_paragraph()
p.text = "HARD OPERATIONAL CONSTRAINTS:\n\n" \
         "1. Transit Distance Constraint:\n" \
         "   d_ij ≤ 35 km (strictly within rural district ambulance transit radius).\n\n" \
         "2. Mandatory Donor Safety Buffer:\n" \
         "   Donor must retain ≥ 14 days of safety stock to prevent secondary stockouts.\n\n" \
         "3. First-Expiry-First-Out:\n" \
         "   Donors with batches nearest expiry give first, so stock is used, not wasted.\n\n" \
         "Every rejected donor is listed with the rule it failed; unmet demand is escalated."
p.font.size = Pt(10)
p.font.color.rgb = TEXT_BODY

add_image_card(
    slide6, 
    Inches(6.8), Inches(1.45), Inches(5.7), Inches(5.5), 
    IMG_CHALLAN, 
    "Dispatch Challan (Allocator Output)",
    "Figure 4: Dispatch challan generated after CMO approval, showing donor, recipient, batch, quantity and the ledger hash."
)

# ==============================================================================
# SLIDE 7: Live Product: Tactical GIS Map & Ambulance Fleet Tracking
# ==============================================================================
slide7 = prs.slides.add_slide(blank_slide_layout)
set_slide_background(slide7)
add_header(
    slide7, 
    "06 / PRODUCT DEMO — MAP & CLINIC DESK", 
    "Facility Map, Transfers & Clinic Desk", 
    "20 facilities per region, colour-coded by cover, with proposed transfer corridors"
)

card_ginfo = add_card(slide7, Inches(0.8), Inches(1.45), Inches(4.3), Inches(5.5), bg_color=CARD_BG, border_color=CARD_BORDER, corner_radius=0.025)
tb_gi = slide7.shapes.add_textbox(Inches(1.05), Inches(1.65), Inches(3.8), Inches(5.1))
tf_gi = tb_gi.text_frame
tf_gi.word_wrap = True

p = tf_gi.paragraphs[0]
p.text = "INTEGRATED GEOSPATIAL INTELLIGENCE"
p.font.size = Pt(11)
p.font.bold = True
p.font.color.rgb = BLUE_ACCENT
p.space_after = Pt(8)

g_points = [
    ("🏥 20 Geo-Tagged Facilities", "Live status pins across Lucknow & Unnao with color-coded coverage indicators (Red: <4d, Amber: <8d, Green: Healthy).", BLUE_ACCENT),
    ("🚚 Transfer Lifecycle", "Approve → reserve → dispatch → receive, with consignment status on the clinic desk and stock updated on receipt.", EMERALD),
    ("🌫️ Live Air-Quality HUD", "Live AQI, PM2.5, boundary-layer height and ventilation index from Copernicus CAMS, with a 72h forecast.", TERRACOTTA),
    ("🎙️ Frontline Multilingual Voice", "Nurses record a stock update in Hindi, Odia or English; Gemini transcribes and parses it into a draft for confirmation.", AMBER)
]

for gp_t, gp_d, gp_c in g_points:
    p = tf_gi.add_paragraph()
    p.text = gp_t
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = gp_c
    
    p = tf_gi.add_paragraph()
    p.text = gp_d
    p.font.size = Pt(9.5)
    p.font.color.rgb = TEXT_BODY
    p.space_after = Pt(6)

add_image_card(
    slide7, 
    Inches(5.3), Inches(1.45), Inches(7.2), Inches(5.5), 
    IMG_GIS_MAP, 
    "Facility Map & Transfer Corridors",
    "Figure 5: Leaflet map of facilities with proposed transfer corridors, the live air-quality HUD and frontline voice intake."
)

# ==============================================================================
# SLIDE 8: Live Product: CMO Strategic Studio & Vision OCR Verification
# ==============================================================================
slide8 = prs.slides.add_slide(blank_slide_layout)
set_slide_background(slide8)
add_header(
    slide8, 
    "07 / PRODUCT DEMO — CMO & VISION", 
    "CMO Strategic Studio & Gemini Vision Shelf Check", 
    "Grounded answers in plain language and photo-based stock verification"
)

add_image_card(
    slide8, 
    Inches(0.8), Inches(1.45), Inches(5.7), Inches(5.5), 
    IMG_CMO_STUDIO, 
    "CMO Strategic Studio (Gemini 3.8 Flash)",
    "Figure 6: CMO Strategic Studio: questions in plain language, answered only from the system's own stock, cover and transfer figures."
)

add_image_card(
    slide8, 
    Inches(6.8), Inches(1.45), Inches(5.7), Inches(5.5), 
    IMG_VISION, 
    "Gemini Vision Shelf Check",
    "Figure 7: Gemini reads a shelf photo, counts visible units and compares them with the stock register."
)

# ==============================================================================
# SLIDE 9: Civic Governance, Cryptographic Ledger & Measurable Impact
# ==============================================================================
slide9 = prs.slides.add_slide(blank_slide_layout)
set_slide_background(slide9)
add_header(
    slide9, 
    "08 / GOVERNANCE & IMPACT", 
    "Cryptographic Audit Ledger & Quantifiable Impact", 
    "Tamper-evident records and the outcomes a pilot would measure"
)

add_image_card(
    slide9, 
    Inches(0.8), Inches(1.45), Inches(5.7), Inches(5.5), 
    IMG_LEDGER, 
    "Tamper-Evident Cryptographic Audit Ledger",
    "Figure 8: SHA-256 hash-chained log of pipeline runs, approvals, CMO queries and vision scans; editing any entry breaks verification."
)

card_imp = add_card(slide9, Inches(6.8), Inches(1.45), Inches(5.7), Inches(5.5), bg_color=CARD_BG, border_color=CARD_BORDER, corner_radius=0.025)
tb_i = slide9.shapes.add_textbox(Inches(7.05), Inches(1.65), Inches(5.2), Inches(5.1))
tf_i = tb_i.text_frame
tf_i.word_wrap = True

p = tf_i.paragraphs[0]
p.text = "WHAT A PILOT WOULD MEASURE"
p.font.size = Pt(11)
p.font.bold = True
p.font.color.rgb = EMERALD
p.space_after = Pt(8)

imp_metrics = [
    ("40 Facilities, 2 States", "Demo dataset across Lucknow–Unnao (UP) and Khordha–Cuttack (Odisha); inventory is synthetic.", EMERALD),
    ("Stockout Days Avoided", "Transfers proposed while clinics still have days of cover, before the surge peaks.", TERRACOTTA),
    ("Expiry Waste Avoided", "Donors send the batch nearest expiry first, so stock is used instead of incinerated.", AMBER),
    ("No Patient Data", "Only aggregate facility stock and batch codes, in line with the DPDP Act 2023.", BLUE_ACCENT)
]

for m_v, m_d, m_c in imp_metrics:
    p = tf_i.add_paragraph()
    p.text = m_v
    p.font.size = Pt(15)
    p.font.bold = True
    p.font.color.rgb = m_c
    
    p = tf_i.add_paragraph()
    p.text = m_d
    p.font.size = Pt(9.5)
    p.font.color.rgb = TEXT_BODY
    p.space_after = Pt(4)

# ==============================================================================
# SLIDE 10: Climate hazards and the medicines they drive
# ==============================================================================
slide_hz = prs.slides.add_slide(blank_slide_layout)
set_slide_background(slide_hz)
add_header(
    slide_hz,
    "09 / CLIMATE HAZARDS",
    "Each Weather Shock Raises Different Medicines",
    "Live from Open-Meteo + Copernicus CAMS; thresholds from IMD; multipliers checked against published studies"
)
add_card(slide_hz, Inches(0.8), Inches(1.45), Inches(11.7), Inches(5.55), bg_color=CARD_BG, border_color=CARD_BORDER, corner_radius=0.025)
hz_rows = [
    ("Medicine", "Smog\n(AQI 385)", "Heatwave", "Flood\n(very heavy / extreme rain)", "Cold wave\n(≤ 4 °C / ≤ 2 °C)"),
    ("Salbutamol (nebuliser)", "×1.62", "—", "—", "×1.15 / ×1.3"),
    ("Dexamethasone (injection)", "×1.62", "—", "—", "×1.15 / ×1.3"),
    ("Cetirizine", "×1.62", "—", "—", "—"),
    ("Amoxicillin + clavulanate", "×1.53", "—", "—", "×1.25 / ×1.5"),
    ("Paracetamol IV (fever)", "×1.43", "×1.60", "×1.2 / ×1.4", "×1.15 / ×1.3"),
    ("ORS (rehydration)", "—", "×1.75+", "×1.5 / ×2.0", "—"),
]
tbl = slide_hz.shapes.add_table(len(hz_rows), 5, Inches(1.1), Inches(1.7), Inches(11.1), Inches(3.6)).table
for col, width in enumerate((3.3, 1.7, 1.7, 2.3, 2.1)):
    tbl.columns[col].width = Inches(width)
HEAD_BG = RGBColor(253, 236, 228)
for r, row in enumerate(hz_rows):
    for c, value in enumerate(row):
        cell = tbl.cell(r, c)
        cell.text = value
        cell.fill.solid()
        cell.fill.fore_color.rgb = HEAD_BG if r == 0 else (RGBColor(255, 255, 255) if r % 2 else RGBColor(248, 250, 252))
        for para in cell.text_frame.paragraphs:
            para.alignment = PP_ALIGN.LEFT if c == 0 else PP_ALIGN.CENTER
            for run in para.runs:
                run.font.size = Pt(12 if r else 11)
                run.font.bold = (r == 0 or c == 0 or (value.startswith("×") and value not in ("×1.0",)))
                run.font.color.rgb = TEXT_HEAD if (r == 0 or c == 0) else (TERRACOTTA if value.startswith("×") else TEXT_MUTED)
tb_h = slide_hz.shapes.add_textbox(Inches(1.1), Inches(5.5), Inches(11.1), Inches(1.4))
tf_h = tb_h.text_frame
tf_h.word_wrap = True
tf_h.margin_left = tf_h.margin_top = tf_h.margin_right = tf_h.margin_bottom = 0
notes = [
    ("Thresholds (IMD SOP): ", "very heavy rain 115.6 mm and extremely heavy 204.5 mm in 24 h; cold wave on the plains at ≤ 4 °C, severe at ≤ 2 °C."),
    ("Evidence: ", "smog — Zheng 2015 meta-analysis, Yadav 2021 AIIMS Delhi (our top smog bands are higher than Delhi ER data); "
                   "floods — Bush 2014 Chennai (×1.6 gut illness), Hashizume 2008 Dhaka (×2 diarrhoea); "
                   "cold — Feng 2023, Wu 2024 (China; no Indian study exists)."),
    ("Next: ", "dengue and malaria, which peak 1–3 months after the monsoon."),
]
for k, (label, text) in enumerate(notes):
    p = tf_h.paragraphs[0] if k == 0 else tf_h.add_paragraph()
    r1 = p.add_run(); r1.text = label; r1.font.bold = True; r1.font.size = Pt(10); r1.font.color.rgb = TEXT_HEAD
    r2 = p.add_run(); r2.text = text; r2.font.size = Pt(10); r2.font.color.rgb = TEXT_BODY
    p.space_after = Pt(4)

# ==============================================================================
# SLIDE 10: Simulated impact (scripts/simulate_impact.py)
# ==============================================================================
slide_sim = prs.slides.add_slide(blank_slide_layout)
set_slide_background(slide_sim)
add_header(
    slide_sim,
    "10 / DOES IT HELP?",
    "Fewer Stockouts in the First Week of a Surge",
    "Simulation on the app's 40 sample clinics with its own engine and allocator (20 runs, no store deliveries in the window)"
)
add_card(slide_sim, Inches(0.8), Inches(1.45), Inches(11.7), Inches(5.55), bg_color=CARD_BG, border_color=CARD_BORDER, corner_radius=0.025)
if os.path.exists(IMG_IMPACT):
    pic_w = Inches(10.2)
    slide_sim.shapes.add_picture(IMG_IMPACT, Inches(0.8) + (Inches(11.7) - pic_w) // 2, Inches(1.6), pic_w)
tb_s = slide_sim.shapes.add_textbox(Inches(1.1), Inches(6.62), Inches(11.1), Inches(0.36))
tf_s = tb_s.text_frame
tf_s.word_wrap = True
tf_s.margin_left = tf_s.margin_top = tf_s.margin_right = tf_s.margin_bottom = 0
p = tf_s.paragraphs[0]
p.text = ("First 7 days: 42% fewer clinic-days out of stock (smog), 83% (heat). After ~2 weeks the district is short and needs resupply, "
          "which the app flags as unmet demand. Running cost ≈ $10 (under ₹1,000) a month per 20-clinic district. Sample data, not field results.")
p.font.size = Pt(10)
p.font.color.rgb = TEXT_BODY

# ==============================================================================
# SLIDE 10: Scalability Roadmap & Solo Developer Profile
# ==============================================================================
slide10 = prs.slides.add_slide(blank_slide_layout)
set_slide_background(slide10)
add_header(
    slide10, 
    "11 / ROADMAP & DEVELOPER", 
    "From Hackathon Prototype to National Infrastructure", 
    "Scalability milestones and solo developer credentials"
)

card_rd = add_card(slide10, Inches(0.8), Inches(1.45), Inches(5.7), Inches(5.5), bg_color=CARD_BG, border_color=CARD_BORDER, corner_radius=0.025)
tb = slide10.shapes.add_textbox(Inches(1.05), Inches(1.65), Inches(5.2), Inches(5.1))
tf = tb.text_frame
tf.word_wrap = True

p = tf.paragraphs[0]
p.text = "PHASED SCALABILITY ROADMAP"
p.font.size = Pt(11)
p.font.bold = True
p.font.color.rgb = TERRACOTTA
p.space_after = Pt(10)

phases = [
    ("Phase 1: Pilot Corridor (Month 1)", "Deploy live with Lucknow & Unnao District Health Societies (20 PHCs/CHCs). Evaluate live ASHA voice logging in Hindi.", EMERALD),
    ("Phase 2: State-Wide e-Aushadhi Integration (Months 2–4)", "Connect directly to Uttar Pradesh DVDMS/e-Aushadhi ERP databases to ingest live stock indents automatically.", BLUE_ACCENT),
    ("Phase 3: National Scale-Up (Months 5–12)", "Expand to 100 high-vulnerability climate districts across Uttar Pradesh, Bihar, Haryana, and Punjab under ABDM.", AMBER)
]

for p_title, p_desc, p_col in phases:
    p = tf.add_paragraph()
    p.text = p_title
    p.font.size = Pt(12.5)
    p.font.bold = True
    p.font.color.rgb = p_col
    p.space_after = Pt(2)
    
    p = tf.add_paragraph()
    p.text = p_desc
    p.font.size = Pt(9.5)
    p.font.color.rgb = TEXT_BODY
    p.space_after = Pt(10)

card_dev = add_card(slide10, Inches(6.8), Inches(1.45), Inches(5.7), Inches(5.5), bg_color=CARD_BG, border_color=CARD_BORDER, corner_radius=0.025)
tb_d = slide10.shapes.add_textbox(Inches(7.05), Inches(1.65), Inches(5.2), Inches(5.1))
tf_d = tb_d.text_frame
tf_d.word_wrap = True

p = tf_d.paragraphs[0]
p.text = "SOLO PARTICIPANT & SYSTEM ARCHITECT"
p.font.size = Pt(11)
p.font.bold = True
p.font.color.rgb = BLUE_ACCENT
p.space_after = Pt(6)

p = tf_d.add_paragraph()
p.text = "Ritesh Kumar Mahato"
p.font.size = Pt(24)
p.font.bold = True
p.font.color.rgb = TEXT_HEAD

p = tf_d.add_paragraph()
p.text = "Full-Stack AI Engineer"
p.font.size = Pt(12)
p.font.color.rgb = TEXT_MUTED
p.space_after = Pt(12)

p = tf_d.add_paragraph()
p.text = "• Event: Build with AI: Code for Communities (2nd Edition)\n" \
         "• Challenge Track: Track 3 — Smart Health & Supply Chain Resilience\n" \
         "• Live Working Application: https://aarogya-vayu.vercel.app\n" \
         "• Video Demo Walkthrough: https://youtu.be/D8w2qviTuW4\n" \
         "• GitHub Repository: https://github.com/Ritesh-Root/aarogya-vayu\n" \
         "• Corridors: Bhubaneswar–Cuttack (Odisha, Default) & Lucknow–Unnao (UP)\n" \
         "• Live Data: Copernicus CAMS & Open-Meteo, Google News RSS\n" \
         "• Google AI: Gemini 3.8 Flash (language, function calling, audio, vision) • Data: Copernicus CAMS via Open-Meteo"
p.font.size = Pt(9.5)
p.font.color.rgb = TEXT_BODY
p.space_after = Pt(12)

p = tf_d.add_paragraph()
p.text = "Thank you for reviewing Aarogya-Vāyu!"
p.font.size = Pt(13)
p.font.bold = True
p.font.color.rgb = EMERALD

prs.save(PPTX_PATH)
print(f"SUCCESS: Generated 12-slide deck to {PPTX_PATH}")
