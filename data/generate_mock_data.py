import json
import random
from datetime import datetime, timedelta

facilities = [
  {"id": "PHC-LKO-01", "name": "PHC Kakori", "district": "Lucknow", "type": "PHC", "lat": 26.8778, "lng": 80.7963, "population_served": 48500, "beds": 12, "cold_storage": True, "doctor": "Dr. Ananya Srivastava"},
  {"id": "CHC-LKO-02", "name": "CHC Malihabad", "district": "Lucknow", "type": "CHC", "lat": 26.9208, "lng": 80.7107, "population_served": 112000, "beds": 30, "cold_storage": True, "doctor": "Dr. Rajesh Verma"},
  {"id": "PHC-LKO-03", "name": "PHC Mohanlalganj", "district": "Lucknow", "type": "PHC", "lat": 26.6853, "lng": 80.9984, "population_served": 54000, "beds": 10, "cold_storage": True, "doctor": "Dr. Neha Tripathi"},
  {"id": "CHC-LKO-04", "name": "CHC Gosainganj", "district": "Lucknow", "type": "CHC", "lat": 26.7725, "lng": 81.1219, "population_served": 89000, "beds": 24, "cold_storage": True, "doctor": "Dr. Vivek Pandey"},
  {"id": "PHC-LKO-05", "name": "PHC Chinhat", "district": "Lucknow", "type": "PHC", "lat": 26.8833, "lng": 81.0425, "population_served": 62000, "beds": 14, "cold_storage": True, "doctor": "Dr. Pooja Yadav"},
  {"id": "CHC-LKO-06", "name": "CHC Sarojini Nagar", "district": "Lucknow", "type": "CHC", "lat": 26.7584, "lng": 80.8665, "population_served": 125000, "beds": 35, "cold_storage": True, "doctor": "Dr. Alok Mishra"},
  {"id": "PHC-LKO-07", "name": "PHC Bakshi Ka Talab", "district": "Lucknow", "type": "PHC", "lat": 27.0012, "lng": 80.9234, "population_served": 51000, "beds": 12, "cold_storage": True, "doctor": "Dr. Sandeep Singh"},
  {"id": "PHC-LKO-08", "name": "PHC Itaunja", "district": "Lucknow", "type": "PHC", "lat": 27.0945, "lng": 80.9123, "population_served": 43000, "beds": 8, "cold_storage": False, "doctor": "Dr. Rashmi Shukla"},
  {"id": "CHC-LKO-09", "name": "CHC Nagram", "district": "Lucknow", "type": "CHC", "lat": 26.6123, "lng": 81.1345, "population_served": 78000, "beds": 20, "cold_storage": True, "doctor": "Dr. Tariq Ahmad"},
  {"id": "PHC-LKO-10", "name": "PHC Alambagh Rural", "district": "Lucknow", "type": "PHC", "lat": 26.8123, "lng": 80.9012, "population_served": 58000, "beds": 12, "cold_storage": True, "doctor": "Dr. Sunita Saxena"},
  {"id": "CHC-UNN-01", "name": "CHC Nawabganj", "district": "Unnao", "type": "CHC", "lat": 26.6432, "lng": 80.6421, "population_served": 95000, "beds": 30, "cold_storage": True, "doctor": "Dr. Pradeep Maurya"},
  {"id": "PHC-UNN-02", "name": "PHC Hasanganj", "district": "Unnao", "type": "PHC", "lat": 26.7821, "lng": 80.5213, "population_served": 52000, "beds": 10, "cold_storage": True, "doctor": "Dr. Manisha Dixit"},
  {"id": "CHC-UNN-03", "name": "CHC Safipur", "district": "Unnao", "type": "CHC", "lat": 26.7389, "lng": 80.3478, "population_served": 110000, "beds": 30, "cold_storage": True, "doctor": "Dr. Ramesh Gupta"},
  {"id": "PHC-UNN-04", "name": "PHC Purwa", "district": "Unnao", "type": "PHC", "lat": 26.4678, "lng": 80.7712, "population_served": 64000, "beds": 14, "cold_storage": True, "doctor": "Dr. Kavita Rastogi"},
  {"id": "CHC-UNN-05", "name": "CHC Bighapur", "district": "Unnao", "type": "CHC", "lat": 26.3456, "lng": 80.6890, "population_served": 82000, "beds": 20, "cold_storage": True, "doctor": "Dr. Sanjay Bajpai"},
  {"id": "PHC-UNN-06", "name": "PHC Bangarmau", "district": "Unnao", "type": "PHC", "lat": 26.9012, "lng": 80.2134, "population_served": 69000, "beds": 12, "cold_storage": True, "doctor": "Dr. Imran Khan"},
  {"id": "CHC-UNN-07", "name": "CHC Mianganj", "district": "Unnao", "type": "CHC", "lat": 26.8124, "lng": 80.4532, "population_served": 76000, "beds": 20, "cold_storage": True, "doctor": "Dr. Arvind Tiwari"},
  {"id": "PHC-UNN-08", "name": "PHC Asoha", "district": "Unnao", "type": "PHC", "lat": 26.5412, "lng": 80.8521, "population_served": 46000, "beds": 8, "cold_storage": False, "doctor": "Dr. Shalini Sahu"},
  {"id": "CHC-UNN-09", "name": "CHC Fatehpur Chaurasi", "district": "Unnao", "type": "CHC", "lat": 26.7912, "lng": 80.2912, "population_served": 88000, "beds": 24, "cold_storage": True, "doctor": "Dr. Dinesh Pratap"},
  {"id": "PHC-UNN-10", "name": "PHC Sikandarpur Karan", "district": "Unnao", "type": "PHC", "lat": 26.5123, "lng": 80.4912, "population_served": 49000, "beds": 10, "cold_storage": True, "doctor": "Dr. Vandana Rajput"}
]

