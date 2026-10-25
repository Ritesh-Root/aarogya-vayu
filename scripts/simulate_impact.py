"""
Before/after simulation: what happens to the sample clinics during a climate surge with and
without Aarogya-Vāyu's transfers. It uses the app's own demand engine and transfer allocator.

Model (all assumptions are stated here and printed in the report):
- A weather event (smog for Lucknow-Unnao, heat for Bhubaneswar-Cuttack) starts on day 0 and lasts
  the whole window. Windows of 7, 14 and 21 days are run: the gap before the next monthly indent.
- No deliveries from the district store arrive inside the window, in either run.
- Daily use per clinic and medicine is Poisson with mean = normal use x the app's surge multiplier.
- "With Aarogya-Vāyu": every morning the app's engine and allocator run on that day's stock, every
  proposed transfer is approved, and it arrives the next morning. Rules are the app's own:
  35 km, the donor keeps 14 days, no batch expiring within 30 days, oldest batch first.
- Stock is used oldest batch first. A batch still on the shelf on its expiry date is wasted.
- Inventory, facilities and multipliers are the app's sample data and rules, not field data.

Run:  python scripts/simulate_impact.py   (about a minute; writes docs/impact.json and docs/impact.svg)
Nothing under data/ is written.
"""

import copy
import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.models import EnvironmentalReading  # noqa: E402
from app.optimizer import RedistributionOptimizer  # noqa: E402
from app.surge_engine import SurgeEngine  # noqa: E402

WINDOWS = (7, 14, 21)
DAYS = 14          # set per window by summarise()
EVENT_DAYS = 14
INDENT_DAYS = ()   # no store deliveries inside the window
SEEDS = 20
START = date(2026, 10, 25)

EVENTS = {
    "lucknow": ("Winter smog, Lucknow-Unnao", EnvironmentalReading(
        aqi=385, pm25=265.0, temperature_c=17.5, humidity_pct=78.0, heatwave_alert=False, smog_episode=True,
        corridor="Lucknow-Unnao")),
    "bhubaneswar": ("Heatwave, Bhubaneswar-Cuttack", EnvironmentalReading(
        aqi=140, pm25=65.0, temperature_c=43.5, humidity_pct=35.0, heatwave_alert=True, smog_episode=False,
        corridor="Bhubaneswar-Cuttack")),
}
NORMAL = EnvironmentalReading(aqi=75, pm25=28.0, temperature_c=26.0, humidity_pct=60.0,
                              heatwave_alert=False, smog_episode=False, corridor="Normal")

FILES = {"lucknow": ("facilities.json", "inventory.json"),
         "bhubaneswar": ("facilities_bhubaneswar.json", "inventory_bhubaneswar.json")}


def load(region):
    fac_file, inv_file = FILES[region]
    facilities = {f["id"]: f for f in json.loads((ROOT / "data" / fac_file).read_text(encoding="utf-8"))}
    medicines = {m["id"]: m for m in json.loads((ROOT / "data" / "medicines.json").read_text(encoding="utf-8"))}
    batches = []
    for item in json.loads((ROOT / "data" / inv_file).read_text(encoding="utf-8")):
        b = dict(item)
        b["on_hand"] = int(item.get("on_hand", item.get("current_stock", 0)))
        b["expiry"] = date.fromisoformat(str(item["expiry_date"])[:10])
        batches.append(b)
    return facilities, medicines, batches


def poisson(rng, lam):
    if lam <= 0:
        return 0
    if lam > 40:  # normal approximation keeps large means fast
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def as_engine_items(batches, today):
    """The shape the app's engine and allocator read."""
    items = []
    for b in batches:
        if b["on_hand"] <= 0 and b.get("synthetic"):
            continue
        items.append({
            "facility_id": b["facility_id"], "facility_name": b["facility_name"],
            "medicine_id": b["medicine_id"], "medicine_name": b["medicine_name"],
            "batch_number": b["batch_number"], "daily_consumption_base": b["daily_consumption_base"],
            "pack_size": b.get("pack_size", 10),
            "on_hand": b["on_hand"], "current_stock": b["on_hand"], "reserved": 0, "quarantined": 0,
            "available": b["on_hand"], "days_to_expiry": (b["expiry"] - today).days,
        })
    return items


