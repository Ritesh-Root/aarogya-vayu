from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import re

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

# Curated regional news dispatches
REGIONAL_NEWS_DATA: Dict[str, List[Dict[str, Any]]] = {
    "bhubaneswar": [
        {
            "id": "NEWS-BBS-01",
            "title": "IMD Bhubaneswar Issues Severe Heatwave Yellow Alert Across Khordha & Cuttack Districts",
            "summary": "Coastal Odisha registers maximum daytime temperatures 4.2°C above seasonal normal with 74% relative humidity. Heat illness surveillance heightened at CHC Jatni, Capital Hospital Unit-6, and PHC Mendhasal as wet-bulb temperatures approach critical thresholds.",
            "category": "climate",
            "severity": "warning",
            "source": "IMD Bhubaneswar Regional Meteorological Centre",
            "published_at": "18 minutes ago",
            "region_id": "bhubaneswar",
            "district": "Khordha",
            "related_medicines": ["MED-002", "MED-005"],
            "clinical_impact": "+72% Acute Dehydration & Pediatric Heat Exhaustion presentations projected across rural frontline PHCs.",
            "action_label": "Pre-Allocate ORS & IV Fluids",
            "target_facility_id": "PHC-BBS-01"
        },
        {
            "id": "NEWS-BBS-02",
            "title": "OSPCB Continuous CAAQMS Records Particulate Concentration Inversion in Choudwar Industrial Basin",
            "summary": "Mahanadi river valley inversion traps industrial fly ash and secondary particulates, driving localized PM2.5 to 185 µg/m³ around Choudwar and Athagarh. Rural health centers report sharp rise in acute obstructive respiratory distress.",
            "category": "air_quality",
            "severity": "warning",
            "source": "Odisha State Pollution Control Board (OSPCB)",
            "published_at": "1 hour ago",
            "region_id": "bhubaneswar",
            "district": "Cuttack",
            "related_medicines": ["MED-001", "MED-003"],
            "clinical_impact": "+48% Acute Bronchospasm and Nebulizer demand within 36–42 hour lag onset window.",
            "action_label": "Mobilize Salbutamol Respules",
            "target_facility_id": "CHC-CTC-01"
        },
        {
            "id": "NEWS-BBS-03",
            "title": "Odisha State Medical Corporation (OSMCL) Mobilizes Emergency Respiratory Buffer to Khordha",
            "summary": "OSMCL central warehouse at Mancheswar releases 50,000 emergency Salbutamol respules for the coastal health corridor. Peer-to-peer autonomous facility transfers activated to bridge immediate 48-hour transit interval for peripheral clinics.",
            "category": "supply_chain",
            "severity": "info",
            "source": "Health & Family Welfare Department, Govt of Odisha",
            "published_at": "3 hours ago",
            "region_id": "bhubaneswar",
            "district": "Khordha",
            "related_medicines": ["MED-001", "MED-004"],
            "clinical_impact": "Autonomous P2P reallocation active across 20-facility cluster to prevent stockouts before warehouse convoy arrival.",
            "action_label": "Review P2P Reallocation Challans",
            "target_facility_id": "CHC-BBS-02"
        },
        {
            "id": "NEWS-BBS-04",
            "title": "Khordha District Health Administration Mandates 24/7 ORS Corners Near Daya River Basin",
            "summary": "10 peripheral Primary Health Centres including Mendhasal, Balianta, and Balipatna instructed to maintain continuous rehydration depots following cluster reports of acute diarrheal illness in agricultural communities.",
            "category": "epidemic",
            "severity": "info",
            "source": "Chief District Medical Officer (CDMO) Khordha",
            "published_at": "5 hours ago",
            "region_id": "bhubaneswar",
            "district": "Khordha",
            "related_medicines": ["MED-002", "MED-004"],
            "clinical_impact": "Accelerated consumption of WHO-formula Oral Rehydration Salts (MED-002) at sub-centre catchment level.",
            "action_label": "Check ORS Buffer Stock",
            "target_facility_id": "PHC-BBS-04"
        },
        {
            "id": "NEWS-BBS-05",
            "title": "AIIMS Bhubaneswar Issues Updated Frontline Protocol for Coastal Inversion Bronchospasm",
            "summary": "Department of Pulmonary Medicine issues clinical directive recommending early 2.5mg Salbutamol nebulization at PHC level prior to systemic corticosteroid escalation for industrial fog exposure.",
            "category": "clinical",
            "severity": "info",
            "source": "AIIMS Bhubaneswar Clinical Pulmonary Directorate",
            "published_at": "8 hours ago",
            "region_id": "bhubaneswar",
            "district": "Cuttack",
            "related_medicines": ["MED-001", "MED-003"],
            "clinical_impact": "Standardizes first-line treatment regimen for rural Medical Officers in Khordha & Cuttack corridors.",
            "action_label": "View Clinical Directive",
            "target_facility_id": "CHC-CTC-03"
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
            "published_at": "22 minutes ago",
            "region_id": "lucknow",
            "district": "Lucknow",
            "related_medicines": ["MED-001", "MED-003"],
            "clinical_impact": "+62% Spike in acute bronchospasm and COPD exacerbations across peripheral health facilities within 42h.",
            "action_label": "Execute Emergency Transfers",
            "target_facility_id": "PHC-LKO-01"
        },
        {
            "id": "NEWS-LKO-02",
            "title": "KGMU Lucknow Pulmonary Ward Reports 88% Bed Occupancy Amid Trans-Gangetic Smog Inversion",
            "summary": "Tertiary referral pressure escalates rapidly as rural health centres in Kakori, Malihabad, and Safipur report depleted stocks of standard inhalant bronchodilators.",
            "category": "epidemic",
            "severity": "warning",
            "source": "Times of India - Lucknow Bureau / KGMU Health Desk",
            "published_at": "1 hour ago",
            "region_id": "lucknow",
            "district": "Lucknow",
            "related_medicines": ["MED-001"],
            "clinical_impact": "Immediate decentralized cluster stock redistribution needed to absorb caseload at primary care level.",
            "action_label": "Audit Kakori Cluster Inventory",
            "target_facility_id": "PHC-LKO-01"
        },
        {
            "id": "NEWS-LKO-03",
            "title": "UPMSCL Central Drug Warehouse Unnao Expedites Antibiotic & Bronchodilator Batch Release",
            "summary": "State warehouse initiates routine 72-hour replenishment dispatches. Autonomous peer-to-peer reallocation algorithm approved by CMO to manage interim zero-stockout risk.",
            "category": "supply_chain",
            "severity": "info",
            "source": "National Health Mission (NHM) Uttar Pradesh",
            "published_at": "4 hours ago",
            "region_id": "lucknow",
            "district": "Unnao",
            "related_medicines": ["MED-001", "MED-004"],
            "clinical_impact": "Autonomous P2P rebalancing bridges 72h warehouse dispatch interval across 20 facilities.",
            "action_label": "Review UPMSCL Consignments",
            "target_facility_id": "CHC-UNA-09"
        },
        {
            "id": "NEWS-LKO-04",
            "title": "District Magistrate Lucknow & CMO Mandate Daily 08:00 Stock Ledgers Across Corridor PHCs",
            "summary": "All 20 corridor primary and community health centres required to maintain cryptographic ledger reconciliation and digital voice intake verification to prevent stockouts.",
            "category": "clinical",
            "severity": "info",
            "source": "Directorate of Health Services, Uttar Pradesh",
            "published_at": "7 hours ago",
            "region_id": "lucknow",
            "district": "Lucknow",
            "related_medicines": ["MED-001", "MED-002", "MED-005"],
            "clinical_impact": "Enforces 100% compliance on daily physical stock verification and discrepancy resolution.",
            "action_label": "Open Clinic Daily Desk",
            "target_facility_id": "PHC-LKO-01"
        }
    ]
}

class NewsService:
    def __init__(self):
        self.news_store = REGIONAL_NEWS_DATA

    def get_news(self, region: str = "bhubaneswar", category: Optional[str] = None, search: Optional[str] = None) -> List[NewsArticle]:
        reg = region.lower()
        articles_data = self.news_store.get(reg, self.news_store.get("bhubaneswar", []))
        
        results: List[NewsArticle] = []
        for item in articles_data:
            if category and category.lower() != "all" and item["category"].lower() != category.lower():
                continue
            if search:
                q = search.lower().strip()
                searchable_text = f"{item['title']} {item['summary']} {item['source']} {item['district']} {' '.join(item['related_medicines'])}".lower()
                if q not in searchable_text:
                    continue
            results.append(NewsArticle(**item))
            
        return results

news_service = NewsService()
