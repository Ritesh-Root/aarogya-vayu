"""
Shelf-photo verification: a multimodal LLM (Gemini primary, Claude fallback) reads a photo of a
medicine cupboard, and the result is compared against the facility's stock register.
The output is advisory evidence only; it never writes stock.
"""

import base64
import binascii
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from app.llm import generate_json

MAX_IMAGE_BYTES = 3 * 1024 * 1024
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}


class ShelfItem(BaseModel):
    medicine_name: str
    matched_medicine_id: Optional[str] = None
    batch_number: Optional[str] = None
    expiry_text: Optional[str] = None
    unit_count_estimate: int
    packaging_condition: str = ""


class ShelfScan(BaseModel):
    is_medicine_shelf: bool
    items: List[ShelfItem]
    notes: str = ""


def decode_image(image_base64: str, mime_type: Optional[str]) -> Tuple[bytes, str]:
    """Accepts raw base64 or a data URL; raises ValueError on bad input."""
    data = image_base64 or ""
    if data.startswith("data:"):
        header, _, data = data.partition(",")
        mime_type = header[5:].split(";")[0] or mime_type
    mime = (mime_type or "image/jpeg").lower()
    if mime not in ALLOWED_MIME:
        raise ValueError("Unsupported image type; use JPEG, PNG or WebP")
    if len(data) > MAX_IMAGE_BYTES * 4 // 3 + 4:
        raise ValueError("Image too large (max 3 MB)")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("image_base64 is not valid base64")
    if not raw:
        raise ValueError("Empty image")
    return raw, mime


async def scan_shelf(image: Tuple[bytes, str], medicines: Dict[str, dict]) -> Optional[Tuple[ShelfScan, str]]:
    catalogue = "\n".join(f"- {mid}: {m['name']}" for mid, m in medicines.items())
    system = (
        "You inspect photos of medicine shelves in Indian primary health centres. "
        "List each distinct medicine product you can see. Count visible units (strips, bottles, sachets, ampoules) "
        "as best you can, and read batch numbers and expiry dates only if they are legible; otherwise leave them null. "
        "Map each product to one of these catalogue IDs when it clearly matches, else null:\n" + catalogue +
        "\nIf the photo is not a medicine shelf, set is_medicine_shelf to false and return no items. Never invent text you cannot read."
    )
    return await generate_json(system, "Inspect this shelf photo.", ShelfScan, image=image)


def compare_with_register(scan: ShelfScan, facility_id: str, inventory: List[dict], medicines: Dict[str, dict]) -> List[dict]:
    """Attach the register's available count to each matched item and flag mismatches."""
    rows = []
    for item in scan.items:
        mid = item.matched_medicine_id if item.matched_medicine_id in medicines else None
        register = None
        if mid:
            register = sum(
                i.get("available", i.get("current_stock", 0))
                for i in inventory if i["facility_id"] == facility_id and i["medicine_id"] == mid
            )
        row = item.model_dump()
        row["matched_medicine_id"] = mid
        row["register_available"] = register
        row["discrepancy_units"] = abs(item.unit_count_estimate - register) if register is not None else None
        rows.append(row)
    return rows