def run(region, use_app, seed):
    facilities, medicines, batches = load(region)
    batches = copy.deepcopy(batches)
    engine = SurgeEngine(facilities, medicines)
    allocator = RedistributionOptimizer(facilities, max_distance_km=35.0)
    rng = random.Random(seed)
    base_use = {(b["facility_id"], b["medicine_id"]): b["daily_consumption_base"] for b in batches}
    meta = {(b["facility_id"], b["medicine_id"]): b for b in batches}
    in_transit = []  # (arrival_day, recipient_id, medicine_id, units, expiry)
    stats = {"stockout_days": 0, "unmet_doses": 0, "expired_units": 0, "transfers": 0, "units_moved": 0, "km": 0.0}

    for day in range(DAYS):
        today = START + timedelta(days=day)
        env = EVENTS[region][1] if day < EVENT_DAYS else NORMAL
        mult = engine.calculate_surge_multipliers(env)

        # Deliveries: yesterday's transfers, and the monthly indent on indent days
        for t in [t for t in in_transit if t[0] == day]:
            _, fac, med, units, expiry = t
            src = meta[(fac, med)]
            batches.append({**src, "batch_number": f"TRF-{day}-{fac}-{med}", "on_hand": units, "expiry": expiry, "synthetic": True})
        in_transit = [t for t in in_transit if t[0] != day]
        if day in INDENT_DAYS:
            for (fac, med), use in base_use.items():
                src = meta[(fac, med)]
                batches.append({**src, "batch_number": f"IND-{day}-{fac}-{med}", "on_hand": 30 * use,
                                "expiry": today + timedelta(days=365), "synthetic": True})

        # Morning: the app proposes transfers on today's stock; all are approved, arriving tomorrow
        if use_app:
            items = as_engine_items(batches, today)
            inbound = {}
            for _, fac, med, units, _ in in_transit:
                inbound[(fac, med)] = inbound.get((fac, med), 0) + units
            risks = engine.assess_facility_risks(items, env, inbound)
            for rec in allocator.optimize(risks, items, set()):
                batch = next((b for b in batches if b["facility_id"] == rec.donor_facility_id
                              and b["medicine_id"] == rec.medicine_id and b["batch_number"] == rec.batch_number), None)
                if not batch or batch["on_hand"] < rec.units_to_transfer:
                    continue
                batch["on_hand"] -= rec.units_to_transfer
                in_transit.append((day + 1, rec.recipient_facility_id, rec.medicine_id, rec.units_to_transfer, batch["expiry"]))
                stats["transfers"] += 1
                stats["units_moved"] += rec.units_to_transfer
                stats["km"] += rec.distance_km

        # Patients: use oldest batch first
        for (fac, med), use in base_use.items():
            category = medicines[med].get("climate_sensitive", "General")
            demand = poisson(rng, use * mult.get(category, 1.0))
            usable = sorted((b for b in batches if b["facility_id"] == fac and b["medicine_id"] == med
                             and b["on_hand"] > 0 and b["expiry"] > today), key=lambda b: b["expiry"])
            for b in usable:
                take = min(demand, b["on_hand"])
                b["on_hand"] -= take
                demand -= take
                if demand == 0:
                    break
            if demand > 0:
                stats["stockout_days"] += 1
                stats["unmet_doses"] += demand

        # Evening: anything expiring tomorrow is thrown away
        for b in batches:
            if b["on_hand"] > 0 and b["expiry"] <= today + timedelta(days=1):
                stats["expired_units"] += b["on_hand"]
                b["on_hand"] = 0
    return stats


def summarise(region, days=None):
    global DAYS, EVENT_DAYS
    if days:
        DAYS = EVENT_DAYS = days
    out = {}
    for arm, use_app in (("status_quo", False), ("with_app", True)):
        runs = [run(region, use_app, seed) for seed in range(SEEDS)]
        out[arm] = {k: round(mean(r[k] for r in runs), 1) for k in runs[0]}
        out[arm]["stockout_days_range"] = [min(r["stockout_days"] for r in runs), max(r["stockout_days"] for r in runs)]
    sq, app = out["status_quo"], out["with_app"]
    out["change"] = {
        "stockout_days_pct": round(100 * (app["stockout_days"] - sq["stockout_days"]) / sq["stockout_days"], 1) if sq["stockout_days"] else None,
        "unmet_doses_pct": round(100 * (app["unmet_doses"] - sq["unmet_doses"]) / sq["unmet_doses"], 1) if sq["unmet_doses"] else None,
        "expired_units_diff": round(app["expired_units"] - sq["expired_units"], 1),
    }
    return out


