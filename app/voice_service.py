import re
import os
import json
import httpx
from typing import Dict, Any, Optional, Tuple
from app.models import VoiceIntakeRequest, VoiceIntakeResponse

class VoiceIntakeService:
    def __init__(self, facilities: Dict[str, dict], medicines: Dict[str, dict]):
        self.facilities = facilities
        self.medicines = medicines
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        # Experiential gateway for gpt-6-astra (OpenAI Chat Completions)
        # Base URL: https://api.experientiallabs.ai/v1  | Model: gpt-6-astra
        # Auth via EXPLABS_API_KEY. See app/experiential_client.py
        self.experiential_api_key = os.getenv("EXPLABS_API_KEY", "")
        self.experiential_base_url = "https://api.experientiallabs.ai/v1"
        self.experiential_model = "gpt-6-astra"  # exact - do not change

    def _require_experiential_key(self) -> str:
        """Return EXPLABS_API_KEY or raise with Settings -> API keys instructions."""
        key = self.experiential_api_key or os.getenv("EXPLABS_API_KEY", "")
        if not key:
            raise RuntimeError(
                "EXPLABS_API_KEY is not set. Create one under Settings -> API keys "
                "at https://api.experientiallabs.ai and export it: "
                "export EXPLABS_API_KEY='xpl_...' (refusing to call gpt-6-astra without key)"
            )
        return key

    async def parse_and_validate(self, request: VoiceIntakeRequest) -> VoiceIntakeResponse:
        """
        Parses frontline speech/text input into structured inventory updates.
        Priority:
          1) gpt-6-astra via Experiential gateway (https://api.experientiallabs.ai/v1)
             if EXPLABS_API_KEY is set — uses OpenAI Chat Completions, preserves
             streaming and tool_calls passthrough.
          2) Gemini LLM extraction if GEMINI_API_KEY is present
          3) Intelligent regex-based multilingual fallback
        """
        text = request.transcript_text.strip()

        # 1) Try gpt-6-astra via Experiential first (if key present)
        if os.getenv("EXPLABS_API_KEY"):
            try:
                extracted = await self._call_experiential_gpt6_astra(text, request.facility_id)
                if extracted:
                    return self._build_response(extracted, text, "hi" if re.search(r'[\u0900-\u097F]', text) else "en")
            except RuntimeError as e:
                # Missing key already handled — propagate message, don't fallback silently
                print(f"Experiential gating: {e}")
                raise
            except Exception as e:
                print(f"Experiential gpt-6-astra fallback triggered: {e}")

        # 2) Try Gemini API if key is set
        if self.gemini_api_key:
            try:
                extracted = await self._call_gemini(text, request.facility_id)
                if extracted:
                    return self._build_response(extracted, text, "hi" if re.search(r'[\u0900-\u097F]', text) else "en")
            except Exception as e:
                print(f"Gemini API fallback triggered: {e}")

        # 3) Intelligent Multilingual Heuristic Fallback
        return self._heuristic_extraction(text, request.facility_id)

    async def _call_experiential_gpt6_astra(self, text: str, hint_facility_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """
        Calls gpt-6-astra via Experiential gateway (OpenAI Chat Completions).
        Base URL: https://api.experientiallabs.ai/v1
        Auth:     EXPLABS_API_KEY (Bearer)
        Model:    gpt-6-astra (exact)
        Preserves streaming and tool_calls params (passed through when needed).
        """
        api_key = self._require_experiential_key()
        url = f"{self.experiential_base_url}/chat/completions"

        system_prompt = (
            "You are an expert AI clinical data parser for rural Indian Primary Health Centres (PHCs). "
            "Extract the following fields from frontline staff messages in Hindi, Hinglish, or English:\n"
            "- facility_id: (match from available facilities or return best match)\n"
            "- medicine_id: (match from MED-001 to MED-006)\n"
            "- reported_stock: integer\n"
            "- dispensed_yesterday: integer or null\n"
            "Output strictly valid JSON with keys: facility_id, medicine_id, reported_stock, dispensed_yesterday, confidence."
        )
        prompt = f"Available facilities: {list(self.facilities.keys())}\nAvailable medicines: {list(self.medicines.keys())}\nInput text: {text}"

        payload: Dict[str, Any] = {
            "model": self.experiential_model,  # gpt-6-astra exactly
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            # temperature omitted - gpt-6-astra route returns 400 for temperature
            "response_format": {"type": "json_object"},
            # streaming and tool_calls are preserved - callers can add:
            # "stream": False, "tools": [...], "tool_choice": "auto"
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            # OpenAI Chat Completions shape
            content = data["choices"][0]["message"]["content"]
            # content is JSON string per response_format
            return json.loads(content)

    async def _call_gemini(self, text: str, hint_facility_id: Optional[str]) -> Optional[Dict[str, Any]]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={self.gemini_api_key}"
        
        system_prompt = (
            "You are an expert AI clinical data parser for rural Indian Primary Health Centres (PHCs). "
            "Extract the following fields from frontline staff messages in Hindi, Hinglish, or English:\n"
            "- facility_id: (match from available facilities or return best match)\n"
            "- medicine_id: (match from MED-001 to MED-006)\n"
            "- reported_stock: integer\n"
            "- dispensed_yesterday: integer or null\n"
            "Output strictly valid JSON with keys: facility_id, medicine_id, reported_stock, dispensed_yesterday, confidence."
        )

        prompt = f"Available facilities: {list(self.facilities.keys())}\nAvailable medicines: {list(self.medicines.keys())}\nInput text: {text}"
        payload = {
            "contents": [{"parts": [{"text": system_prompt + "\n" + prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"}
        }

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                raw_json = data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(raw_json)
        return None

    def _build_response(self, extracted: Dict[str, Any], raw_text: str, lang_hint: str) -> VoiceIntakeResponse:
        """Build VoiceIntakeResponse from LLM-extracted JSON (shared by Gemini and gpt-6-astra paths)."""
        fac_id = extracted.get("facility_id") or "PHC-LKO-01"
        med_id = extracted.get("medicine_id") or "MED-001"
        reported = int(extracted.get("reported_stock", 15))
        dispensed = extracted.get("dispensed_yesterday")
        if dispensed is not None:
            try:
                dispensed = int(dispensed)
            except Exception:
                dispensed = None
        confidence = float(extracted.get("confidence", 0.92))
        fac_meta = self.facilities.get(fac_id, {"name": f"Facility {fac_id}"})
        med_meta = self.medicines.get(med_id, {"name": f"Medicine {med_id}"})
        # Reuse heuristic quality checks
        anomaly_flag = None
        quality_passed = True
        if reported < 0:
            quality_passed = False
            anomaly_flag = "Negative stock count reported"
        elif reported > 5000:
            quality_passed = False
            anomaly_flag = "Implausibly high stock (>5,000 units) for a rural facility. Flagged for verification."
        return VoiceIntakeResponse(
            facility_id=fac_id,
            facility_name=fac_meta["name"],
            medicine_id=med_id,
            medicine_name=med_meta["name"],
            reported_stock=reported,
            dispensed_yesterday=dispensed,
            confidence_score=confidence if quality_passed else 0.45,
            detected_language="Hindi" if lang_hint == "hi" else "English / Hinglish",
            quality_checks_passed=quality_passed,
            anomaly_flag=anomaly_flag,
            raw_transcript=raw_text,
            action_taken=f"Updated facility inventory ledger to {reported} units. Risk engine recomputed." if quality_passed else "Held in audit queue for officer review.",
        )

    def _transliterated_match(self, eng_word: str, text: str) -> bool:
        hindi_map = {
            "kakori": "काकोरी",
            "malihabad": "मलिहाबाद",
            "sarojini": "सरोजिनी",
            "nawabganj": "नवाबगंज",
            "chinhat": "चिनहट",
            "mohanlalganj": "मोहनलालगंज",
            "gosainganj": "गोसाईंगंज",
            "hasanganj": "हसनगंज",
            "safipur": "सफीपुर",
            "purwa": "पुरवा",
            "bighapur": "बीघापुर",
            "itaunja": "इटौंजा",
            "alambagh": "आलमबाग",
            "nagram": "नग्राम"
        }
        val = hindi_map.get(eng_word.lower())
        return bool(val and val in text)

    def _heuristic_extraction(self, text: str, hint_facility_id: Optional[str]) -> VoiceIntakeResponse:
        # Detect language
        has_devanagari = bool(re.search(r'[\u0900-\u097F]', text))
        lang = "hi" if has_devanagari else "en"
        lower_text = text.lower()

        # Match Facility
        matched_fac_id = hint_facility_id
        if not matched_fac_id:
            for fid, fmeta in self.facilities.items():
                name_parts = fmeta["name"].lower().split()
                # Check each significant word in the facility name
                for part in name_parts:
                    if len(part) > 3:
                        if part in lower_text or self._transliterated_match(part, text):
                            matched_fac_id = fid
                            break
                if matched_fac_id:
                    break

        if not matched_fac_id:
            matched_fac_id = "PHC-LKO-01"

        # Match Medicine
        matched_med_id = "MED-001"  # default to Salbutamol for demo scenario
        med_keywords = {
            "MED-001": ["salbutamol", "inhaler", "respule", "साल्बुटामोल", "रेस्प्यूल", "अस्थमा", "dama"],
            "MED-002": ["ors", "sachet", "electrolyte", "ओआरएस", "घोल", "डिहाइड्रेशन", "churan"],
            "MED-003": ["dexamethasone", "dexa", "injection", "डेक्सामेथासोन", "इंजेक्शन", "सूजन"],
            "MED-004": ["amoxicillin", "amoxy", "mox", "एमोक्सिसिलिन", "एंटीबायोटिक"],
            "MED-005": ["paracetamol", "pcm", "fever", "पैरासिटामोल", "बुखार"],
            "MED-006": ["cetirizine", "citrizen", "alerid", "सिट्रिजिन", "एलर्जी", "खांसी"]
        }

        for mid, kw_list in med_keywords.items():
            if any(kw in lower_text for kw in kw_list):
                matched_med_id = mid
                break

        # Extract Numbers
        # Hindi devanagari numerals mapping
        dev_digits = {'०': '0', '१': '1', '२': '2', '३': '3', '४': '4', '५': '5', '६': '6', '७': '7', '८': '8', '९': '9'}
        clean_text = text
        for d, digit in dev_digits.items():
            clean_text = clean_text.replace(d, digit)

        numbers = [int(n) for n in re.findall(r'\b\d+\b', clean_text)]

        reported_stock = 15
        dispensed_yesterday = None

        if len(numbers) >= 2:
            reported_stock = numbers[0]
            dispensed_yesterday = numbers[1]
        elif len(numbers) == 1:
            reported_stock = numbers[0]

        # Anomaly Detection & Quality Checks
        anomaly_flag = None
        quality_passed = True

        if reported_stock < 0:
            quality_passed = False
            anomaly_flag = "Negative stock count reported"
        elif reported_stock > 5000:
            quality_passed = False
            anomaly_flag = "Implausibly high stock (>5,000 units) for a rural facility. Flagged for verification."

        fac_meta = self.facilities.get(matched_fac_id, {"name": "PHC Kakori"})
        med_meta = self.medicines.get(matched_med_id, {"name": "Salbutamol Respirator Solution (Respules 2.5mg)"})

        return VoiceIntakeResponse(
            facility_id=matched_fac_id,
            facility_name=fac_meta["name"],
            medicine_id=matched_med_id,
            medicine_name=med_meta["name"],
            reported_stock=reported_stock,
            dispensed_yesterday=dispensed_yesterday,
            confidence_score=0.96 if quality_passed else 0.45,
            detected_language="Hindi" if lang == "hi" else "English / Hinglish",
            quality_checks_passed=quality_passed,
            anomaly_flag=anomaly_flag,
            raw_transcript=text,
            action_taken=f"Updated facility inventory ledger to {reported_stock} units. Risk engine recomputed." if quality_passed else "Held in audit queue for officer review."
        )
