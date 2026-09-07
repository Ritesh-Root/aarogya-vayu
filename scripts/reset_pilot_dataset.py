#!/usr/bin/env python3
"""
Aarogya-Vāyu Pilot Dataset Reset Utility.
Ensures every participant in the Usability Pilot starts with an identical,
isolated synthetic dataset with zero contamination from previous test sessions.
"""
import subprocess
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TMP_DIR = Path("/tmp/aarogya_vayu")

def reset_pilot_state():
    print("=== Aarogya-Vāyu Usability Pilot State Reset ===")
    
    # 1. Restore pristine inventory from git HEAD
    res = subprocess.run(["git", "checkout", "data/inventory.json"], cwd=BASE_DIR, capture_output=True, text=True)
    if res.returncode == 0:
        print("  [✓] data/inventory.json restored to pristine baseline from git.")
    else:
        print(f"  [!] Git restore warning: {res.stderr.strip()}")

    # 2. Reset active consignments and idempotency cache
    (DATA_DIR / "consignments.json").write_text("{}\n", encoding="utf-8")
    print("  [✓] data/consignments.json reset to empty.")

    (DATA_DIR / "idempotency.json").write_text("{}\n", encoding="utf-8")
    print("  [✓] data/idempotency.json reset to empty.")

    # 3. Clean ephemeral /tmp cache if present
    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR)
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        print("  [✓] Ephemeral /tmp/aarogya_vayu cache cleared.")

    print("\nEnvironment is 100% clean and ready for the next participant session.\n")

if __name__ == "__main__":
    reset_pilot_state()