medicines = [
  {
    "id": "MED-001",
    "name": "Salbutamol Respirator Solution (Respules 2.5mg)",
    "category": "Respiratory / Bronchodilator",
    "unit": "Respules (vials)",
    "climate_sensitive": "AQI / Smog",
    "base_consumption_phc": 20,
    "base_consumption_chc": 50,
    "min_buffer_days": 14,
    "critical_threshold_days": 4
  },
  {
    "id": "MED-002",
    "name": "Oral Rehydration Salts (ORS Sachets, WHO Formula)",
    "category": "Fluid Therapy / Electrolytes",
    "unit": "Sachets",
    "climate_sensitive": "Heatwave / Drought",
    "base_consumption_phc": 40,
    "base_consumption_chc": 100,
    "min_buffer_days": 14,
    "critical_threshold_days": 5
  },
  {
    "id": "MED-003",
    "name": "Dexamethasone Sodium Phosphate Injection (4mg/ml)",
    "category": "Corticosteroid / Severe Flare-up",
    "unit": "Ampoules",
    "climate_sensitive": "AQI / Smog",
    "base_consumption_phc": 15,
    "base_consumption_chc": 35,
    "min_buffer_days": 14,
    "critical_threshold_days": 3
  },
  {
    "id": "MED-004",
    "name": "Amoxicillin + Clavulanate 625mg Tablets",
    "category": "Antibacterial",
    "unit": "Strips (10 tabs)",
    "climate_sensitive": "Secondary Respiratory",
    "base_consumption_phc": 25,
    "base_consumption_chc": 60,
    "min_buffer_days": 14,
    "critical_threshold_days": 4
  },
  {
    "id": "MED-005",
    "name": "Paracetamol IV Infusion (1000mg/100ml bottle)",
    "category": "Antipyretic / Analgesic",
    "unit": "Bottles",
    "climate_sensitive": "Heat / Infection",
    "base_consumption_phc": 18,
    "base_consumption_chc": 45,
    "min_buffer_days": 14,
    "critical_threshold_days": 4
  },
  {
    "id": "MED-006",
    "name": "Cetirizine 10mg Tablets",
    "category": "Antihistamine / Rhinitis",
    "unit": "Strips (10 tabs)",
    "climate_sensitive": "Smog / Dust",
    "base_consumption_phc": 30,
    "base_consumption_chc": 80,
    "min_buffer_days": 14,
    "critical_threshold_days": 4
  }
]

# Set fixed seed for deterministic, realistic demo
random.seed(42)
today = datetime.now()

inventory = []
for fac in facilities:
    is_chc = fac["type"] == "CHC"
    fac_id = fac["id"]

    for med in medicines:
        base_rate = med["base_consumption_chc"] if is_chc else med["base_consumption_phc"]

        # Engineered Scenario:
        # Downwind Smog corridor: PHC Kakori (PHC-LKO-01) and CHC Sarojini Nagar (CHC-LKO-06)
        # have critically low respiratory stock (Salbutamol, Dexamethasone)!
        if fac_id in ["PHC-LKO-01", "CHC-LKO-06"] and med["id"] in ["MED-001", "MED-003"]:
            # Critical stock: only 2-3 days left
            current_qty = int(base_rate * random.uniform(1.8, 3.2))
            expiry_days = random.randint(180, 365)
        # Upwind Donor Facilities: CHC Nawabganj (CHC-UNN-01) and CHC Malihabad (CHC-LKO-02)
        # have large surplus and lots of stock EXPIRING SOON (45-75 days)!!
        elif fac_id in ["CHC-UNN-01", "CHC-LKO-02", "PHC-UNN-02"] and med["id"] in ["MED-001", "MED-003"]:
            current_qty = int(base_rate * random.uniform(25.0, 38.0))
            # Critical: expiring within 60-90 days, high risk of expiry waste if not transferred!
            expiry_days = random.randint(55, 85)
        else:
            # Normal facilities: 12-25 days cover
            current_qty = int(base_rate * random.uniform(12.0, 24.0))
            expiry_days = random.randint(120, 450)

        exp_date = (today + timedelta(days=expiry_days)).strftime("%Y-%m-%d")
        batch_no = f"BAT-{random.randint(100, 999)}-{today.year % 100}"

        inventory.append({
            "facility_id": fac_id,
            "facility_name": fac["name"],
            "medicine_id": med["id"],
            "medicine_name": med["name"],
            "current_stock": current_qty,
            "daily_consumption_base": base_rate,
            "batch_number": batch_no,
            "expiry_date": exp_date,
            "days_to_expiry": expiry_days,
            "last_updated": (today - timedelta(hours=random.randint(1, 14))).strftime("%Y-%m-%d %H:%M:%S")
        })

with open("/home/ritesh/aarogya_vayu/data/facilities.json", "w") as f:
    json.dump(facilities, f, indent=2)

with open("/home/ritesh/aarogya_vayu/data/medicines.json", "w") as f:
    json.dump(medicines, f, indent=2)

with open("/home/ritesh/aarogya_vayu/data/inventory.json", "w") as f:
    json.dump(inventory, f, indent=2)

print(f"Generated {len(facilities)} facilities, {len(medicines)} medicines, and {len(inventory)} inventory records successfully!")
