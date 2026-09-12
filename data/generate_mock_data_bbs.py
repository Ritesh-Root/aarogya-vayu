import json
import random
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

with open(DATA_DIR / "facilities_bhubaneswar.json", "r", encoding="utf-8") as f:
    facilities = json.load(f)

with open(DATA_DIR / "medicines.json", "r", encoding="utf-8") as f:
    medicines = json.load(f)

# Deterministic seed for reproducible testing & live demos
random.seed(108)
today = datetime.now()

inventory = []
for fac in facilities:
    is_chc = fac["type"] == "CHC"
    fac_id = fac["id"]

    for med in medicines:
        base_rate = med["base_consumption_chc"] if is_chc else med["base_consumption_phc"]

        # Engineered Scenario for Bhubaneswar-Cuttack:
        # High-demand frontline facilities:
        # PHC Mendhasal (PHC-BBS-01) and PHC Balianta (PHC-BBS-04)
        # have critically low respiratory/heatwave stock (Salbutamol, Dexamethasone, ORS)!
        if fac_id in ["PHC-BBS-01", "PHC-BBS-04"] and med["id"] in ["MED-001", "MED-002", "MED-003"]:
            # Critical stock: only 2-3 days cover
            current_qty = int(base_rate * random.uniform(1.8, 3.2))
            expiry_days = random.randint(180, 365)
        # Upwind Donor Facilities: CHC Jatni (CHC-BBS-03) and CHC Choudwar (CHC-CTC-01)
        # have large surplus and lots of stock EXPIRING SOON (45-85 days)
        elif fac_id in ["CHC-BBS-03", "CHC-CTC-01", "CHC-BBS-07"] and med["id"] in ["MED-001", "MED-002", "MED-003"]:
            current_qty = int(base_rate * random.uniform(25.0, 38.0))
            expiry_days = random.randint(55, 85)
        else:
            # Normal facilities: 12-25 days cover
            current_qty = int(base_rate * random.uniform(12.0, 24.0))
            expiry_days = random.randint(120, 450)

        exp_date = (today + timedelta(days=expiry_days)).strftime("%Y-%m-%d")
        batch_no = f"BAT-OD-{random.randint(100, 999)}-{today.year % 100}"

        inventory.append({
            "facility_id": fac_id,
            "facility_name": fac["name"],
            "medicine_id": med["id"],
            "medicine_name": med["name"],
            "current_stock": current_qty,
            "on_hand": current_qty,
            "reserved": 0,
            "quarantined": 0,
            "available": current_qty,
            "raw_available": current_qty,
            "reconciliation_deficit": 0,
            "is_reconciliation_required": False,
            "is_frozen": False,
            "version": 1,
            "pack_size": 10,
            "daily_consumption_base": base_rate,
            "batch_number": batch_no,
            "expiry_date": exp_date,
            "days_to_expiry": expiry_days,
            "last_updated": (today - timedelta(hours=random.randint(1, 14))).strftime("%Y-%m-%d %H:%M:%S")
        })

output_path = DATA_DIR / "inventory_bhubaneswar.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(inventory, f, indent=2)

print(f"Generated {len(facilities)} Bhubaneswar facilities and {len(inventory)} inventory records into {output_path}")
