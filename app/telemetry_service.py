import os
import time
import json
import logging
import statistics
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from app.models import EnvironmentalReading

logger = logging.getLogger("aarogya_vayu.telemetry")

# GPS Centroids for Regional Corridors
COORDINATES = {
    "bhubaneswar": {
        "lat": 20.2961,
        "lng": 85.8245,
        "name": "Bhubaneswar–Cuttack Coastal & Industrial Corridor (Odisha)",
        "district": "Khordha",
        # IMD heatwave criterion: 37°C for coastal stations, 40°C for the plains
        "heatwave_threshold_c": 37.0,
    },
    "lucknow": {
        "lat": 26.8467,
        "lng": 80.9462,
        "name": "Lucknow-Unnao Indo-Gangetic Smog Corridor (Severe Inversion)",
        "district": "Lucknow",
        "heatwave_threshold_c": 40.0,
    }
}

IST = timezone(timedelta(hours=5, minutes=30))
USER_AGENT = {"User-Agent": "AarogyaVayu/2.0 (Health Logistics Resilience)"}
FIRMS_BBOX_DEG = 1.5  # ~165 km around the corridor centroid
FORECAST_HOURS = 72


def _get_json(url: str, timeout: float = 5) -> dict:
    req = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _split_hourly(times: List[str], values: List[Optional[float]], now_local: datetime):
    """Split an hourly series into (past, next-72h) lists of (hours_from_now, value), skipping nulls."""
    past, future = [], []
    for t, v in zip(times, values):
        if v is None:
            continue
        delta_h = (datetime.fromisoformat(t).replace(tzinfo=IST) - now_local).total_seconds() / 3600
        if delta_h <= 0:
            past.append((delta_h, v))
        elif delta_h <= FORECAST_HOURS:
            future.append((delta_h, v))
    return past, future