def svg_chart(results):
    """Days a clinic ran out of a medicine, today vs with the app, for each window and region."""
    W, H = 960, 470
    teal, clay, ink, muted = "#2F6B52", "#B4321E", "#2E221D", "#5C4A44"
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Segoe UI,Helvetica,Arial,sans-serif">',
             f'<rect width="{W}" height="{H}" rx="20" fill="#FFFDF9"/>',
             f'<text x="32" y="44" font-size="22" font-weight="800" fill="{ink}">Transfers stop most stockouts in week 1; after ~2 weeks the district needs resupply</text>',
             f'<text x="32" y="70" font-size="14" fill="{muted}">Days a clinic ran out of a medicine. Simulation on the app\'s 40 sample clinics, mean of {SEEDS} runs, no store deliveries in the window.</text>',
             f'<rect x="{W - 330}" y="92" width="14" height="14" rx="3" fill="{clay}"/><text x="{W - 310}" y="104" font-size="13" fill="{ink}">Today (no transfers)</text>',
             f'<rect x="{W - 170}" y="92" width="14" height="14" rx="3" fill="{teal}"/><text x="{W - 150}" y="104" font-size="13" fill="{ink}">With Aarogya-Vāyu</text>']
    regions = (("lucknow", "Winter smog, Lucknow-Unnao"), ("bhubaneswar", "Heatwave, Bhubaneswar-Cuttack"))
    pw = (W - 96) / 2
    base_y, bar_h = 410, 230
    for p, (region, title) in enumerate(regions):
        x0 = 32 + p * (pw + 32)
        parts.append(f'<text x="{x0}" y="140" font-size="16" font-weight="700" fill="{ink}">{title}</text>')
        top = max(results[w][region]["status_quo"]["stockout_days"] for w in WINDOWS) or 1
        for g, w in enumerate(WINDOWS):
            r = results[w][region]
            gx = x0 + 8 + g * (pw / len(WINDOWS))
            for k, (arm, colour) in enumerate((("status_quo", clay), ("with_app", teal))):
                v = r[arm]["stockout_days"]
                h = max(2, bar_h * v / top)
                bx = gx + k * 56
                parts.append(f'<rect x="{bx:.0f}" y="{base_y - h:.0f}" width="48" height="{h:.0f}" rx="5" fill="{colour}"/>')
                parts.append(f'<text x="{bx + 24:.0f}" y="{base_y - h - 7:.0f}" text-anchor="middle" font-size="13" font-weight="800" fill="{ink}">{v:,.0f}</text>')
            pct = r["change"]["stockout_days_pct"]
            parts.append(f'<text x="{gx + 52:.0f}" y="{base_y + 22}" text-anchor="middle" font-size="13" fill="{muted}">first {w} days</text>')
            parts.append(f'<text x="{gx + 52:.0f}" y="{base_y + 42}" text-anchor="middle" font-size="14" font-weight="800" fill="{teal}">{pct:+.0f}%</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def main():
    results = {w: {region: summarise(region, w) for region in ("lucknow", "bhubaneswar")} for w in WINDOWS}
    report = {
        "assumptions": __doc__.split("Run:")[0].strip(),
        "windows_days": list(WINDOWS), "seeds": SEEDS, "results": results,
    }
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "impact.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (ROOT / "docs" / "impact.svg").write_text(svg_chart(results), encoding="utf-8")
    for w in WINDOWS:
        for region, r in results[w].items():
            sq, app = r["status_quo"], r["with_app"]
            print(f"first {w:2d} days | {EVENTS[region][0]:30s} | clinic stockout-days {sq['stockout_days']:7.1f} -> {app['stockout_days']:7.1f}"
                  f" ({r['change']['stockout_days_pct']:+.1f}%) | unmet doses {sq['unmet_doses']:9.1f} -> {app['unmet_doses']:9.1f}"
                  f" ({r['change']['unmet_doses_pct']:+.1f}%) | transfers {app['transfers']} ({app['units_moved']:.0f} units, {app['km']:.0f} km)")


if __name__ == "__main__":
    main()
