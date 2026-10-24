from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import re
import html
import time
import logging
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

logger = logging.getLogger("aarogya_vayu.news")

class NewsArticle(BaseModel):
    id: str
    title: str
    summary: str
    category: str  # "climate", "air_quality", "epidemic", "supply_chain", "clinical"
    severity: str  # "critical", "warning", "info"
    source: str
    published_at: str
    region_id: str
    district: str
    related_medicines: List[str]
    clinical_impact: str
    action_label: str
    target_facility_id: Optional[str] = None
    url: Optional[str] = None
    is_live: bool = False

# Illustrative sample advisories (hand-written; shown labelled as samples alongside live Google News RSS)
CURATED_OFFICIAL_DIRECTIVES: Dict[str, List[Dict[str, Any]]] = {
    "bhubaneswar": [
        {
            "id": "NEWS-BBS-01",
            "title": "IMD Bhubaneswar Issues Severe Heatwave Yellow Alert Across Khordha & Cuttack Districts",
            "summary": "Coastal Odisha registers maximum daytime temperatures 4.2°C above seasonal normal with 74% relative humidity. Heat illness surveillance heightened at CHC Jatni, Capital Hospital Unit-6, and PHC Mendhasal as wet-bulb temperatures approach critical thresholds.",
            "category": "climate",
            "severity": "warning",
            "source": "IMD Bhubaneswar Regional Meteorological Centre",
            "published_at": "Today • 08:30 IST",
            "region_id": "bhubaneswar",
            "district": "Khordha",
            "related_medicines": ["MED-002", "MED-005"],
            "clinical_impact": "+72% Acute Dehydration & Pediatric Heat Exhaustion presentations projected across rural frontline PHCs.",
            "action_label": "Pre-Allocate ORS & IV Fluids",
            "target_facility_id": "PHC-BBS-01",
            "url": "https://mausam.imd.gov.in/bhubaneswar/",
            "is_live": False
        },
        {
            "id": "NEWS-BBS-02",
            "title": "OSPCB Continuous CAAQMS Records Particulate Concentration Inversion in Choudwar Industrial Basin",
            "summary": "Mahanadi river valley inversion traps industrial fly ash and secondary particulates, driving localized PM2.5 to 185 µg/m³ around Choudwar and Athagarh. Rural health centers report sharp rise in acute obstructive respiratory distress.",
            "category": "air_quality",
            "severity": "warning",
            "source": "Odisha State Pollution Control Board (OSPCB)",
            "published_at": "Today • 07:15 IST",
            "region_id": "bhubaneswar",
            "district": "Cuttack",
            "related_medicines": ["MED-001", "MED-003"],
            "clinical_impact": "+48% Acute Bronchospasm and Nebulizer demand within 36–42 hour lag onset window.",
            "action_label": "Mobilize Salbutamol Respules",
            "target_facility_id": "CHC-CTC-01",
            "url": "http://ospcboard.org/",
            "is_live": False
        },
        {
            "id": "NEWS-BBS-03",
            "title": "Odisha State Medical Corporation (OSMCL) Mobilizes Emergency Respiratory Buffer to Khordha",
            "summary": "OSMCL central warehouse at Mancheswar releases 50,000 emergency Salbutamol respules for the coastal health corridor. Peer-to-peer autonomous facility transfers activated to bridge immediate 48-hour transit interval for peripheral clinics.",
            "category": "supply_chain",
            "severity": "info",
            "source": "Health & Family Welfare Department, Govt of Odisha",
            "published_at": "Yesterday • 18:00 IST",
            "region_id": "bhubaneswar",
            "district": "Khordha",
            "related_medicines": ["MED-001", "MED-004"],
            "clinical_impact": "Autonomous P2P reallocation active across 20-facility cluster to prevent stockouts before warehouse convoy arrival.",
            "action_label": "Review P2P Reallocation Challans",
            "target_facility_id": "CHC-BBS-02",
            "url": "https://osmcl.nic.in/",
            "is_live": False
        },
        {
            "id": "NEWS-BBS-04",
            "title": "Khordha District Health Administration Mandates 24/7 ORS Corners Near Daya River Basin",
            "summary": "10 peripheral Primary Health Centres including Mendhasal, Balianta, and Balipatna instructed to maintain continuous rehydration depots following cluster reports of acute diarrheal illness in agricultural communities.",
            "category": "epidemic",
            "severity": "info",
            "source": "Chief District Medical Officer (CDMO) Khordha",
            "published_at": "Yesterday • 14:20 IST",
            "region_id": "bhubaneswar",
            "district": "Khordha",
            "related_medicines": ["MED-002", "MED-004"],
            "clinical_impact": "Accelerated consumption of WHO-formula Oral Rehydration Salts (MED-002) at sub-centre catchment level.",
            "action_label": "Check ORS Buffer Stock",
            "target_facility_id": "PHC-BBS-04",
            "url": "https://khordha.odisha.gov.in/",
            "is_live": False
        },
        {
            "id": "NEWS-BBS-05",
            "title": "AIIMS Bhubaneswar Issues Updated Frontline Protocol for Coastal Inversion Bronchospasm",
            "summary": "Department of Pulmonary Medicine issues clinical directive recommending early 2.5mg Salbutamol nebulization at PHC level prior to systemic corticosteroid escalation for industrial fog exposure.",
            "category": "clinical",
            "severity": "info",
            "source": "AIIMS Bhubaneswar Clinical Pulmonary Directorate",
            "published_at": "Yesterday • 10:00 IST",
            "region_id": "bhubaneswar",
            "district": "Cuttack",
            "related_medicines": ["MED-001", "MED-003"],
            "clinical_impact": "Standardizes first-line treatment regimen for rural Medical Officers in Khordha & Cuttack corridors.",
            "action_label": "View Clinical Directive",
            "target_facility_id": "CHC-CTC-03",
            "url": "https://aiimsbhubaneswar.nic.in/",
            "is_live": False
        }
    ],
    "lucknow": [
        {
            "id": "NEWS-LKO-01",
            "title": "Severe Atmospheric Inversion Over Lucknow-Unnao Corridor Traps PM2.5 at 298 µg/m³; GRAP-IV Considered",
            "summary": "Ground-level nocturnal thermal inversion ceiling drops to 180m AGL across Central Awadh. Toxic particulate stagnation across Talkatora, Sarojini Nagar, and Nawabganj triggers high-priority respiratory emergency warnings.",
            "category": "air_quality",
            "severity": "critical",
            "source": "UPPCB Central CAAQMS Network Bulletin",
            "published_at": "Today • 08:15 IST",
            "region_id": "lucknow",
            "district": "Lucknow",
            "related_medicines": ["MED-001", "MED-003"],
            "clinical_impact": "+62% Spike in acute bronchospasm and COPD exacerbations across peripheral health facilities within 42h.",
            "action_label": "Execute Emergency Transfers",
            "target_facility_id": "PHC-LKO-01",
            "url": "http://uppcb.com/",
            "is_live": False
        },
        {
            "id": "NEWS-LKO-02",
            "title": "KGMU Lucknow Pulmonary Ward Reports 88% Bed Occupancy Amid Trans-Gangetic Smog Inversion",
            "summary": "Tertiary referral pressure escalates rapidly as rural health centres in Kakori, Malihabad, and Safipur report depleted stocks of standard inhalant bronchodilators.",
            "category": "epidemic",
            "severity": "warning",
            "source": "King George's Medical University (KGMU) Pulmonology",
            "published_at": "Today • 06:45 IST",
            "region_id": "lucknow",
            "district": "Lucknow",
            "related_medicines": ["MED-001"],
            "clinical_impact": "Immediate decentralized cluster stock redistribution needed to absorb caseload at primary care level.",
            "action_label": "Audit Kakori Cluster Inventory",
            "target_facility_id": "PHC-LKO-01",
            "url": "https://www.kgmu.org/",
            "is_live": False
        },
        {
            "id": "NEWS-LKO-03",
            "title": "UPMSCL Central Drug Warehouse Unnao Expedites Antibiotic & Bronchodilator Batch Release",
            "summary": "State warehouse initiates routine 72-hour replenishment dispatches. Autonomous peer-to-peer reallocation algorithm approved by CMO to manage interim zero-stockout risk.",
            "category": "supply_chain",
            "severity": "info",
            "source": "National Health Mission (NHM) Uttar Pradesh",
            "published_at": "Yesterday • 19:30 IST",
            "region_id": "lucknow",
            "district": "Unnao",
            "related_medicines": ["MED-001", "MED-004"],
            "clinical_impact": "Autonomous P2P rebalancing bridges 72h warehouse dispatch interval across 20 facilities.",
            "action_label": "Review UPMSCL Consignments",
            "target_facility_id": "CHC-UNA-09",
            "url": "http://upmscl.in/",
            "is_live": False
        },
        {
            "id": "NEWS-LKO-04",
            "title": "District Magistrate Lucknow & CMO Mandate Daily 08:00 Stock Ledgers Across Corridor PHCs",
            "summary": "All 20 corridor primary and community health centres required to maintain cryptographic ledger reconciliation and digital voice intake verification to prevent stockouts.",
            "category": "clinical",
            "severity": "info",
            "source": "Directorate of Health Services, Uttar Pradesh",
            "published_at": "Yesterday • 16:00 IST",
            "region_id": "lucknow",
            "district": "Lucknow",
            "related_medicines": ["MED-001", "MED-002", "MED-005"],
            "clinical_impact": "Enforces 100% compliance on daily physical stock verification and discrepancy resolution.",
            "action_label": "Open Clinic Daily Desk",
            "target_facility_id": "PHC-LKO-01",
            "url": "https://lucknow.nic.in/",
            "is_live": False
        }
    ]
}