class LiveTelemetryService:
    """
    Fetches real-time and forecast atmospheric telemetry:
      - Open-Meteo Weather (ECMWF/GFS): temperature, humidity, wind, boundary layer height, 72h forecast
      - Open-Meteo Air Quality (Copernicus CAMS): AQI, PM2.5/PM10, aerosol optical depth with
        30-day history (for the anomaly) and 72h forecast
      - NASA FIRMS VIIRS active fires, when FIRMS_MAP_KEY is configured
    Open-Meteo needs no API key.
    """
    def __init__(self, cache_ttl_seconds: int = 300):
        self.cache_ttl = cache_ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _fetch_fire_hotspots(self, lat: float, lng: float) -> Optional[int]:
        key = os.getenv("FIRMS_MAP_KEY")
        if not key:
            return None
        bbox = f"{lng - FIRMS_BBOX_DEG},{lat - FIRMS_BBOX_DEG},{lng + FIRMS_BBOX_DEG},{lat + FIRMS_BBOX_DEG}"
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/{bbox}/2"
        try:
            req = urllib.request.Request(url, headers=USER_AGENT)
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode("utf-8").strip()
            lines = body.splitlines()
            if not lines or not lines[0].startswith("latitude"):
                logger.warning("Unexpected NASA FIRMS response: %s", body[:120])
                return None
            return len(lines) - 1
        except Exception as e:
            logger.warning("NASA FIRMS fetch failed: %s", e)
            return None

    def fetch_live_reading(self, region: str = "bhubaneswar") -> EnvironmentalReading:
        reg = region.lower()
        coords = COORDINATES.get(reg, COORDINATES["bhubaneswar"])

        # Check cache
        now = time.time()
        cached = self._cache.get(reg)
        if cached and (now - cached["timestamp"] < self.cache_ttl):
            return cached["reading"]

        try:
            lat, lng = coords["lat"], coords["lng"]
            w_data = _get_json(
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}"
                f"&current=temperature_2m,relative_humidity_2m,wind_speed_10m"
                f"&hourly=temperature_2m,boundary_layer_height&forecast_days=4"
                f"&timezone=Asia%2FKolkata"
            )
            aq_data = _get_json(
                f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lng}"
                f"&current=pm10,pm2_5,us_aqi,aerosol_optical_depth"
                f"&hourly=us_aqi,pm2_5,aerosol_optical_depth&past_days=30&forecast_days=4"
                f"&timezone=Asia%2FKolkata"
            )

            curr_w = w_data.get("current", {})
            curr_aq = aq_data.get("current", {})

            temp_c = float(curr_w["temperature_2m"])
            humidity = float(curr_w["relative_humidity_2m"])
            wind_kmh = float(curr_w["wind_speed_10m"])
            pm25 = float(curr_aq["pm2_5"])
            pm10 = float(curr_aq["pm10"]) if curr_aq.get("pm10") is not None else None
            aqi = int(curr_aq["us_aqi"])
            aod = curr_aq.get("aerosol_optical_depth")

            now_local = datetime.now(IST).replace(minute=0, second=0, microsecond=0)
            w_hourly = w_data.get("hourly", {})
            aq_hourly = aq_data.get("hourly", {})
            times_w = w_hourly.get("time", [])
            times_aq = aq_hourly.get("time", [])

            _, temp_fc = _split_hourly(times_w, w_hourly.get("temperature_2m", []), now_local)
            blh_past, _ = _split_hourly(times_w, w_hourly.get("boundary_layer_height", []), now_local)
            _, aqi_fc = _split_hourly(times_aq, aq_hourly.get("us_aqi", []), now_local)
            _, pm25_fc = _split_hourly(times_aq, aq_hourly.get("pm2_5", []), now_local)
            aod_past, _ = _split_hourly(times_aq, aq_hourly.get("aerosol_optical_depth", []), now_local)

            aod_sigma = None
            aod_hist = [v for _, v in aod_past]
            if aod is not None and len(aod_hist) >= 48:
                sd = statistics.pstdev(aod_hist)
                if sd > 0:
                    aod_sigma = round((float(aod) - statistics.fmean(aod_hist)) / sd, 2)

            peak_h, peak_aqi = max(aqi_fc, key=lambda x: x[1]) if aqi_fc else (None, None)
            max_temp_72h = max(v for _, v in temp_fc) if temp_fc else None
            boundary_layer = blh_past[-1][1] if blh_past else None
            fires = self._fetch_fire_hotspots(lat, lng)

            hottest = max(temp_c, max_temp_72h or temp_c)
            reading = EnvironmentalReading(
                aqi=aqi,
                pm25=pm25,
                pm10=pm10,
                temperature_c=temp_c,
                humidity_pct=humidity,
                wind_speed_kmh=wind_kmh,
                heatwave_alert=hottest >= coords["heatwave_threshold_c"],
                smog_episode=(aqi >= 200 or pm25 >= 120.0 or (peak_aqi or 0) >= 200),
                corridor=f"{coords['name']} (Live Real-Time Telemetry)",
                source="Open-Meteo & Copernicus Atmospheric Monitoring Service (CAMS)"
                + (" + NASA FIRMS" if fires is not None else ""),
                recorded_at=curr_aq.get("time") or curr_w.get("time"),
                aod=float(aod) if aod is not None else None,
                aod_anomaly_sigma=aod_sigma,
                boundary_layer_m=boundary_layer,
                forecast_peak_aqi_72h=int(peak_aqi) if peak_aqi is not None else None,
                forecast_peak_pm25_72h=max(v for _, v in pm25_fc) if pm25_fc else None,
                forecast_peak_in_hours=round(peak_h) if peak_h is not None else None,
                forecast_max_temp_72h=max_temp_72h,
                fire_hotspots=fires,
            )

            self._cache[reg] = {
                "timestamp": now,
                "reading": reading
            }
            return reading

        except Exception as e:
            logger.warning(f"Could not fetch real-time Open-Meteo telemetry for {region}: {e}. Using baseline fallback.")
            if cached:
                return cached["reading"]

            # Clearly labelled offline baseline; is_live is derived from `source`, so this never shows as live
            return EnvironmentalReading(
                aqi=68 if reg == "bhubaneswar" else 78,
                pm25=22.4 if reg == "bhubaneswar" else 26.8,
                temperature_c=27.5 if reg == "bhubaneswar" else 28.0,
                humidity_pct=82.0 if reg == "bhubaneswar" else 76.0,
                wind_speed_kmh=9.5 if reg == "bhubaneswar" else 12.0,
                heatwave_alert=False,
                smog_episode=False,
                corridor=f"{coords['name']} (Offline Baseline)",
                source="Offline baseline (live feed unavailable)"
            )

telemetry_service = LiveTelemetryService()