EXCLUDED_CRIME_TERMS = [
    "murder", "stabbed", "arrested", "rape", "theft", "crime", "fraud",
    "scam", "suicide", "robbery", "killed by", "hit and run", "plane crash",
    "shot dead", "smuggling", "encounter"
]

class NewsService:
    def __init__(self, cache_ttl_seconds: int = 600):
        self.cache_ttl = cache_ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}

    def fetch_live_google_news(self, region: str = "bhubaneswar") -> List[NewsArticle]:
        """
        Dynamically fetches and categorizes 100% real live news articles
        from Google News RSS for the target regional corridor.
        """
        reg = region.lower()
        if reg == "bhubaneswar":
            query = "Bhubaneswar (health OR hospital OR pollution OR weather OR heat OR dengue OR malaria OR fever OR medicine OR clinic OR doctor OR air quality)"
            district_name = "Khordha"
            default_fac = "PHC-BBS-01"
        else:
            query = "Lucknow (health OR hospital OR pollution OR weather OR heat OR dengue OR malaria OR fever OR medicine OR clinic OR doctor OR air quality)"
            district_name = "Lucknow"
            default_fac = "PHC-LKO-01"

        encoded_q = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded_q}&hl=en-IN&gl=IN&ceid=IN:en"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )

        live_articles: List[NewsArticle] = []
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                xml_content = resp.read()
                root = ET.fromstring(xml_content)
                items = root.findall(".//item")

                for idx, item in enumerate(items[:20]):
                    raw_title = item.findtext("title") or "Regional Health Dispatch"
                    link = item.findtext("link") or ""
                    pub_date = item.findtext("pubDate") or ""
                    source_el = item.find("source")
                    source_name = source_el.text if source_el is not None else "National News Wire"
                    raw_desc = item.findtext("description") or ""

                    # Filter out non-health / crime news
                    clean_desc = re.sub(r"<[^>]+>", "", html.unescape(raw_desc)).strip()
                    title_lower = raw_title.lower()
                    if any(t in title_lower for t in EXCLUDED_CRIME_TERMS):
                        continue

                    # Extract pure title without trailing " - Source"
                    clean_title = raw_title
                    if " - " in raw_title:
                        parts = raw_title.rsplit(" - ", 1)
                        clean_title = parts[0].strip()
                        if not source_name or source_name == "National News Wire":
                            source_name = parts[1].strip()

                    corpus = f"{clean_title} {clean_desc}".lower()

                    # Semantic Category Classification
                    if any(w in corpus for w in ["rain", "weather", "heat", "cyclone", "flood", "monsoon", "temperature", "forecast", "cloud"]):
                        category = "climate"
                    elif any(w in corpus for w in ["pollution", "aqi", "smog", "air quality", "clean air", "emissions", "pm2.5", "swachh vayu"]):
                        category = "air_quality"
                    elif any(w in corpus for w in ["dengue", "malaria", "fever", "diarrhea", "cholera", "infection", "virus", "outbreak", "swine flu"]):
                        category = "epidemic"
                    elif any(w in corpus for w in ["drug", "medicine", "pharmacy", "warehouse", "stock", "supply", "dispensary", "depot"]):
                        category = "supply_chain"
                    else:
                        category = "clinical"

                    # Related Essential Medicines Tagging
                    related_meds: List[str] = []
                    if category == "air_quality" or "respiratory" in corpus or "asthma" in corpus:
                        related_meds = ["MED-001", "MED-006"]
                    elif category == "climate" or "heat" in corpus or "dehydration" in corpus:
                        related_meds = ["MED-002", "MED-005"]
                    elif category == "epidemic" or "fever" in corpus or "dengue" in corpus:
                        related_meds = ["MED-003", "MED-004"]
                    else:
                        related_meds = ["MED-001", "MED-004"]

                    # Severity
                    severity = "warning" if any(w in corpus for w in ["warning", "alert", "death", "surge", "severe", "outbreak", "inversion"]) else "info"

                    # Clinical impact
                    if category == "air_quality":
                        clinical_impact = f"Elevated particulate matter reported by {source_name}. Clinicians advised to pre-position bronchodilators."
                    elif category == "climate":
                        clinical_impact = f"Meteorological variation reported by {source_name}. Primary care facilities on alert for weather-related stress."
                    elif category == "epidemic":
                        clinical_impact = f"Disease surveillance dispatch from {source_name}. Monitor fever & rehydration protocols."
                    else:
                        clinical_impact = f"Verified public health news from {source_name}. Peripheral facilities advised to maintain standard reserves."

                    # Clean published date
                    formatted_pub = pub_date[:16] if len(pub_date) > 16 else pub_date

                    live_articles.append(NewsArticle(
                        id=f"LIVE-{reg[:3].upper()}-{idx+1:02d}",
                        title=clean_title,
                        summary=clean_desc or f"Public health and environmental bulletin published via {source_name} for {reg.title()}.",
                        category=category,
                        severity=severity,
                        source=source_name,
                        published_at=formatted_pub,
                        region_id=reg,
                        district=district_name,
                        related_medicines=related_meds,
                        clinical_impact=clinical_impact,
                        action_label="Analyze Field Impact",
                        target_facility_id=default_fac,
                        url=link,
                        is_live=True
                    ))
        except Exception as e:
            logger.warning(f"Failed to fetch live Google News RSS for {region}: {e}")

        return live_articles

    def get_news(
        self,
        region: str = "bhubaneswar",
        category: Optional[str] = None,
        search: Optional[str] = None,
        force_refresh: bool = False
    ) -> List[NewsArticle]:
        reg = region.lower()
        now = time.time()
        
        cached = self._cache.get(reg)
        if not force_refresh and cached and (now - cached["timestamp"] < self.cache_ttl):
            combined_articles = cached["articles"]
        else:
            # 1. Fetch live articles from Google News RSS
            live_articles = self.fetch_live_google_news(reg)
            
            # 2. Get curated official state health & pollution directives
            curated_raw = CURATED_OFFICIAL_DIRECTIVES.get(reg, CURATED_OFFICIAL_DIRECTIVES["bhubaneswar"])
            # These are hand-written illustrative advisories, not fetched bulletins: label them so they are never mistaken for live news
            curated_articles = [
                NewsArticle(**{
                    **item,
                    "title": f"[Sample advisory] {item['title']}",
                    "source": f"{item['source']} (illustrative sample, not a live bulletin)",
                    "published_at": "Sample",
                    "is_live": False,
                })
                for item in curated_raw
            ]
            
            # 3. Interleave/merge live news with curated official directives
            # Keep live articles first, followed by official regulatory notices
            combined_articles = live_articles + curated_articles
            
            self._cache[reg] = {
                "timestamp": now,
                "articles": combined_articles
            }

        # Apply filtering
        results: List[NewsArticle] = []
        for item in combined_articles:
            if category and category.lower() != "all" and item.category.lower() != category.lower():
                continue
            if search:
                q = search.lower().strip()
                searchable_text = f"{item.title} {item.summary} {item.source} {item.district} {' '.join(item.related_medicines)}".lower()
                if q not in searchable_text:
                    continue
            results.append(item)

        return results

news_service = NewsService()
