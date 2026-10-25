// Each browser keeps its own Conditions choice (live / smog / heat / normal) and sends it with every
// API call, so one visitor pressing Smog doesn't change what everyone else sees. Until a visitor picks
// one, nothing is sent and the server's own default applies.
const SCENARIO_KEY = 'aarogya.scenario';
const SCENARIO_NAMES = ['live', 'smog', 'heat', 'flood', 'cold', 'normal'];
let currentScenario = null;
try {
  const saved = localStorage.getItem(SCENARIO_KEY);
  if (SCENARIO_NAMES.includes(saved)) currentScenario = saved;
} catch (e) { /* storage blocked: start on live */ }
const nativeFetch = window.fetch.bind(window);
window.fetch = (input, init) => {
  if (currentScenario && typeof input === 'string' && input.startsWith('/api/')) {
    input += (input.includes('?') ? '&' : '?') + 'scenario=' + encodeURIComponent(currentScenario);
  }
  return nativeFetch(input, init);
};

let map;
let facilityMarkers = {};
let transferLines = [];
let facilities = [];
let activeRecs = [];
let allRisks = [];
let facRiskSummary = {};
let allLogs = [];
let activeSearchQuery = '';
let currentLang = 'en';

// Regional Corridors Configuration
let currentRegion = 'bhubaneswar';

const REGIONS = {
  bhubaneswar: {
    id: 'bhubaneswar',
    name: 'Bhubaneswar–Cuttack Health Corridor (Odisha)',
    shortName: 'Bhubaneswar (OD)',
    center: [20.30, 85.83],
    zoom: 10,
    defaultFacility: 'PHC-BBS-01',
    polygon: [
      [20.62, 85.65],
      [20.65, 86.18],
      [20.45, 86.22],
      [20.10, 86.12],
      [19.90, 85.35],
      [20.15, 85.25],
      [20.40, 85.60]
    ],
    sensors: [
      {
        id: "SNS-BBS-01",
        name: "Chandrasekharpur OSPCB CAAQMS",
        type: "Continuous Ambient Air Quality Node",
        lat: 20.325,
        lng: 85.820
      },
      {
        id: "SNS-BBS-02",
        name: "Biju Patnaik Airport Met (IMD)",
        type: "Synoptic Automated Doppler Node",
        lat: 20.252,
        lng: 85.818
      },
      {
        id: "SNS-CTC-03",
        name: "Cuttack Badambadi Transport Hub OSPCB",
        type: "Urban Traffic Emission Node",
        lat: 20.463,
        lng: 85.877
      },
      {
        id: "SNS-BBS-04",
        name: "Khordha Industrial Estate IoT Sensor",
        type: "Industrial Emission Monitoring Stn",
        lat: 20.180,
        lng: 85.620
      },
      {
        id: "SNS-CTC-05",
        name: "Choudwar Industrial Complex Sensor",
        type: "OSPCB Real-time Industrial Stn",
        lat: 20.525,
        lng: 85.920
      }
    ]
  },
  lucknow: {
    id: 'lucknow',
    name: 'Lucknow–Unnao Health Corridor (UP)',
    shortName: 'Lucknow (UP)',
    center: [26.75, 80.72],
    zoom: 10,
    defaultFacility: 'PHC-LKO-01',
    polygon: [
      [27.02, 80.45],
      [27.00, 80.85],
      [26.90, 81.16],
      [26.72, 81.15],
      [26.54, 80.70],
      [26.46, 80.35],
      [26.60, 80.22],
      [26.85, 80.32]
    ],
    sensors: [
      {
        id: "SNS-LKO-01",
        name: "Talkatora Industrial CPCB Stn",
        type: "Continuous Ambient Air Quality Node",
        lat: 26.832,
        lng: 80.892
      },
      {
        id: "SNS-LKO-02",
        name: "Amausi Airport Met Center (IMD)",
        type: "Synoptic Automated Doppler Node",
        lat: 26.760,
        lng: 80.880
      },
      {
        id: "SNS-UNA-03",
        name: "Unnao Industrial Cluster Node",
        type: "UPPCB IoT Emission Hub",
        lat: 26.545,
        lng: 80.495
      },
      {
        id: "SNS-LKO-04",
        name: "Malihabad Agro-Met Station",
        type: "Agri-Weather & Particulate Node",
        lat: 26.925,
        lng: 80.705
      },
      {
        id: "SNS-LKO-05",
        name: "Gomti River Basin Hydrological Node",
        type: "River Valley Inversion Monitor",
        lat: 26.865,
        lng: 80.950
      }
    ]
  }
};

// Clinic Daily Desk State
let currentClinicFacilityId = "PHC-BBS-01";
let activeClinicDeskData = null;
let selectedStockActionType = "PHYSICAL_COUNT";
let currentStockActionMedicineId = null;
let currentStockActionBatchNumber = null;
let currentReceiptConsignment = null;
let currentDispatchConsignment = null;
let clinicInventoryFilterQuery = '';

// Advanced Atmospheric GIS & Courier Fleet Telemetry
let facilityMarkersLayer = null;
let courierMarkersLayer = null;
let sensorMarkersLayer = null;
let atmosphericPlumeLayer = null;
let activeCouriers = [];
let regionConsignments = [];
let courierTransitInterval = null;
let activeMapFilter = 'all';
let currentInspectFacilityId = null;
let isSpeaking = false;
let currentTelemetry = null;

// Regional News & Intelligence Bureau State
let allNewsArticles = [];
let activeNewsCategory = 'all';
let activeNewsSearch = '';

document.addEventListener('DOMContentLoaded', async () => {
  initMap();
  await loadInitialData(true);
  setupEventListeners();
  lucide.createIcons();

  const urlParams = new URLSearchParams(window.location.search);
  const view = urlParams.get('view') || urlParams.get('tab');
  if (view) {
    setTimeout(async () => {
      if (view === 'clinic') {
        switchMainView('clinic');
      } else if (view === 'cmo') {
        openCmoModal();
        setTimeout(() => askCmoQuery(1), 200);
      } else if (view === 'ledger') {
        openLedgerModal();
      } else if (view === 'challan') {
        const rId = (activeRecs && activeRecs.length > 0) ? activeRecs[0].id : 'REC-ABA38C63';
        showChallanModal(rId);
      } else if (view === 'facility') {
        const fId = (facilities && facilities.length > 0) ? facilities[0].id : 'FAC-001';
        openFacilityDetail(fId);
      } else if (view === 'map') {
        const mapEl = document.getElementById('map');
        if (mapEl) mapEl.scrollIntoView({ behavior: 'instant', block: 'start' });
        loadSampleVoice(1);
        setTimeout(() => submitVoiceIntake(), 200);
      } else if (view === 'agents') {
        const term = document.getElementById('agentTerminalBody');
        if (term) term.scrollIntoView({ behavior: 'instant', block: 'center' });
        await runAgentPipeline();
      } else if (view === 'vision') {
        const btnV = document.getElementById('btnVision');
        if (btnV) btnV.scrollIntoView({ behavior: 'instant', block: 'center' });
      }
    }, 400);
  }
});

function initMap() {
  const reg = REGIONS[currentRegion] || REGIONS['bhubaneswar'];
  map = L.map('map', { zoomControl: true }).setView(reg.center, reg.zoom);
  
  // Standard OpenStreetMap tiles (100% free, zero watermark, crystal clear)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19
  }).addTo(map);

  // Initialize Layer Groups
  facilityMarkersLayer = L.layerGroup().addTo(map);
  courierMarkersLayer = L.layerGroup().addTo(map);
  sensorMarkersLayer = L.layerGroup().addTo(map);

  setTimeout(() => {
    map.invalidateSize();
  }, 250);

  window.addEventListener('resize', () => {
    if (map) map.invalidateSize();
  });

  // Start continuous vehicle animation loop
  startCourierAnimationLoop();
}

function updateRegionButtons(regId) {
  const btnBbs = document.getElementById('btnRegionBbs');
  const btnLko = document.getElementById('btnRegionLko');
  const sub = document.getElementById('networkSubtitle');
  if (btnBbs && btnLko) {
    if (regId === 'bhubaneswar') {
      btnBbs.className = 'px-3.5 py-2 rounded-full font-black text-xs sm:text-sm bg-clay-terracotta text-white shadow-clay-btn transition flex items-center space-x-1.5';
      btnLko.className = 'px-3.5 py-2 rounded-full font-black text-xs sm:text-sm text-clay-muted hover:text-clay-dark hover:bg-white transition flex items-center space-x-1.5';
      if (sub) sub.textContent = 'Bhubaneswar–Cuttack · tap a clinic to see its stock';
    } else {
      btnLko.className = 'px-3.5 py-2 rounded-full font-black text-xs sm:text-sm bg-clay-terracotta text-white shadow-clay-btn transition flex items-center space-x-1.5';
      btnBbs.className = 'px-3.5 py-2 rounded-full font-black text-xs sm:text-sm text-clay-muted hover:text-clay-dark hover:bg-white transition flex items-center space-x-1.5';
      if (sub) sub.textContent = 'Lucknow–Unnao · tap a clinic to see its stock';
    }
  }
}

async function switchRegion(regionId) {
  if (!REGIONS[regionId]) return;
  try {
    const res = await fetch('/api/region/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ region: regionId })
    });
    if (!res.ok) throw new Error(await apiErrorMessage(res, 'Region switch failed'));
  } catch (e) {
    console.error("switchRegion error:", e);
    alert(e.message || 'Region switch failed');
    return;
  }
  currentRegion = regionId;
  updateRegionButtons(regionId);

  if (map && REGIONS[regionId]) {
    map.setView(REGIONS[regionId].center, REGIONS[regionId].zoom);
  }

  currentClinicFacilityId = REGIONS[regionId].defaultFacility;

  await fetchEnvironmental();
  await fetchFacilities();
  await fetchRisks();
  await fetchRecommendations();
  await fetchAuditLog();
  await fetchNews(regionId);
  await loadClinicDesk(currentClinicFacilityId);
}

// The region the user picked is the source of truth; the server's per-instance active region is
// only adopted on first page load
async function loadInitialData(adoptServerRegion = false) {
  try {
    if (adoptServerRegion) try {
      const regRes = await fetch('/api/regions');
      if (regRes.ok) {
        const regData = await regRes.json();
        if (regData.active_region && REGIONS[regData.active_region]) {
          currentRegion = regData.active_region;
          currentClinicFacilityId = REGIONS[currentRegion].defaultFacility;
          updateRegionButtons(currentRegion);
          if (map) {
            map.setView(REGIONS[currentRegion].center, REGIONS[currentRegion].zoom);
          }
        }
      }
    } catch (e) {
      console.warn("Could not query /api/regions:", e);
    }

    await fetchEnvironmental();
    await fetchFacilities();
    await fetchRisks();
    await fetchRecommendations();
    await fetchAuditLog();
    await fetchNews(currentRegion);
    await loadClinicDesk(currentClinicFacilityId);
  } catch (err) {
    console.error("Initialization error:", err);
  }
}

async function fetchEnvironmental() {
  try {
    const res = await fetch(`/api/environmental?region=${encodeURIComponent(currentRegion)}`);
    if (!res.ok) throw new Error(`environmental HTTP ${res.status}`);
    const data = await res.json();
    const t = data.telemetry;
    currentTelemetry = t;

    const valAqi = document.getElementById('valAqi');
    if (valAqi) valAqi.textContent = `${t.aqi} (${aqiCategory(t.aqi)})`;

    const valPm25 = document.getElementById('valPm25');
    if (valPm25) valPm25.textContent = `${t.pm25} µg/m³`;

    const valTemp = document.getElementById('valTemp');
    if (valTemp) valTemp.textContent = `${t.temperature_c}°C`;

    const valCorridor = document.getElementById('valCorridor');
    if (valCorridor) valCorridor.textContent = t.corridor;

    const bannerTitle = document.getElementById('bannerTitle');
    const bannerDesc = document.getElementById('bannerDesc');
    const mults = data.surge_multipliers || {};

    // Exactly one surge-mode button is highlighted, matching the server's mode for this region
    const isLiveMode = data.mode === 'live';
    const activeScenario = isLiveMode ? 'live' : (data.scenario || (t.smog_episode ? 'smog' : (t.heatwave_alert ? 'heat' : (t.flood_alert ? 'flood' : (t.cold_wave_alert ? 'cold' : 'normal')))));
    highlightScenarioButton(activeScenario);

    // Banner uses the short area name: "Lucknow-Unnao (UP)" rather than the full corridor description
    const corridorName = escapeHtml((t.corridor || 'Regional Corridor').replace(/ [^()]*Corridor/, ''));
    const area = t.corridor ? t.corridor.replace(/ [^()]*Corridor/, '') : 'this region';
    const pct = key => Math.round(((mults[key] || 1) - 1) * 100);
    if (isLiveMode && data.is_live) {
      if (bannerTitle) bannerTitle.innerHTML = `<span class="inline-flex flex-wrap items-center gap-x-2 gap-y-1"><span>Today's air: ${corridorName}</span><span class="whitespace-nowrap text-[10px] leading-none bg-emerald-500/40 text-emerald-50 border border-emerald-300/50 px-2 py-1 rounded-full uppercase tracking-wider font-extrabold">Live</span></span>`;
      const hazards = [t.flood_alert ? `very heavy rain (${t.rain_24h_mm} mm/24 h)` : '', t.cold_wave_alert ? `cold wave (min ${t.min_temp_c}°C)` : '']
        .filter(Boolean).join(' and ');
      if (bannerDesc) bannerDesc.textContent = `AQI ${t.aqi} (${aqiCategory(t.aqi)}) · PM2.5 ${t.pm25} µg/m³ · ${t.temperature_c}°C · humidity ${t.humidity_pct ?? 'n/a'}% · wind ${t.wind_speed_kmh ?? 'n/a'} km/h${hazards ? ` · Alert: ${hazards}` : ''}. Source: Open-Meteo and Copernicus CAMS.`;
    } else if (isLiveMode) {
      if (bannerTitle) bannerTitle.textContent = `${area}: live air data unavailable`;
      if (bannerDesc) bannerDesc.textContent = `Showing a stored baseline, not live data · AQI ${t.aqi} · ${t.temperature_c}°C`;
    } else if (t.smog_episode) {
      if (bannerTitle) bannerTitle.textContent = `Demo: winter smog over ${area}`;
      if (bannerDesc) bannerDesc.textContent = `AQI ${t.aqi} · PM2.5 ${t.pm25} µg/m³ · demand for breathing medicines up ${pct('AQI / Smog')}%. Hospital visits rise 1–3 days after a PM2.5 peak.`;
    } else if (t.flood_alert) {
      if (bannerTitle) bannerTitle.textContent = `Demo: flood and heavy rain, ${area}`;
      if (bannerDesc) bannerDesc.textContent = `${t.rain_24h_mm ?? 'n/a'} mm of rain in 24 h · ORS demand up ${pct('Heatwave / Drought')}%, fever medicine up ${pct('Heat / Infection')}%. Diarrhoea and fever cases rise in the days after.`;
    } else if (t.cold_wave_alert) {
      if (bannerTitle) bannerTitle.textContent = `Demo: cold wave over ${area}`;
      if (bannerDesc) bannerDesc.textContent = `Minimum ${t.min_temp_c ?? t.temperature_c}°C · antibiotic demand up ${pct('Secondary Respiratory')}% for chest infections; AQI ${t.aqi}.`;
    } else if (t.heatwave_alert) {
      if (bannerTitle) bannerTitle.textContent = `Demo: heatwave over ${area}`;
      if (bannerDesc) bannerDesc.textContent = `${t.temperature_c}°C · demand for ORS (rehydration salts) up ${pct('Heatwave / Drought')}%.`;
    } else {
      if (bannerTitle) bannerTitle.textContent = `Demo: normal conditions over ${area}`;
      if (bannerDesc) bannerDesc.textContent = `AQI ${t.aqi} · ${t.temperature_c}°C · medicines used at their usual rate.`;
    }

    // Render Atmospheric Inversion Plume & Ground Sensors
    updateAtmosphericPlume(t);
    updateSensorStations(t);
  } catch (err) {
    console.error("fetchEnvironmental error:", err);
  }
}

function updateAtmosphericPlume(t) {
  if (atmosphericPlumeLayer && map.hasLayer(atmosphericPlumeLayer)) {
    map.removeLayer(atmosphericPlumeLayer);
  }

  const reg = REGIONS[currentRegion] || REGIONS['bhubaneswar'];
  const corridorName = escapeHtml(t.corridor || reg.name);
  // Boundary layer height and wind come from Open-Meteo; ventilation index = mixing height × wind speed
  const blh = (typeof t.boundary_layer_m === 'number') ? Math.round(t.boundary_layer_m) : null;
  const ventIndex = (blh !== null && typeof t.wind_speed_kmh === 'number') ? Math.round(blh * t.wind_speed_kmh / 3.6) : null;
  const blhText = blh !== null ? `${blh.toLocaleString()} m AGL` : 'n/a (scenario)';
  const ventText = ventIndex !== null ? `${ventIndex.toLocaleString()} m²/s${ventIndex < 2000 ? ' (Stagnant)' : (ventIndex < 6000 ? ' (Moderate)' : ' (Good)')}` : 'n/a (scenario)';

  let strokeColor = '#DE6B48';
  let fillColor = '#DE6B48';
  let fillOpacity = 0.22;
  let label = `🌫️ ${corridorName} Inversion Corridor (AQI ${t.aqi})`;

  if (t.smog_episode) {
    strokeColor = '#C25433';
    fillColor = '#DE6B48';
    fillOpacity = 0.32;
    label = `🌫️ ${corridorName} Smog Inversion Corridor • Mixing Height: ${blhText} • AQI ${t.aqi} • PM2.5: ${t.pm25} µg/m³`;
  } else if (t.flood_alert) {
    strokeColor = '#1D4ED8';
    fillColor = '#3B82F6';
    fillOpacity = 0.28;
    label = `🌧️ ${corridorName} Flood Zone • Rain: ${t.rain_24h_mm ?? 'n/a'} mm/24 h • Diarrhoea & fever risk`;
  } else if (t.cold_wave_alert) {
    strokeColor = '#0E7490';
    fillColor = '#67E8F9';
    fillOpacity = 0.26;
    label = `❄️ ${corridorName} Cold Wave • Min: ${t.min_temp_c ?? t.temperature_c}°C • Chest infection risk`;
  } else if (t.heatwave_alert) {
    strokeColor = '#DC2626';
    fillColor = '#F97316';
    fillOpacity = 0.28;
    label = `🔥 ${corridorName} Heatwave Zone • Max Temp: ${t.temperature_c}°C • Extreme Dehydration Risk`;
  } else {
    fillOpacity = 0.08;
    strokeColor = '#0284C7';
    fillColor = '#38BDF8';
    label = `🍃 ${corridorName} Baseline Atmospheric Zone • AQI ${t.aqi} • Mixing Height: ${blhText}`;
  }

  atmosphericPlumeLayer = L.polygon(reg.polygon, {
    color: strokeColor,
    weight: 2,
    dashArray: '6, 8',
    fillColor: fillColor,
    fillOpacity: fillOpacity
  });

  atmosphericPlumeLayer.bindTooltip(label, {
    permanent: false,
    direction: 'center',
    className: 'text-xs font-bold font-sans'
  });

  atmosphericPlumeLayer.bindPopup(`
    <div class="p-1 font-sans text-xs space-y-1">
      <div class="flex items-center space-x-1.5 pb-1 border-b border-slate-200">
        <span class="w-2.5 h-2.5 rounded-full ${t.smog_episode ? 'bg-red-500 animate-ping' : (t.heatwave_alert ? 'bg-amber-500' : 'bg-blue-500')}"></span>
        <strong class="text-slate-900">${t.smog_episode ? 'Atmospheric Inversion Trap' : (t.heatwave_alert ? 'Heatwave Corridor' : 'Baseline Corridor')}</strong>
      </div>
      <div class="text-slate-600 space-y-0.5 text-[11px]">
        <div>Corridor: <strong class="text-slate-900">${corridorName}</strong></div>
        <div>Active AQI: <strong class="text-[#DE6B48]">${t.aqi}</strong> (PM2.5: ${t.pm25} µg/m³)</div>
        <div>Boundary Layer (mixing height): <strong>${blhText}</strong></div>
        <div>Ventilation Index: <strong>${ventText}</strong></div>
      </div>
    </div>
  `);

  if (activeMapFilter === 'all' || activeMapFilter === 'plume') {
    atmosphericPlumeLayer.addTo(map);
  }

  // Update Glassmorphic Map HUD
  const hudCorridor = document.getElementById('hudCorridor');
  if (hudCorridor) {
    hudCorridor.textContent = t.corridor || (currentRegion === 'bhubaneswar' ? 'Bhubaneswar-Cuttack' : 'Lucknow-Unnao');
  }
  const hudWind = document.getElementById('hudWind');
  if (hudWind) hudWind.textContent = (typeof t.wind_speed_kmh === 'number') ? `${t.wind_speed_kmh} km/h` : 'n/a';
  const hudLive = document.getElementById('hudLiveBadge');
  if (hudLive) hudLive.textContent = (t.source && t.source.includes('Open-Meteo')) ? 'LIVE' : 'SCENARIO';
  const hudInversion = document.getElementById('hudInversion');
  if (hudInversion) {
    if (blh !== null) {
      hudInversion.textContent = `${blh.toLocaleString()} m (${blh < 300 ? 'smog trapped' : (blh < 800 ? 'slow to clear' : 'clears normally')})`;
    } else {
      hudInversion.textContent = t.smog_episode ? "Smog demo" : (t.heatwave_alert ? "Heatwave demo" : (t.flood_alert ? "Flood demo" : (t.cold_wave_alert ? "Cold wave demo" : "Clears normally")));
    }
  }
}

function updateSensorStations(t) {
  if (!sensorMarkersLayer) return;
  sensorMarkersLayer.clearLayers();

  const reg = REGIONS[currentRegion] || REGIONS['bhubaneswar'];
  const sensorConfigs = reg.sensors || REGIONS['bhubaneswar'].sensors;

  // These are monitoring sites in the corridor; no per-station feed is wired in, so each pin shows
  // the corridor-level CAMS value rather than an invented station reading
  const sensorData = sensorConfigs.map((cfg) => {
    const aqiVal = t.aqi;
    return {
      id: cfg.id,
      name: cfg.name,
      type: cfg.type,
      lat: cfg.lat,
      lng: cfg.lng,
      aqi: Math.round(aqiVal),
      pm25: t.pm25,
      temp: t.temperature_c,
      status: aqiCategory(aqiVal)
    };
  });

  sensorData.forEach(s => {
    const isSevere = s.aqi > 300;
    const badgeBg = isSevere ? 'bg-purple-600' : (s.aqi > 200 ? 'bg-red-500' : 'bg-emerald-600');

    const sensorIcon = L.divIcon({
      className: 'sensor-node-marker',
      html: `
        <div class="flex items-center space-x-1.5 bg-slate-950/90 text-white px-2.5 py-1 rounded-full shadow-md border border-slate-700 cursor-pointer hover:scale-105 transition">
          <span class="text-sm">📡</span>
          <span class="text-xs font-black ${badgeBg} px-1.5 py-0.5 rounded text-white">${s.aqi}</span>
        </div>
      `,
      iconSize: [75, 26],
      iconAnchor: [37, 13]
    });

    const marker = L.marker([s.lat, s.lng], { icon: sensorIcon }).addTo(sensorMarkersLayer);

    marker.bindPopup(`
      <div class="p-1.5 font-sans text-xs sm:text-sm space-y-1.5">
        <div class="flex items-center space-x-2 pb-1.5 border-b border-slate-200">
          <span class="text-sm">📡</span>
          <span class="font-black text-slate-900 text-sm">${escapeHtml(s.name)}</span>
        </div>
        <div class="text-slate-600 text-xs space-y-1 font-medium">
          <div>Site Type: <strong class="text-slate-800">${escapeHtml(s.type)}</strong></div>
          <div>Corridor AQI: <strong class="${isSevere ? 'text-red-600 font-black' : 'text-slate-900 font-black'}">${s.aqi} (${s.status})</strong></div>
          <div>Corridor PM2.5: <strong class="text-slate-800">${s.pm25} µg/m³</strong></div>
          <div>Ambient Temp: <strong class="text-slate-800">${s.temp}°C</strong></div>
          <div class="text-[10px] text-slate-500 pt-0.5">Corridor-level CAMS value; this site's own station feed is not connected.</div>
        </div>
      </div>
    `);
  });
}

async function fetchFacilities() {
  try {
    const res = await fetch(`/api/facilities?region=${encodeURIComponent(currentRegion)}`);
    if (!res.ok) throw new Error(`facilities HTTP ${res.status}`);
    facilities = await res.json();
    
    renderVoiceSamples();
    const select = document.getElementById('voiceFacilitySelect');
    if (select) {
      select.innerHTML = '<option value="">Clinic: detect it from the report</option>';
      facilities.forEach(fac => {
        const opt = document.createElement('option');
        opt.value = fac.id;
        opt.textContent = `${fac.name} (${fac.district} - ${fac.type})`;
        select.appendChild(opt);
      });
    }

    const visionSelect = document.getElementById('visionFacilitySelect');
    if (visionSelect) {
      const keep = visionSelect.value;
      visionSelect.innerHTML = '';
      facilities.forEach(fac => {
        const opt = document.createElement('option');
        opt.value = fac.id;
        opt.textContent = `Compare with: ${fac.name}`;
        visionSelect.appendChild(opt);
      });
      visionSelect.value = facilities.some(f => f.id === keep) ? keep
        : (facilities.some(f => f.id === currentClinicFacilityId) ? currentClinicFacilityId : (facilities[0] ? facilities[0].id : ''));
    }

    const clinicSelect = document.getElementById('clinicFacilitySelect');
    if (clinicSelect) {
      clinicSelect.innerHTML = '';
      facilities.forEach(fac => {
        const opt = document.createElement('option');
        opt.value = fac.id;
        opt.textContent = `${fac.name} (${fac.type} - ${fac.district})`;
        clinicSelect.appendChild(opt);
      });
      if (facilities.length > 0) {
        const found = facilities.find(f => f.id === currentClinicFacilityId);
        if (!found) {
          currentClinicFacilityId = facilities[0].id;
        }
      }
      clinicSelect.value = currentClinicFacilityId;
    }
  } catch (err) {
    console.error("fetchFacilities error:", err);
  }
}

async function fetchRisks() {
  try {
    const res = await fetch(`/api/risks?region=${encodeURIComponent(currentRegion)}`);
    if (!res.ok) throw new Error(`risks HTTP ${res.status}`);
    allRisks = await res.json();

    // Aggregate risk per facility
    facRiskSummary = {};
    facilities.forEach(f => {
      facRiskSummary[f.id] = { criticalCount: 0, warningCount: 0, surplusCount: 0, items: [] };
    });

    let totalCriticalPhcs = 0;
    allRisks.forEach(r => {
      if (facRiskSummary[r.facility_id]) {
        facRiskSummary[r.facility_id].items.push(r);
        if (r.status === 'CRITICAL') facRiskSummary[r.facility_id].criticalCount++;
        if (r.status === 'WARNING') facRiskSummary[r.facility_id].warningCount++;
        if (r.status === 'SURPLUS') facRiskSummary[r.facility_id].surplusCount++;
      }
    });

    Object.values(facRiskSummary).forEach(s => {
      if (s.criticalCount > 0) totalCriticalPhcs++;
    });
    
    const statCriticalPhc = document.getElementById('statCriticalPhc');
    if (statCriticalPhc) statCriticalPhc.textContent = `${totalCriticalPhcs} Facilities`;

    // Render Watchlist in Right Panel
    renderWatchlist(activeSearchQuery);

    // Plot on Leaflet Map with Custom High-Fidelity Pins
    facilityMarkersLayer.clearLayers();
    facilityMarkers = {};

    facilities.forEach(fac => {
      const summary = facRiskSummary[fac.id] || { criticalCount: 0, warningCount: 0, surplusCount: 0, items: [] };
      
      const isCritical = summary.criticalCount > 0;
      const isWarning = summary.warningCount > 0 && !isCritical;
      const isSurplus = summary.surplusCount >= 2;

      let minDays = 14;
      if (summary.items.length > 0) {
        minDays = Math.min(...summary.items.map(i => i.days_of_coverage));
      }

      const bubbleColor = isCritical ? 'bg-red-500' : (isWarning ? 'bg-amber-500' : (isSurplus ? 'bg-teal-500' : 'bg-emerald-600'));
      const badgeText = `${minDays.toFixed(1)}d`;

      const pinIcon = L.divIcon({
        className: 'facility-pin-wrapper',
        html: `
          <div class="facility-pin cursor-pointer" onclick="openFacilityDetail('${safeId(fac.id)}')">
            ${isCritical ? '<div class="pin-pulse-ring"></div>' : ''}
            <div class="pin-bubble ${bubbleColor} text-white font-black text-xs shadow-lg flex items-center justify-center space-x-0.5">
              <svg class="w-4 h-4 fill-current" viewBox="0 0 24 24"><path d="M19 10.5h-4.5V6h-5v4.5H5v5h4.5V20h5v-4.5H19v-5z"/></svg>
              <span>${fac.type}</span>
            </div>
            <div class="pin-badge ${isCritical ? 'bg-red-900 text-white font-black animate-bounce' : 'bg-slate-900 text-white font-black'}">
              ${badgeText}
            </div>
          </div>
        `,
        iconSize: [52, 48],
        iconAnchor: [26, 24]
      });

      const marker = L.marker([fac.lat, fac.lng], { icon: pinIcon }).addTo(facilityMarkersLayer);

      let popupContent = `
        <div class="text-xs sm:text-sm p-1.5 font-sans space-y-1.5">
          <div class="flex items-center justify-between border-b border-slate-200 pb-1.5">
            <strong class="text-slate-900 block text-sm sm:text-base font-black">${escapeHtml(fac.name)}</strong>
            <span class="text-xs font-black ${isCritical ? 'bg-red-100 text-red-700' : 'bg-emerald-100 text-emerald-700'} px-2.5 py-0.5 rounded-full">${fac.type}</span>
          </div>
          <div class="text-slate-600 text-xs font-medium py-0.5">${escapeHtml(fac.district)} &bull; ${escapeHtml(fac.doctor)} (demo)</div>
          <div class="mt-1 space-y-1">
      `;

      summary.items.slice(0, 4).forEach(item => {
        const badgeColor = item.status === 'CRITICAL' ? 'text-red-600 font-black' : item.status === 'WARNING' ? 'text-amber-600 font-bold' : 'text-emerald-600 font-bold';
        popupContent += `
          <div class="flex justify-between border-b border-slate-100 pb-1 text-xs">
            <span class="font-medium text-slate-700">${escapeHtml(item.medicine_name.split('(')[0])}</span>
            <span class="${badgeColor}">${item.days_of_coverage}d cover (${item.current_stock}u)</span>
          </div>
        `;
      });

      popupContent += `
          </div>
          <div class="mt-2.5 pt-2 border-t border-slate-200 grid grid-cols-2 gap-2">
            <button onclick="openFacilityDetail('${safeId(fac.id)}')" class="text-xs sm:text-sm bg-slate-900 hover:bg-slate-800 text-white px-3 py-1.5 rounded-full font-bold shadow-sm transition text-center cursor-pointer">
              Inspect Stock
            </button>
            <button onclick="runTransferFor('${safeId(fac.id)}')" class="text-xs sm:text-sm bg-clay-terracotta hover:bg-clay-terracottaDark text-white px-3 py-1.5 rounded-full font-black shadow-sm transition text-center cursor-pointer">
              Find stock
            </button>
          </div>
        </div>
      `;

      marker.bindPopup(popupContent);
      facilityMarkers[fac.id] = marker;
    });

    if (activeSearchQuery) {
      applyMapFilter(activeSearchQuery);
    }
  } catch (err) {
    console.error("fetchRisks error:", err);
  }
}

function renderWatchlist(searchQuery = '') {
  const watchlistContainer = document.getElementById('criticalWatchlist');
  if (!watchlistContainer) return;
  watchlistContainer.innerHTML = '';

  const q = (searchQuery || '').toLowerCase().trim();
  let itemsToDisplay = allRisks;

  if (q) {
    itemsToDisplay = allRisks.filter(r => 
      r.facility_name.toLowerCase().includes(q) ||
      r.medicine_name.toLowerCase().includes(q) ||
      r.status.toLowerCase().includes(q)
    );
  } else {
    const criticalItems = allRisks.filter(r => r.status === 'CRITICAL');
    itemsToDisplay = criticalItems.length > 0 ? criticalItems : allRisks;
  }

  if (itemsToDisplay.length === 0) {
    watchlistContainer.innerHTML = `
      <div class="text-center py-6 text-clay-muted text-sm bg-white rounded-2xl border border-clay-salmon/20 font-medium">
        No facility stock risks matching "<strong>${escapeHtml(searchQuery)}</strong>"
      </div>
    `;
    return;
  }

  itemsToDisplay.slice(0, 6).forEach(item => {
    const row = document.createElement('div');
    row.className = 'flex items-center justify-between bg-white p-3.5 rounded-2xl border border-clay-salmon/20 shadow-sm transition hover:shadow-md';
    const isCritical = item.status === 'CRITICAL';
    const facType = item.facility_name.startsWith('CHC') ? 'CHC' : 'PHC';
    row.innerHTML = `
      <div class="flex items-center space-x-3 min-w-0">
        <div class="w-11 h-11 rounded-xl ${isCritical ? 'bg-red-100 text-red-600' : 'bg-amber-100 text-amber-700'} flex items-center justify-center font-black text-sm flex-shrink-0">
          ${facType}
        </div>
        <div class="min-w-0">
          <h4 class="text-sm font-black text-clay-dark truncate">${escapeHtml(item.facility_name)}</h4>
          <p class="text-xs ${isCritical ? 'text-red-500 font-bold' : 'text-amber-600 font-bold'}">${escapeHtml(item.medicine_name.split('(')[0])} &bull; ${item.days_of_coverage}d Cover</p>
        </div>
      </div>
      <div class="text-right flex items-center space-x-2 flex-shrink-0 pl-2">
        <span class="text-sm font-black text-clay-dark whitespace-nowrap">${item.current_stock} Units</span>
        <button onclick="${isCritical ? 'runTransferFor' : 'openFacilityDetail'}('${safeId(item.facility_id)}')" class="text-xs ${isCritical ? 'bg-clay-terracotta hover:bg-clay-terracottaDark text-white' : 'bg-clay-terracotta/10 text-clay-terracotta hover:bg-clay-terracotta hover:text-white'} px-3.5 py-1.5 rounded-full font-bold shadow-sm transition cursor-pointer whitespace-nowrap" title="${isCritical ? 'Look for a clinic within 35 km that can spare stock' : 'See this clinic\'s stock'}">
          ${isCritical ? 'Find stock' : 'View'}
        </button>
      </div>
    `;
    watchlistContainer.appendChild(row);
  });
}

async function fetchRecommendations() {
  try {
    const res = await fetch(`/api/recommendations?region=${encodeURIComponent(currentRegion)}`);
    if (!res.ok) throw new Error(`recommendations HTTP ${res.status}`);
    activeRecs = await res.json();

    const statActiveTransfers = document.getElementById('statActiveTransfers');
    if (statActiveTransfers) statActiveTransfers.textContent = `${activeRecs.filter(r => r.status === 'PENDING_APPROVAL').length} Pending`;

    let totalExpiryPrevented = 0;
    let totalDist = 0;

    activeRecs.forEach(r => {
      if (r.expiry_waste_prevented && r.status === 'APPROVED') totalExpiryPrevented += r.units_to_transfer;
      totalDist += r.distance_km;
    });

    const statExpirySaved = document.getElementById('statExpirySaved');
    if (statExpirySaved) statExpirySaved.textContent = `${totalExpiryPrevented} Units`;
    const avgDist = activeRecs.length > 0 ? (totalDist / activeRecs.length).toFixed(1) : '0';
    const statAvgDist = document.getElementById('statAvgDist');
    if (statAvgDist) statAvgDist.textContent = `${avgDist} km`;

    // Draw lines on map for active recommendations
    transferLines.forEach(l => map.removeLayer(l));
    transferLines = [];

    activeRecs.forEach(rec => {
      const donorFac = facilities.find(f => f.id === rec.donor_facility_id);
      const recFac = facilities.find(f => f.id === rec.recipient_facility_id);

      if (donorFac && recFac && rec.status === 'PENDING_APPROVAL') {
        const line = L.polyline([[donorFac.lat, donorFac.lng], [recFac.lat, recFac.lng]], {
          color: '#10b981',
          weight: 2.5,
          dashArray: '6, 8',
          opacity: 0.85
        }).addTo(map);

        line.bindTooltip(`${rec.units_to_transfer} units ${rec.medicine_name.split('(')[0]} &bull; ${rec.distance_km} km`, {
          permanent: false,
          direction: 'center'
        });
        transferLines.push(line);
      }
    });

    // Update Live Moving Courier Fleet
    updateCourierFleet();

    renderRecommendations(activeSearchQuery);
  } catch (err) {
    console.error("fetchRecommendations error:", err);
  }
}

function courierPopupHtml(c) {
  return `
    <div class="p-1.5 font-sans text-xs sm:text-sm space-y-1.5">
      <div class="flex items-center justify-between pb-1.5 border-b border-slate-200">
        <span class="font-black text-slate-900 text-sm">🚑 ${escapeHtml(c.vehicleId)}</span>
        <span class="bg-emerald-100 text-emerald-800 text-xs font-black px-2.5 py-0.5 rounded-full">DISPATCHED</span>
      </div>
      <div class="text-slate-600 text-xs space-y-1 font-medium">
        <div>Challan: <strong class="text-slate-900 font-mono">${escapeHtml(c.challanId)}</strong></div>
        <div>Donor: <strong class="text-slate-900">${escapeHtml(c.donor.name)}</strong></div>
        <div>Destination: <strong class="text-[#DE6B48]">${escapeHtml(c.recip.name)}</strong></div>
        <div>Cargo: <strong class="text-slate-900">${escapeHtml(c.units)} Units</strong> (${escapeHtml(c.medicine)})</div>
        <div class="text-slate-500 text-[11px] pt-0.5">No GPS feed: van position on the route is illustrative.</div>
      </div>
    </div>
  `;
}

// Vans are drawn only for consignments that were really dispatched; pending recommendations are the dashed lines
async function updateCourierFleet() {
  if (!courierMarkersLayer) return;
  let dispatched = [];
  try {
    const res = await fetch(`/api/consignments?region=${encodeURIComponent(currentRegion)}`);
    if (res.ok) {
      regionConsignments = await res.json();
      dispatched = regionConsignments.filter(c => c.status === 'DISPATCHED');
    }
  } catch (err) {
    console.error("updateCourierFleet error:", err);
  }
  courierMarkersLayer.clearLayers();
  activeCouriers = [];

  dispatched.forEach((c, idx) => {
    const donor = facilities.find(f => f.id === c.donor_facility_id);
    const recip = facilities.find(f => f.id === c.recipient_facility_id);
    if (!donor || !recip) return;

    const progress = (0.22 + idx * 0.32) % 0.9;
    const courier = {
      id: c.id,
      challanId: c.challan_id,
      vehicleId: c.vehicle_number || 'Vehicle n/a',
      donor,
      recip,
      units: c.units_dispatched,
      medicine: (c.medicine_name || '').split('(')[0],
      progress,
      marker: null
    };

    const vanIcon = L.divIcon({
      className: 'courier-van-marker',
      html: `
        <div class="flex items-center space-x-1.5 bg-slate-950 text-white font-black text-xs px-3 py-1 rounded-full shadow-xl border border-emerald-400 cursor-pointer hover:scale-105 transition">
          <span class="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-ping"></span>
          <span>🚑 ${escapeHtml(courier.vehicleId)}</span>
        </div>
      `,
      iconSize: [135, 28],
      iconAnchor: [67, 14]
    });

    courier.marker = L.marker([donor.lat + (recip.lat - donor.lat) * progress, donor.lng + (recip.lng - donor.lng) * progress], { icon: vanIcon }).addTo(courierMarkersLayer);
    courier.marker.bindPopup(courierPopupHtml(courier));
    activeCouriers.push(courier);
  });

  const hudCouriers = document.getElementById('hudCouriers');
  if (hudCouriers) {
    const pending = activeRecs.filter(r => r.status === 'PENDING_APPROVAL').length;
    hudCouriers.textContent = `${activeCouriers.length} dispatched · ${pending} pending`;
  }
}

function startCourierAnimationLoop() {
  if (courierTransitInterval) clearInterval(courierTransitInterval);
  courierTransitInterval = setInterval(() => {
    simulateCourierTransitStep(false);
  }, 2200);
}

function simulateCourierTransitStep(userTriggered = true) {
  if (!userTriggered && activeCouriers.length === 0) return;

  activeCouriers.forEach(c => {
    c.progress += 0.04;
    if (c.progress >= 0.96) {
      c.progress = 0.05;
    }

    const curLat = c.donor.lat + (c.recip.lat - c.donor.lat) * c.progress;
    const curLng = c.donor.lng + (c.recip.lng - c.donor.lng) * c.progress;

    if (c.marker) {
      c.marker.setLatLng([curLat, curLng]);
      c.marker.setPopupContent(courierPopupHtml(c));
    }
  });

  if (userTriggered) {
    const toast = document.createElement('div');
    toast.className = 'fixed bottom-6 right-6 bg-slate-950 text-white text-xs px-4 py-2.5 rounded-2xl shadow-2xl border border-emerald-400 z-50 transition transform flex items-center space-x-2 animate-bounce';
    toast.innerHTML = activeCouriers.length ? '<span class="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-ping"></span><span>Simulated step: dispatched vans moved along their routes (no GPS feed)</span>' : '<span>No dispatched consignments in transit right now</span>';
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2600);
  }
}

function setMapLayerFilter(layer) {
  activeMapFilter = layer;

  const btnAll = document.getElementById('mapLayerAll');
  const btnFacs = document.getElementById('mapLayerFacs');
  const btnCouriers = document.getElementById('mapLayerCouriers');
  const btnPlume = document.getElementById('mapLayerPlume');
  const btnSensors = document.getElementById('mapLayerSensors');

  const activeCls = 'text-[11px] bg-clay-terracotta text-white font-extrabold px-3 py-1 rounded-full shadow-sm transition';
  const inactiveCls = 'text-[11px] bg-white text-clay-dark hover:bg-clay-bg font-semibold px-2.5 py-1 rounded-full border border-clay-salmon/30 transition';

  if (btnAll) btnAll.className = (layer === 'all' ? activeCls : inactiveCls);
  if (btnFacs) btnFacs.className = (layer === 'facilities' ? activeCls : inactiveCls);
  if (btnCouriers) btnCouriers.className = (layer === 'couriers' ? activeCls : inactiveCls);
  if (btnPlume) btnPlume.className = (layer === 'plume' ? activeCls : inactiveCls);
  if (btnSensors) btnSensors.className = (layer === 'sensors' ? activeCls : inactiveCls);

  if (layer === 'all') {
    if (!map.hasLayer(facilityMarkersLayer)) map.addLayer(facilityMarkersLayer);
    if (!map.hasLayer(courierMarkersLayer)) map.addLayer(courierMarkersLayer);
    if (atmosphericPlumeLayer && !map.hasLayer(atmosphericPlumeLayer)) map.addLayer(atmosphericPlumeLayer);
    if (!map.hasLayer(sensorMarkersLayer)) map.addLayer(sensorMarkersLayer);
    transferLines.forEach(l => { if (!map.hasLayer(l)) map.addLayer(l); });
  } else if (layer === 'facilities') {
    if (!map.hasLayer(facilityMarkersLayer)) map.addLayer(facilityMarkersLayer);
    if (map.hasLayer(courierMarkersLayer)) map.removeLayer(courierMarkersLayer);
    if (atmosphericPlumeLayer && map.hasLayer(atmosphericPlumeLayer)) map.removeLayer(atmosphericPlumeLayer);
    if (map.hasLayer(sensorMarkersLayer)) map.removeLayer(sensorMarkersLayer);
    transferLines.forEach(l => { if (map.hasLayer(l)) map.removeLayer(l); });
  } else if (layer === 'couriers') {
    if (map.hasLayer(facilityMarkersLayer)) map.removeLayer(facilityMarkersLayer);
    if (!map.hasLayer(courierMarkersLayer)) map.addLayer(courierMarkersLayer);
    if (atmosphericPlumeLayer && map.hasLayer(atmosphericPlumeLayer)) map.removeLayer(atmosphericPlumeLayer);
    if (map.hasLayer(sensorMarkersLayer)) map.removeLayer(sensorMarkersLayer);
    transferLines.forEach(l => { if (!map.hasLayer(l)) map.addLayer(l); });
  } else if (layer === 'plume') {
    if (map.hasLayer(facilityMarkersLayer)) map.removeLayer(facilityMarkersLayer);
    if (map.hasLayer(courierMarkersLayer)) map.removeLayer(courierMarkersLayer);
    if (atmosphericPlumeLayer && !map.hasLayer(atmosphericPlumeLayer)) map.addLayer(atmosphericPlumeLayer);
    if (map.hasLayer(sensorMarkersLayer)) map.removeLayer(sensorMarkersLayer);
    transferLines.forEach(l => { if (map.hasLayer(l)) map.removeLayer(l); });
  } else if (layer === 'sensors') {
    if (map.hasLayer(facilityMarkersLayer)) map.removeLayer(facilityMarkersLayer);
    if (map.hasLayer(courierMarkersLayer)) map.removeLayer(courierMarkersLayer);
    if (atmosphericPlumeLayer && map.hasLayer(atmosphericPlumeLayer)) map.removeLayer(atmosphericPlumeLayer);
    if (!map.hasLayer(sensorMarkersLayer)) map.addLayer(sensorMarkersLayer);
    transferLines.forEach(l => { if (map.hasLayer(l)) map.removeLayer(l); });
  }
}

let showAllRecs = false;  // the approval list shows 3 cards until the user expands it
const RECS_PREVIEW = 3;

function renderRecommendations(searchQuery = '') {
  const container = document.getElementById('recommendationsList');
  if (!container) return;
  container.innerHTML = '';

  const q = (searchQuery || '').toLowerCase().trim();
  let items = activeRecs;

  if (q) {
    items = activeRecs.filter(r =>
      r.donor_facility_name.toLowerCase().includes(q) ||
      r.recipient_facility_name.toLowerCase().includes(q) ||
      r.medicine_name.toLowerCase().includes(q) ||
      r.id.toLowerCase().includes(q)
    );
  }

  if (items.length === 0) {
    container.innerHTML = `<div class="col-span-full text-center py-6 text-clay-muted text-xs">${q ? `No transfers matching "${escapeHtml(searchQuery)}"` : 'No transfers needed: every clinic has enough stock.'}</div>`;
    return;
  }

  const hiddenCount = (!q && !showAllRecs) ? Math.max(0, items.length - RECS_PREVIEW) : 0;
  if (hiddenCount) items = items.slice(0, RECS_PREVIEW);

  items.forEach(rec => {
    const card = document.createElement('div');
    card.className = `bg-white border ${rec.status === 'APPROVED' ? 'border-emerald-300 bg-emerald-50/40' : 'border-clay-salmon/30'} rounded-2xl p-4 sm:p-5 flex flex-col justify-between space-y-3 shadow-sm transition hover:shadow-md`;
    card.dataset.recId = rec.id;

    const statusBadge = rec.status === 'APPROVED'
      ? `<span class="bg-emerald-100 text-emerald-800 border border-emerald-300 text-xs px-3 py-1 rounded-full font-black">APPROVED &bull; STOCK RESERVED</span>`
      : `<span class="bg-[#FFF1EB] text-clay-terracotta border border-clay-salmon/40 text-xs px-3 py-1 rounded-full font-black">AWAITING CMO SIGN-OFF</span>`;

    const expiryBadge = rec.expiry_waste_prevented
      ? `<span class="bg-[#EBF3EF] text-emerald-800 border border-emerald-300 text-xs px-2.5 py-1 rounded-full font-bold">Prevents Expiry Waste (${rec.batch_expiry_days}d left)</span>`
      : '';

    card.innerHTML = `
      <div>
        <div class="flex items-center justify-between">
          <span class="text-xs font-mono text-clay-muted font-bold">${escapeHtml(rec.id)}</span>
          ${statusBadge}
        </div>

        <div class="mt-2.5 flex items-center justify-between bg-clay-inner p-3 rounded-xl border border-clay-salmon/20">
          <div>
            <span class="text-[10px] text-clay-muted uppercase font-extrabold tracking-wider block">From (has spare)</span>
            <strong class="text-sm font-black text-clay-dark">${escapeHtml(rec.donor_facility_name)}</strong>
          </div>
          <div class="text-clay-muted text-xs px-2 flex flex-col items-center">
            <span>&rarr;</span>
            <span class="text-xs font-black text-clay-terracotta">${rec.distance_km} km</span>
          </div>
          <div class="text-right">
            <span class="text-[10px] text-clay-muted uppercase font-extrabold tracking-wider block">To (running low)</span>
            <strong class="text-sm font-black text-red-600">${escapeHtml(rec.recipient_facility_name)}</strong>
          </div>
        </div>

        <div class="mt-2.5">
          <div class="flex justify-between items-center text-sm">
            <span class="font-black text-clay-dark sm:text-base">${escapeHtml(rec.medicine_name.split('(')[0])}</span>
            <span class="font-black text-clay-terracotta text-base sm:text-lg">${rec.units_to_transfer} Units</span>
          </div>
          <div class="text-xs sm:text-sm text-clay-muted mt-0.5 font-medium">
            Days of medicine left: ${rec.recipient_initial_coverage_days} &rarr; <strong class="text-emerald-700 font-black">${rec.recipient_new_coverage_days}</strong>
          </div>
        </div>

        <div class="mt-2">
          ${expiryBadge}
        </div>
      </div>

      <div class="pt-2.5 border-t border-clay-salmon/20">
        ${rec.status === 'APPROVED' 
          ? `<button onclick="showChallanModal('${safeId(rec.id)}')" class="w-full bg-clay-inner hover:bg-clay-bg text-clay-dark text-xs sm:text-sm py-2.5 rounded-full font-bold border border-clay-salmon/30 transition cursor-pointer">View dispatch note (challan)</button>`
          : `<button onclick="approveTransfer('${safeId(rec.id)}')" class="w-full bg-clay-terracotta hover:bg-clay-terracottaDark text-white text-xs sm:text-sm py-2.5 rounded-full font-black shadow-clay-btn transition cursor-pointer">Approve &amp; Reserve Stock</button>`
        }
      </div>
    `;

    container.appendChild(card);
  });

  if (hiddenCount) {
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'w-full py-2.5 rounded-full text-xs sm:text-sm font-black text-clay-terracotta bg-white border border-clay-salmon/30 hover:bg-clay-bg transition cursor-pointer';
    more.textContent = `Show all ${hiddenCount + RECS_PREVIEW} transfers`;
    more.onclick = () => { showAllRecs = true; renderRecommendations(searchQuery); };
    container.appendChild(more);
  }
}

let approvingRecId = null;

async function approveTransfer(recId) {
  if (approvingRecId === recId) return;  // ignore a double click while the first request is in flight
  approvingRecId = recId;
  try {
    const res = await fetch('/api/approve-transfer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        recommendation_id: recId,
        officer_name: "Demo CMO (District Health Society)",
        comments: "Approved for immediate district ambulance/van courier transfer under Climate Surge Protocol."
      })
    });

    if (res.ok) {
      const data = await res.json();
      await loadInitialData();
      showChallanModal(recId, data);
    } else {
      alert("Transfer approval failed: " + await apiErrorMessage(res, "Server error"));
    }
  } catch (err) {
    console.error(err);
    alert("Network error while approving transfer");
  } finally {
    approvingRecId = null;
  }
}

function showChallanModal(recId, approvalData = null) {
  const rec = activeRecs ? activeRecs.find(r => r.id === recId) : null;
  let consignment = (approvalData && approvalData.consignment) || null;
  if (!consignment) {
    const desk = activeClinicDeskData || {};
    const pool = [...regionConsignments, ...(desk.inbound_consignments || []), ...(desk.outbound_consignments || [])];
    consignment = pool.find(c => c.recommendation_id === recId || c.id === recId || c.challan_id === recId) || null;
  }
  if (!rec && !consignment) return;

  const fmtDate = (iso) => new Date(iso || Date.now()).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
  const regionId = consignment ? regionForFacility(consignment.donor_facility_id) : currentRegion;
  const isOdisha = regionId === 'bhubaneswar';
  document.getElementById('challanStateBadge').textContent = isOdisha ? 'OD' : 'UP';
  document.getElementById('challanStateTitle').innerHTML = `${isOdisha ? 'Khordha–Cuttack (Odisha)' : 'Lucknow–Unnao (Uttar Pradesh)'} &bull; District Health Society`;

  const hashRow = document.getElementById('modalHashRow');
  if (consignment) {
    document.getElementById('modalChallanId').textContent = consignment.challan_id;
    document.getElementById('modalDate').textContent = fmtDate(consignment.approved_at);
    document.getElementById('modalDonor').textContent = consignment.donor_facility_name;
    document.getElementById('modalRecipient').textContent = consignment.recipient_facility_name;
    document.getElementById('modalMed').textContent = consignment.medicine_name;
    const units = consignment.units_dispatched > 0 ? consignment.units_dispatched : consignment.units_requested;
    document.getElementById('modalUnits').textContent = `${units} Units${consignment.units_dispatched > 0 ? '' : ' (reserved, not yet dispatched)'}`;
    document.getElementById('modalBatch').textContent = consignment.batch_number;
    document.getElementById('modalDist').textContent = consignment.distance_km != null ? `${consignment.distance_km} km` : 'n/a';
    document.getElementById('modalRationale').textContent = consignment.condition_notes || consignment.discrepancy_reason || (rec && rec.rationale_en) || 'Inter-facility transfer authorized by the CMO.';
    const hash = consignment.cryptographic_hash || (approvalData && approvalData.cryptographic_hash);
    document.getElementById('modalHash').textContent = hash || '';
    if (hashRow) hashRow.classList.toggle('hidden', !hash);
  } else {
    document.getElementById('modalChallanId').textContent = 'Not issued yet (awaiting approval)';
    document.getElementById('modalDate').textContent = fmtDate();
    document.getElementById('modalDonor').textContent = rec.donor_facility_name;
    document.getElementById('modalRecipient').textContent = rec.recipient_facility_name;
    document.getElementById('modalMed').textContent = rec.medicine_name;
    document.getElementById('modalUnits').textContent = `${rec.units_to_transfer} Units`;
    document.getElementById('modalBatch').textContent = rec.batch_number || 'n/a';
    document.getElementById('modalDist').textContent = `${rec.distance_km} km`;
    document.getElementById('modalRationale').textContent = rec.rationale_en;
    document.getElementById('modalHash').textContent = '';
    if (hashRow) hashRow.classList.add('hidden');
  }

  document.getElementById('challanModal').classList.remove('hidden');
}

function regionForFacility(facId) {
  return /BBS|CTC|OD/.test(String(facId || '')) ? 'bhubaneswar' : 'lucknow';
}

function closeModal() {
  document.getElementById('challanModal').classList.add('hidden');
}

async function fetchAuditLog() {
  try {
    const res = await fetch('/api/audit-log');
    if (!res.ok) throw new Error(`audit log HTTP ${res.status}`);
    allLogs = await res.json();

    const tbody = document.getElementById('auditTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';

    allLogs.forEach(e => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-clay-inner/80 transition';

      let detailsPreview = JSON.stringify(e.details) || '';
      if (detailsPreview.length > 60) detailsPreview = detailsPreview.substring(0, 60) + '...';

      tr.innerHTML = `
        <td class="py-3 px-3.5 text-clay-muted font-mono font-bold text-xs sm:text-sm">#${escapeHtml(e.index)}</td>
        <td class="py-3 px-3.5 text-clay-dark font-semibold text-xs sm:text-sm">${escapeHtml(String(e.timestamp || '').substring(11, 19))}</td>
        <td class="py-3 px-3.5 font-bold text-clay-terracotta text-xs sm:text-sm">${escapeHtml(e.event_type)}</td>
        <td class="py-3 px-3.5 text-clay-dark font-medium text-xs sm:text-sm">${escapeHtml(e.approved_by)}</td>
        <td class="py-3 px-3.5 text-clay-muted font-mono text-xs sm:text-sm" title="${escapeHtml(JSON.stringify(e.details))}">${escapeHtml(detailsPreview)}</td>
        <td class="py-3 px-3.5 text-slate-500 font-mono text-xs font-semibold">${escapeHtml(String(e.current_hash || '').substring(0, 16))}...</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("fetchAuditLog error:", err);
  }
}

async function verifyAuditLedgerLive() {
  const statusEl = document.getElementById('ledgerIntegrityStatus');
  if (statusEl) {
    statusEl.innerHTML = `<span class="text-amber-600 font-bold animate-pulse">Recalculating SHA-256 hashes across entire ledger chain...</span>`;
  }
  try {
    const res = await fetch('/api/audit-log/verify');
    if (!res.ok) throw new Error(await apiErrorMessage(res, 'Verification request failed'));
    const result = await res.json();
    if (result.valid) {
      if (statusEl) {
        statusEl.innerHTML = `
          <span class="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
          <span class="text-emerald-700 font-extrabold">Chain Verified (Intact) &bull; ${escapeHtml(result.total_blocks)} Blocks &bull; Head: <code class="font-mono text-emerald-900 bg-emerald-100 px-1 py-0.5 rounded">${result.head_hash ? escapeHtml(result.head_hash.substring(0, 10)) + '...' : 'Genesis'}</code></span>
        `;
      }
    } else {
      if (statusEl) {
        statusEl.innerHTML = `<span class="text-red-600 font-bold">⚠️ Tampering Detected: ${escapeHtml(result.error)}</span>`;
      }
    }
    if (window.lucide) lucide.createIcons();
  } catch (err) {
    console.error("verifyAuditLedgerLive error:", err);
    if (statusEl) statusEl.innerHTML = `<span class="text-red-600 font-bold">Could not verify the ledger: ${escapeHtml(err.message || 'network error')}</span>`;
  }
}

function showWaveformBriefly(ms = 2400) {
  const wave = document.getElementById('voiceWaveform');
  if (wave) {
    wave.classList.remove('hidden');
    wave.classList.add('flex');
    setTimeout(() => {
      wave.classList.add('hidden');
      wave.classList.remove('flex');
    }, ms);
  }
}

// Sample field reports per region, so the facility always exists in the region's dropdown
const VOICE_SAMPLES = {
  lucknow: [
    { label: '🔴 "Kakori: 15 Salbutamol respules..."', facility: 'PHC-LKO-01',
      text: "This is PHC Kakori reporting. We only have 15 respules of Salbutamol left and treated 40 acute respiratory patients yesterday." },
    { label: '🟡 "Sarojini Nagar: 120 ORS sachets..."', facility: 'CHC-LKO-06',
      text: "Sarojini Nagar CHC reporting: 120 packets of ORS oral rehydration salt remain, with 35 new acute dehydration cases." },
    { label: '🟢 Hindi: "इटौंजा: पैरासिटामोल 12..."', facility: 'PHC-LKO-08',
      text: "PHC इटौंजा से रिपोर्ट: पैरासिटामोल के सिर्फ 12 बोतल बचे हैं, कल 30 बच्चों को बुखार की दवा दी।" }
  ],
  bhubaneswar: [
    { label: '🔴 "Jatni: 60 ORS packets..."', facility: 'CHC-BBS-03',
      text: "This is CHC Jatni reporting. Only 60 ORS packets are left and we treated 25 dehydration cases yesterday." },
    { label: '🟡 Hinglish: "Unit-6: Salbutamol 20..."', facility: 'CHC-BBS-02',
      text: "Capital Hospital Unit-6 se report: Salbutamol respules sirf 20 bache hain, kal 35 asthma patients aaye the." },
    { label: '🟢 Odia: "Mendhasal ୧୮ Salbutamol..."', facility: 'PHC-BBS-01',
      text: "ଏହା PHC Mendhasal ରିପୋର୍ଟ। ଆମ ପାଖରେ ମାତ୍ର ୧୮ ଟି ସାଲବୁଟାମଲ୍ (Salbutamol) ବାକି ଅଛି ଏବଂ ଗତକାଲି ୪୨ ଜଣ ଶ୍ୱାସରୋଗୀଙ୍କୁ ଚିକିତ୍ସା କରିଛୁ।" }
  ]
};

function renderVoiceSamples() {
  (VOICE_SAMPLES[currentRegion] || []).forEach((sample, i) => {
    const btn = document.getElementById(`voiceSample${i + 1}`);
    if (btn) btn.textContent = sample.label;
  });
}

function loadSampleVoice(idx) {
  const sample = (VOICE_SAMPLES[currentRegion] || [])[idx - 1];
  if (!sample) return;
  showWaveformBriefly(2500);
  const txt = document.getElementById('voiceTranscript');
  const facSelect = document.getElementById('voiceFacilitySelect');
  if (txt) txt.value = sample.text;
  if (facSelect) facSelect.value = sample.facility;
}

async function submitVoiceIntake() {
  const text = document.getElementById('voiceTranscript').value.trim();
  if (!text) {
    alert("Please enter or record a voice message in English, Hindi, or Odia.");
    return;
  }

  const wave = document.getElementById('voiceWaveform');
  if (wave) {
    wave.classList.remove('hidden');
    wave.classList.add('flex');
  }

  const facSelect = document.getElementById('voiceFacilitySelect');
  const facId = facSelect ? (facSelect.value || null) : null;
  const btn = document.getElementById('btnSubmitVoice');
  btn.disabled = true;
  btn.innerHTML = `<span>Parsing report...</span>`;

  try {
    const res = await fetch('/api/voice-intake', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        transcript_text: text,
        facility_id: facId,
        language: "en"
      })
    });

    btn.disabled = false;
    btn.innerHTML = `<span>Read report</span>`;
    if (!res.ok) {
      alert("Could not process the report: " + await apiErrorMessage(res, "Server error"));
      return;
    }
    const result = await res.json();

    const box = document.getElementById('voiceResultBox');
    if (box) box.classList.remove('hidden');

    const badge = document.getElementById('voiceResultBadge');
    if (badge) {
      if (result.is_draft) {
        badge.textContent = "DRAFT CREATED (CONFIRMATION REQUIRED)";
        badge.className = "text-[10px] font-bold text-amber-800 bg-amber-100 px-2 py-0.5 rounded-full";
      } else if (result.quality_checks_passed) {
        badge.textContent = "QA PASSED & LOGGED";
        badge.className = "text-[10px] font-bold text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded-full";
      } else {
        badge.textContent = "ANOMALY FLAGGED";
        badge.className = "text-[10px] font-bold text-red-600 bg-red-100 px-2 py-0.5 rounded-full";
      }
    }

    const conf = document.getElementById('voiceConfidence');
    if (conf) {
      const parser = { gemini: 'Gemini 3.8 Flash', claude: 'Claude Haiku 5.5 (fallback)', heuristic: 'Offline keyword parser' }[result.parsed_by] || '';
      conf.textContent = `Confidence: ${Math.round((Number(result.confidence_score) || 0) * 100)}%${parser ? ` · ${parser}` : ''}`;
    }
    const facNameEl = document.getElementById('voiceFacName');
    if (facNameEl) facNameEl.textContent = result.facility_name;
    const medNameEl = document.getElementById('voiceMedName');
    if (medNameEl) medNameEl.textContent = result.medicine_name;
    const stockEl = document.getElementById('voiceStockQty');
    if (stockEl) stockEl.textContent = result.reported_stock != null ? `${result.reported_stock} units` : 'Not stated';
    const dispEl = document.getElementById('voiceDispQty');
    if (dispEl) dispEl.textContent = result.dispensed_yesterday != null ? `${result.dispensed_yesterday} units` : 'N/A';
    const edlEl = document.getElementById('voiceEdlCode');
    if (edlEl) {
      const verified = !result.anomaly_flag && Number(result.confidence_score) >= 0.75;
      edlEl.textContent = `${result.medicine_code || result.medicine_id} (${verified ? 'Verified Grounding' : 'Needs review'})`;
    }
    const formEl = document.getElementById('voiceFormStrength');
    if (formEl) formEl.textContent = `${result.dosage_form || 'Standard Form'} • ${result.strength || ''}`;
    const actionEl = document.getElementById('voiceActionText');
    if (actionEl) {
      const actionText = {
        DRAFT_CREATED_AWAITING_CONFIRMATION: 'Draft stock report created. A pharmacist must confirm the count on the Clinic Desk before the register changes.'
      };
      actionEl.textContent = result.anomaly_flag || actionText[result.action_taken] || result.action_taken || '';
      if (result.is_draft) {
        actionEl.innerHTML += `
          <div class="mt-2 pt-2 border-t border-emerald-200 flex items-center justify-between">
            <span class="text-[11px] text-amber-900 font-bold">⚠️ Draft only. Master ledger unchanged.</span>
            <button onclick="openClinicDeskForVoiceDraft('${safeId(result.facility_id)}', '${safeId(result.medicine_id)}', ${Number(result.reported_stock) || 0})" class="px-3 py-1 bg-clay-terracotta hover:bg-clay-terracottaDark text-white font-black text-xs rounded-lg shadow-sm transition">
              Review &amp; Commit in Clinic Desk &rarr;
            </button>
          </div>
        `;
      }
    }

    // Refresh dashboard
    await loadInitialData();
  } catch (err) {
    console.error(err);
    btn.disabled = false;
    btn.innerHTML = `<span>Read report</span>`;
    alert("Network error while processing the report");
  } finally {
    if (wave) {
      wave.classList.add('hidden');
      wave.classList.remove('flex');
    }
  }
}

const VOICE_MAX_SECONDS = 30;
// idle -> starting (waiting for mic permission) -> recording -> transcribing -> idle; 'browser' while the fallback recogniser listens
let voiceState = 'idle';
let voiceRecorder = null;

function setVoiceUi(state, label) {
  voiceState = state;
  const micBtn = document.getElementById('btnMic');
  const wave = document.getElementById('voiceWaveform');
  const waveLabel = document.getElementById('voiceWaveLabel');
  const busy = state !== 'idle';
  if (micBtn) {
    const live = state === 'recording' || state === 'browser';
    micBtn.classList.toggle('bg-red-600', live);
    micBtn.classList.toggle('text-white', live);
    micBtn.classList.toggle('opacity-50', state === 'starting' || state === 'transcribing');
  }
  if (wave) {
    wave.classList.toggle('hidden', !busy);
    wave.classList.toggle('flex', busy);
  }
  if (waveLabel) waveLabel.textContent = label || 'Audio Input Active';
}

// Gemini rejects the Opus/WebM audio MediaRecorder produces, so re-encode as 16 kHz mono 16-bit WAV
async function blobToWav(blob) {
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  let decoded;
  try {
    decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
  } finally {
    ctx.close();
  }
  const rate = 16000;
  const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * rate), rate);
  const src = offline.createBufferSource();
  src.buffer = decoded;
  src.connect(offline.destination);
  src.start();
  const pcm = (await offline.startRendering()).getChannelData(0);
  const view = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const tag = (o, t) => [...t].forEach((c, i) => view.setUint8(o + i, c.charCodeAt(0)));
  tag(0, 'RIFF'); view.setUint32(4, 36 + pcm.length * 2, true); tag(8, 'WAVE');
  tag(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  tag(36, 'data'); view.setUint32(40, pcm.length * 2, true);
  pcm.forEach((v, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, v)) * 0x7fff, true));
  return new Blob([view], { type: 'audio/wav' });
}

async function transcribeVoiceNote(blob) {
  const txt = document.getElementById('voiceTranscript');
  setVoiceUi('transcribing', 'Transcribing with Gemini...');
  let wav;
  try {
    wav = blob.size ? await blobToWav(blob) : null;
  } catch (err) {
    wav = null;
  }
  // under 1 s of audio: treat as an accidental tap (models invent text for near-empty clips)
  if (!wav || wav.size < 44 + 16000 * 2 * 1.0) {
    setVoiceUi('idle');
    if (txt) txt.placeholder = 'Recording too short. Tap the mic, speak, then tap again to stop.';
    return;
  }
  try {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(wav);
    });
    const res = await fetch('/api/voice-intake/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ audio_base64: dataUrl, mime_type: 'audio/wav' })
    });
    const data = await res.json().catch(() => ({}));
    setVoiceUi('idle');
    if (res.status === 503) {
      // Gemini unavailable: the browser's own recogniser is the remaining option, so ask for a repeat
      alert('Gemini transcription is unavailable right now. Switching to the browser\'s speech recognition: please speak again.');
      recordWithBrowserSpeech();
      return;
    }
    if (!res.ok) throw new Error(data.detail || `Transcription failed (${res.status})`);
    if (!data.is_speech) {
      if (txt) txt.placeholder = 'No speech detected. Tap the mic and try again.';
      return;
    }
    if (txt) {
      // add to what the worker already typed instead of overwriting it
      const existing = txt.value.trim();
      txt.value = existing ? `${existing}\n${data.transcript}` : data.transcript;
    }
  } catch (err) {
    console.error('transcribeVoiceNote error:', err);
    setVoiceUi('idle');
    if (txt) txt.placeholder = 'Transcription failed. Type the report or try again.';
    alert(err.message || 'Transcription failed');
  }
}

async function recordVoiceNote() {
  if (voiceState === 'recording') {
    voiceRecorder.stop();
    return;
  }
  if (voiceState === 'browser') {
    if (voiceRecognition) voiceRecognition.stop();
    return;
  }
  if (voiceState !== 'idle') return;  // waiting for mic permission or a transcription
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder || !window.OfflineAudioContext) {
    recordWithBrowserSpeech();
    return;
  }
  setVoiceUi('starting', 'Waiting for microphone...');
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    setVoiceUi('idle');
    alert('Microphone access was blocked. Allow the microphone or type the report.');
    return;
  }
  const chunks = [];
  let recorder;
  try {
    recorder = new MediaRecorder(stream);
  } catch (err) {
    stream.getTracks().forEach(t => t.stop());
    setVoiceUi('idle');
    recordWithBrowserSpeech();
    return;
  }
  voiceRecorder = recorder;
  const stopTimer = setTimeout(() => recorder.state === 'recording' && recorder.stop(), VOICE_MAX_SECONDS * 1000);
  recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  recorder.onstop = () => {
    clearTimeout(stopTimer);
    stream.getTracks().forEach(t => t.stop());
    voiceRecorder = null;
    transcribeVoiceNote(new Blob(chunks, { type: recorder.mimeType }));
  };
  recorder.start();
  setVoiceUi('recording', `Recording (English, Hindi or Odia): tap the mic again to stop (max ${VOICE_MAX_SECONDS} s)`);
}

let voiceRecognition = null;

// Fallback where audio recording is unsupported or Gemini transcription is unavailable
function recordWithBrowserSpeech() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    alert("Voice recording is not available in this browser. Please type the report or use a sample scenario button.");
    return;
  }
  if (voiceState !== 'idle') return;

  const recognition = new SpeechRecognition();
  recognition.lang = 'en-IN';  // Indian English; browser recognisers take one language per session
  recognition.interimResults = false;
  voiceRecognition = recognition;
  setVoiceUi('browser', 'Listening (browser speech recognition, Indian English): tap the mic to stop');

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    const txt = document.getElementById('voiceTranscript');
    if (txt) {
      const existing = txt.value.trim();
      txt.value = existing ? `${existing}\n${transcript}` : transcript;
    }
  };
  recognition.onerror = (event) => {
    if (event.error === 'not-allowed') alert('Microphone access was blocked. Allow the microphone or type the report.');
  };
  // onend fires after a result, an error or silence, so it is the one place to reset the UI
  recognition.onend = () => {
    voiceRecognition = null;
    setVoiceUi('idle');
  };

  try {
    recognition.start();
  } catch (err) {
    voiceRecognition = null;
    setVoiceUi('idle');
  }
}

// Conditions buttons: the choice is this browser's own (see the fetch wrapper at the top)
async function switchScenario(type) {
  currentScenario = SCENARIO_NAMES.includes(type) ? type : 'live';
  try { localStorage.setItem(SCENARIO_KEY, currentScenario); } catch (e) { /* private mode: keep it for this page only */ }
  highlightScenarioButton(currentScenario);
  await loadInitialData();
}

function fitMapBounds() {
  if (facilities.length > 0) {
    const group = new L.featureGroup(Object.values(facilityMarkers));
    map.fitBounds(group.getBounds().pad(0.15));
  }
}

// Multi-Agent Pipeline Runner: a step tracker, a one-sentence outcome and a plain-language log
const PIPE_STEP_OF = {
  EnvironmentalSentinelAgent: 'air',
  FrontlineIntakeAgent: 'intake',
  DemandIntelligenceAgent: 'demand',
  LogisticsAgent: 'transfer',
  GovernanceAgent: 'cmo'
};
const PIPE_LABEL = { air: 'Weather & air agent', intake: 'Field report agent', demand: 'Demand agent', transfer: 'Transfer agent', cmo: 'Governance' };
const PIPE_ICON = { air: 'wind', intake: 'mic', demand: 'trending-up', transfer: 'route', cmo: 'shield-check' };
const PIPE_ACTION = { TOOL_CALL: 'called the transfer solver', TOOL_RESULT: 'solver result', GROUNDING_MATCH: 'matched the drug list' };

function setPipeStep(key, state, figure) {
  const li = document.querySelector(`#pipeSteps [data-step="${key}"]`);
  if (!li) return;
  const fig = li.querySelector('.pipe-figure');
  if (!li.dataset.defaultFigure) li.dataset.defaultFigure = fig.textContent;
  li.dataset.state = state;
  fig.textContent = figure === undefined ? li.dataset.defaultFigure : figure;
}

function shortMedicineName(name) {
  return String(name || '').split(' (')[0];
}

// Final state and headline figure of each step, worked out from the whole response
function pipelineStepSummary(data, traces) {
  const tel = (data.sentinel && data.sentinel.telemetry) || {};
  const condition = data.sentinel && data.sentinel.condition;
  const grounding = traces.find(t => t.type === 'GROUNDING_MATCH');
  const entity = (grounding && grounding.payload && grounding.payload.grounded_entity) || {};
  const intakeNote = traces.find(t => t.agent === 'FrontlineIntakeAgent' && t.type === 'THINKING');
  const usedReport = Boolean(intakeNote && String(intakeNote.message || '').startsWith('Field report parsed'));
  const df = data.demand_forecast || {};
  const logistics = data.logistics;
  const rec = logistics && logistics.recommendation;
  const cover = df.days_of_coverage;
  const urgent = ['CRITICAL', 'WARNING', 'NO_STOCK_RECORD'].includes(df.risk_status);
  return {
    air: {
      state: ['SEVERE_COMPOUND_INVERSION', 'ELEVATED_SURGE'].includes(condition) ? 'alert' : 'done',
      figure: tel.aqi === undefined ? undefined
        : `${tel.flood_alert ? `Rain ${tel.rain_24h_mm} mm` : tel.cold_wave_alert ? `Min ${tel.min_temp_c}°C` : `AQI ${tel.aqi}`} · ${tel.is_live ? 'live' : 'scenario'}`
    },
    intake: {
      state: usedReport ? 'done' : 'skipped',
      figure: usedReport ? shortMedicineName(entity.standard_name) : 'No report · register used'
    },
    demand: {
      state: urgent ? 'alert' : 'done',
      figure: cover === null || cover === undefined ? 'No stock record' : `${cover} days of cover`
    },
    transfer: rec
      ? { state: 'done', figure: `${Number(rec.units_to_transfer) || 0} units from ${rec.donor_facility_name}` }
      : logistics
        ? { state: 'alert', figure: 'No donor within 35 km' }
        : { state: 'skipped', figure: 'Not needed' },
    cmo: rec
      ? { state: 'waiting', figure: 'Waiting for approval' }
      : logistics
        ? { state: 'alert', figure: 'Escalated to district' }
        : { state: 'skipped', figure: 'Nothing to approve' }
  };
}

function renderPipelineOutcome(data, facId, medicineName) {
  const box = document.getElementById('pipeOutcome');
  const fac = facilities.find(f => f.id === facId);
  const facName = escapeHtml(fac ? fac.name : facId);
  const df = data.demand_forecast || {};
  const logistics = data.logistics;
  const rec = logistics && logistics.recommendation;
  const med = escapeHtml(shortMedicineName((rec && rec.medicine_name) || medicineName || df.medicine_id || 'this medicine'));
  const figure = (value, label) => `
    <div class="bg-white/70 rounded-xl px-4 py-3">
      <div class="text-xl sm:text-2xl font-black text-clay-dark tabular-nums">${value}</div>
      <div class="text-xs sm:text-sm text-clay-muted mt-0.5">${label}</div>
    </div>`;

  if (rec) {
    box.className = 'rounded-2xl p-5 sm:p-6 bg-[#E8F0EC]';
    box.innerHTML = `
      <p class="text-sm font-bold text-[#2F6B52]">Proposal for ${facName} · waiting for CMO sign-off</p>
      <h4 class="text-xl sm:text-2xl font-black text-clay-dark tracking-tight mt-1 leading-snug">Send ${Number(rec.units_to_transfer) || 0} units of ${med} from ${escapeHtml(rec.donor_facility_name)} to ${escapeHtml(rec.recipient_facility_name)}</h4>
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-2 mt-4">
        ${figure(`${Number(rec.distance_km) || 0} km`, 'Distance (limit 35 km)')}
        ${figure(`${Number(rec.recipient_initial_coverage_days)} → ${Number(rec.recipient_new_coverage_days)} d`, `Cover at ${escapeHtml(rec.recipient_facility_name)}`)}
        ${figure(`${Number(rec.donor_remaining_coverage_days)} d`, `Cover kept at ${escapeHtml(rec.donor_facility_name)} (min 14 d)`)}
        ${figure(`${Number(rec.batch_expiry_days)} d`, 'Until the batch expires')}
      </div>
      <button onclick="focusRecommendation('${safeId(rec.id)}')" class="mt-4 bg-clay-terracotta hover:bg-clay-terracottaDark active:scale-[0.98] text-white font-black text-sm px-5 py-2.5 rounded-full transition">Review and approve</button>`;
  } else if (logistics) {
    const sub = logistics.drug_substitution;
    box.className = 'rounded-2xl p-5 sm:p-6 bg-[#FBE4DE]';
    box.innerHTML = `
      <p class="text-sm font-bold text-[#8F2A19]">${facName} · escalated</p>
      <h4 class="text-xl sm:text-2xl font-black text-clay-dark tracking-tight mt-1 leading-snug">No clinic within 35 km can spare ${med} for ${facName}</h4>
      <p class="text-sm text-clay-dark mt-2">The shortfall goes to the district store as a requisition.${sub ? ` A substitute, ${escapeHtml(sub.substitute_name)}, is available if the CMO approves it.` : ''}</p>`;
  } else {
    const cover = df.days_of_coverage;
    box.className = 'rounded-2xl p-5 sm:p-6 bg-clay-inner';
    box.innerHTML = `
      <p class="text-sm font-bold text-clay-muted">${facName} · no action needed</p>
      <h4 class="text-xl sm:text-2xl font-black text-clay-dark tracking-tight mt-1 leading-snug">${facName} has enough ${med}${cover !== null && cover !== undefined ? `: ${Number(cover)} days of cover` : ''}</h4>
      <p class="text-sm text-clay-dark mt-2">No transfer is proposed, so nothing goes to the CMO.</p>`;
  }
}

function focusRecommendation(recId) {
  if (!showAllRecs && !document.querySelector(`#recommendationsList [data-rec-id="${recId}"]`)) {
    showAllRecs = true;
    renderRecommendations(activeSearchQuery);
  }
  const card = document.querySelector(`#recommendationsList [data-rec-id="${recId}"]`) || document.getElementById('recommendationsList');
  if (!card) return;
  card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  card.classList.add('ring-4', 'ring-clay-terracotta/60');
  setTimeout(() => card.classList.remove('ring-4', 'ring-clay-terracotta/60'), 2400);
}

function pipelineLogRow(step) {
  const key = PIPE_STEP_OF[step.agent] || 'cmo';
  const payload = step.payload || {};
  let details = '';
  if (step.type === 'TOOL_CALL') {
    const caller = payload.called_by === 'gemini' ? 'Gemini function call' : payload.called_by === 'claude' ? 'Claude tool call (Gemini unavailable)' : 'Default arguments (no model reachable)';
    details = `${caller}\n${payload.tool || 'calculate_optimal_transfer'}(${JSON.stringify(payload.arguments || {}, null, 2)})`;
  } else if (step.type === 'TOOL_RESULT' && !payload.no_feasible_donor) {
    details = JSON.stringify({
      donor: payload.donor_facility_name, units: payload.units_to_transfer, batch: payload.batch_number,
      batch_expiry_days: payload.batch_expiry_days, distance_km: payload.distance_km,
      donor_min_reserve_units: payload.donor_min_reserve_units, recommendation_id: payload.id
    }, null, 2);
  } else if (step.agent === 'EnvironmentalSentinelAgent' && payload.aqi !== undefined) {
    details = JSON.stringify(payload, null, 2);
  }
  const action = PIPE_ACTION[step.type] ? ` <span class="font-semibold text-clay-muted">${PIPE_ACTION[step.type]}</span>` : '';
  const row = document.createElement('div');
  row.className = 'pipe-log-row';
  row.innerHTML = `
    <span class="pipe-dot"><i data-lucide="${PIPE_ICON[key]}" class="w-4 h-4"></i></span>
    <div class="min-w-0">
      <div class="flex flex-wrap items-baseline justify-between gap-x-3">
        <p class="text-sm"><strong class="text-clay-dark">${PIPE_LABEL[key]}</strong>${action}</p>
        <span class="text-xs text-clay-muted tabular-nums">${escapeHtml(step.timestamp || '')}</span>
      </div>
      <p class="text-sm text-clay-dark leading-relaxed mt-0.5">${escapeHtml(step.message)}</p>
      ${details ? `<details><summary>${step.type === 'TOOL_CALL' ? 'Show the function call' : 'Show the data'}</summary><pre><code>${escapeHtml(details)}</code></pre></details>` : ''}
    </div>`;
  return row;
}

async function runAgentPipeline(targetFacId = null, includeFieldReport = true) {
  const btn = document.getElementById('btnRunAgents');
  const term = document.getElementById('agentTerminalBody');
  const outcome = document.getElementById('pipeOutcome');
  const latencyEl = document.getElementById('agentLatency');
  const snippet = includeFieldReport ? (document.getElementById('voiceTranscript').value.trim() || null) : null;
  const facSelect = document.getElementById('voiceFacilitySelect');

  const facId = targetFacId || (facSelect && facSelect.value ? facSelect.value : (currentClinicFacilityId || (facilities.length > 0 ? facilities[0].id : (currentRegion === 'bhubaneswar' ? 'PHC-BBS-01' : 'PHC-LKO-01'))));
  if (facSelect && facId) facSelect.value = facId;
  const fac = facilities.find(f => f.id === facId);

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>Running...</span>`;
  }
  ['air', 'intake', 'demand', 'transfer', 'cmo'].forEach(k => setPipeStep(k, 'idle'));
  setPipeStep('air', 'running');
  outcome.classList.add('hidden');
  term.innerHTML = `<p class="text-sm text-clay-muted bg-clay-inner rounded-2xl p-4">Checking ${escapeHtml(fac ? fac.name : facId)}: reading live air quality and calling Gemini…</p>`;
  if (latencyEl) latencyEl.textContent = '';
  lucide.createIcons();

  const startedAt = performance.now();
  try {
    const res = await fetch('/api/agents/run-resilience-pipeline', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target_facility_id: facId,
        voice_snippet: snippet
      })
    });

    if (!res.ok) {
      setPipeStep('air', 'idle');
      term.innerHTML = `<p class="text-sm text-[#8F2A19] bg-[#FBE4DE] rounded-2xl p-4">The pipeline failed: ${escapeHtml(await apiErrorMessage(res, 'Server error'))}</p>`;
      return;
    }
    const data = await res.json();
    const seconds = ((performance.now() - startedAt) / 1000).toFixed(1);
    const traces = data.traces || [];
    const summary = pipelineStepSummary(data, traces);
    term.innerHTML = '';

    // Reveal each agent's work in order, so the hand-offs can be followed
    let current = null;
    for (const step of traces) {
      const key = PIPE_STEP_OF[step.agent] || 'cmo';
      if (key !== current) {
        if (current) setPipeStep(current, summary[current].state, summary[current].figure);
        setPipeStep(key, 'running');
        current = key;
      }
      await new Promise(r => setTimeout(r, 320));
      term.appendChild(pipelineLogRow(step));
      lucide.createIcons();
      term.scrollTop = term.scrollHeight;
    }
    Object.entries(summary).forEach(([k, v]) => setPipeStep(k, v.state, v.figure));

    const grounding = traces.find(t => t.type === 'GROUNDING_MATCH');
    renderPipelineOutcome(data, facId, grounding && grounding.payload && grounding.payload.grounded_entity && grounding.payload.grounded_entity.standard_name);
    outcome.classList.remove('hidden');
    const call = traces.find(t => t.type === 'TOOL_CALL');
    const by = call && call.payload ? call.payload.called_by : null;
    if (latencyEl) latencyEl.textContent = `Last run took ${seconds} s` + (by === 'gemini' ? ' · transfer solver called by Gemini' : by === 'claude' ? ' · transfer solver called by Claude (Gemini unavailable)' : '');

    // Refresh UI
    await loadInitialData();
  } catch (err) {
    console.error("Agent pipeline error:", err);
    // Stop any step that was still spinning when the run failed
    document.querySelectorAll('#pipeSteps [data-state="running"]').forEach(li => setPipeStep(li.dataset.step, 'idle'));
    term.innerHTML = '<p class="text-sm text-[#8F2A19] bg-[#FBE4DE] rounded-2xl p-4">The agent pipeline could not finish (network or display error). Please try again.</p>';
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="play" class="w-4 h-4 fill-current"></i><span>Run Agent Pipeline</span>`;
      lucide.createIcons();
    }
  }
}

// Facility Action: Find stock with the agent pipeline
function runTransferFor(facId) {
  const fac = facilities.find(f => f.id === facId);
  if (fac && map && facilityMarkers[facId]) {
    map.flyTo([fac.lat, fac.lng], 13, { duration: 1.0 });
    facilityMarkers[facId].openPopup();
  }

  const facSelect = document.getElementById('voiceFacilitySelect');
  if (facSelect && facId) {
    facSelect.value = facId;
  }

  const term = document.getElementById('agentTerminalBody');
  if (term) {
    term.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  // Run for this facility's highest-risk item; the typed field report (if any) is left untouched
  runAgentPipeline(facId, false);
}

// CMO Conversational Studio
function askCmoQuery(idx) {
  const input = document.getElementById('cmoQueryInput');
  if (idx === 1) {
    input.value = "What if this smog inversion lasts for 5 more days? Which facilities will stock out first?";
  } else if (idx === 2) {
    input.value = "Can we substitute Levosalbutamol respules in place of standard Salbutamol?";
  } else if (idx === 3) {
    input.value = "Prepare a parliamentary constituency health logistics briefing for the Hon. Member of Parliament.";
  }
  submitCmoQuery();
}

async function submitCmoQuery() {
  stopBriefingAudio();  // a new question replaces the briefing being read
  const ttsBtnWhileLoading = document.getElementById('btnTtsSpeak');
  if (ttsBtnWhileLoading) { ttsBtnWhileLoading.classList.add('hidden'); ttsBtnWhileLoading.classList.remove('inline-flex'); }
  const input = document.getElementById('cmoQueryInput');
  const question = input.value.trim();
  if (!question) return;

  const box = document.getElementById('cmoResponseBox');
  box.classList.remove('hidden');
  document.getElementById('cmoAnswerText').innerHTML = '<span class="text-indigo-400 animate-pulse">// Strategic Insight Agent evaluating scenario...</span>';
  document.getElementById('cmoMetaBox').textContent = '';

  try {
    const res = await fetch('/api/cmo/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, region: currentRegion })
    });

    if (!res.ok) {
      document.getElementById('cmoQueryTypeBadge').textContent = "ERROR";
      document.getElementById('cmoAnswerText').textContent = await apiErrorMessage(res, "The Strategic Insight Agent could not answer");
      return;
    }
    const data = await res.json();
    document.getElementById('cmoQueryTypeBadge').textContent = data.query_type || "INSIGHT READY";
    
    // Display English primary response with Hindi translation below
    const answer = `
      <div class="space-y-2">
        <div class="text-clay-dark font-medium leading-relaxed">${escapeHtml(data.answer_en)}</div>
        <div class="text-clay-muted italic border-t border-clay-salmon/20 pt-1.5 text-[11px] font-sans">${escapeHtml(data.answer_hi)}</div>
      </div>
    `;
    document.getElementById('cmoAnswerText').innerHTML = answer;
    const grounding = document.getElementById('cmoGroundingBadge');
    if (grounding) grounding.textContent = `Grounded via District Inventory Store${data.answered_by ? ` · Answered by ${data.answered_by}` : ''}`;

    if (data.recommended_action) {
      document.getElementById('cmoMetaBox').textContent = `Action Protocol: ${data.recommended_action}`;
    } else if (data.substitution_details) {
      document.getElementById('cmoMetaBox').textContent = `Clinical Guidance: ${data.substitution_details.name} (Equivalence: ${data.substitution_details.equivalence_ratio * 100}%)`;
    } else if (data.metrics) {
      document.getElementById('cmoMetaBox').textContent = `MP Summary: ${data.metrics.population_served.toLocaleString()} people served | ${data.metrics.stockout_risks_addressed} stockout risks with a proposed transfer`;
    }

    // Unhide Speech synthesis read-aloud button
    const ttsBtn = document.getElementById('btnTtsSpeak');
    if (ttsBtn) {
      ttsBtn.classList.remove('hidden');
      ttsBtn.classList.add('inline-flex');
    }

    // Refresh audit table
    await fetchAuditLog();
  } catch (err) {
    console.error(err);
    document.getElementById('cmoQueryTypeBadge').textContent = "ERROR";
    document.getElementById('cmoAnswerText').textContent = "Network error while contacting the Strategic Insight Agent. Please try again.";
  }
}

// "Read aloud": Gemini's speech model voices the briefing; the browser's own voice is only a fallback
let briefingAudio = null;
let briefingRequest = null;

function setTtsUi(label, status) {
  const btnLabel = document.getElementById('btnTtsLabel');
  const statusEl = document.getElementById('cmoTtsStatus');
  if (btnLabel) btnLabel.textContent = label;
  if (statusEl) statusEl.textContent = status || '';
}

function stopBriefingAudio() {
  if (briefingRequest) { briefingRequest.abort(); briefingRequest = null; }
  if (briefingAudio) { briefingAudio.pause(); URL.revokeObjectURL(briefingAudio.src); briefingAudio = null; }
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  isSpeaking = false;
  setTtsUi('Read aloud');
}

async function speakCurrentCmoBriefing() {
  if (isSpeaking || briefingRequest) {
    stopBriefingAudio();
    return;
  }
  const answerEl = document.getElementById('cmoAnswerText');
  const rawText = answerEl ? (answerEl.innerText || '') : '';
  // Read the English answer (the first paragraph), not the Hindi translation below it
  const textToSpeak = rawText.split('\n').map(l => l.trim()).filter(Boolean)[0] || '';
  if (!textToSpeak || textToSpeak.startsWith('//')) return;  // no answer yet, only the loading placeholder

  isSpeaking = true;
  setTtsUi('Stop', 'Preparing audio with Gemini…');
  briefingRequest = new AbortController();
  try {
    const res = await fetch('/api/cmo/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: textToSpeak }),
      signal: briefingRequest.signal
    });
    if (!res.ok) throw new Error(`speak HTTP ${res.status}`);
    const blob = await res.blob();
    briefingRequest = null;
    if (!isSpeaking) return;  // stopped while the audio was being prepared
    briefingAudio = new Audio(URL.createObjectURL(blob));
    briefingAudio.onended = stopBriefingAudio;
    briefingAudio.onerror = stopBriefingAudio;
    setTtsUi('Stop', 'Voice: Gemini');
    await briefingAudio.play();
  } catch (err) {
    briefingRequest = null;
    if (err.name === 'AbortError' || !isSpeaking) return;
    console.warn('Gemini speech unavailable, using the browser voice:', err);
    speakWithBrowserVoice(textToSpeak);
  }
}

function speakWithBrowserVoice(text) {
  if (!('speechSynthesis' in window)) {
    stopBriefingAudio();
    setTtsUi('Read aloud', 'Audio is unavailable right now.');
    return;
  }
  const utterance = new SpeechSynthesisUtterance(text);
  // Prefer a natural (online) English voice over the default, which is robotic on many systems
  const voices = window.speechSynthesis.getVoices().filter(v => v.lang && v.lang.startsWith('en'));
  utterance.voice = voices.find(v => /natural|google|online/i.test(v.name) && v.lang === 'en-IN')
    || voices.find(v => /natural|google|online/i.test(v.name))
    || voices.find(v => v.lang === 'en-IN') || voices[0] || null;
  utterance.lang = utterance.voice ? utterance.voice.lang : 'en-IN';
  utterance.rate = 0.95;
  utterance.onend = stopBriefingAudio;
  utterance.onerror = stopBriefingAudio;
  setTtsUi('Stop', 'Voice: browser (Gemini audio unavailable)');
  window.speechSynthesis.speak(utterance);
}

// Downscale a photo to a JPEG data URL so uploads stay well under the serverless body limit
function shrinkImage(file, maxSide = 1280) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL('image/jpeg', 0.85));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Could not read image')); };
    img.src = url;
  });
}

// Gemini Vision Shelf Verification (real photo)
async function runVisionVerification(file) {
  if (!file) return;
  const btn = document.getElementById('btnVision');
  const box = document.getElementById('visionResultBox');
  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Reading photo with Gemini...</span>`;
  lucide.createIcons();

  box.classList.add('hidden');  // never leave the previous scan on screen
  const visionSelect = document.getElementById('visionFacilitySelect');
  const facilityId = (visionSelect && visionSelect.value) || currentClinicFacilityId || (facilities[0] && facilities[0].id);
  try {
    const dataUrl = await shrinkImage(file);
    const res = await fetch('/api/vision/verify-shelf-photo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_base64: dataUrl, facility_id: facilityId })
    });
    if (!res.ok) throw new Error(await apiErrorMessage(res, 'Vision scan failed'));
    const data = await res.json();

    box.classList.remove('hidden');
    const labels = {
      VERIFIED_MATCH: 'Matches register',
      PARTIAL_COUNT: 'Fewer units visible than the register (part of the stock may be out of frame)',
      DISCREPANCY_FLAGGED: 'Discrepancy flagged',
      NOT_A_SHELF_PHOTO: 'Not a medicine shelf',
      NO_ITEMS_DETECTED: 'No items detected',
      NO_CATALOGUE_MATCH: 'Not in this clinic\'s catalogue'
    };
    document.getElementById('visionStatusLabel').textContent = labels[data.status] || data.status;
    const items = data.detected_items || [];
    document.getElementById('visionCountLabel').textContent = items.length ? `${items.length} item${items.length > 1 ? 's' : ''} read` : '';
    const facName = data.facility_name || (facilities.find(f => f.id === facilityId) || {}).name || facilityId;
    document.getElementById('visionFacilityText').textContent = `Compared with the stock register of ${facName}`;
    document.getElementById('visionSummaryText').textContent = data.verification_summary || '';

    btn.disabled = false;
    btn.innerHTML = `<span>Scan Another Photo</span>`;
    await fetchAuditLog();
  } catch (err) {
    console.error(err);
    btn.disabled = false;
    btn.innerHTML = `<span>Upload / Snap Shelf Photo</span>`;
    alert(`Vision scan failed: ${err.message}`);
  }
}

// UI Helper Functions for Modals & Navigation
function openCmoModal() {
  document.getElementById('cmoModal').classList.remove('hidden');
  setTimeout(() => {
    const input = document.getElementById('cmoQueryInput');
    if (input) input.focus();
  }, 100);
}

function closeCmoModal() {
  stopBriefingAudio();
  document.getElementById('cmoModal').classList.add('hidden');
}

function openFacilityDetail(facId) {
  const fac = facilities.find(f => f.id === facId);
  if (!fac) return;

  currentInspectFacilityId = facId;
  const summary = facRiskSummary[facId] || { criticalCount: 0, warningCount: 0, surplusCount: 0, items: [] };

  const nameEl = document.getElementById('facDetailName');
  if (nameEl) nameEl.textContent = fac.name;

  const subEl = document.getElementById('facDetailSub');
  if (subEl) subEl.textContent = `${fac.district} District • ${fac.type} • In-Charge (demo persona): ${fac.doctor}`;

  const popEl = document.getElementById('facDetailPop');
  if (popEl) popEl.textContent = (fac.population_served || 45000).toLocaleString();

  const bedsEl = document.getElementById('facDetailBeds');
  if (bedsEl) bedsEl.textContent = `${fac.beds || 12} Beds`;

  const coldEl = document.getElementById('facDetailCold');
  if (coldEl) coldEl.textContent = fac.cold_storage ? "Active (Solar+Grid)" : "Grid-Only (Backup Req)";

  const coordsEl = document.getElementById('facDetailCoords');
  if (coordsEl) coordsEl.textContent = `${fac.lat.toFixed(2)}°N, ${fac.lng.toFixed(2)}°E`;

  const facDetailIcon = document.getElementById('facDetailIcon');
  if (facDetailIcon) {
    facDetailIcon.textContent = fac.type;
    facDetailIcon.className = `w-12 h-12 rounded-2xl ${summary.criticalCount > 0 ? 'bg-red-500' : 'bg-clay-terracotta'} text-white flex items-center justify-center font-bold text-base shadow-sm`;
  }

  const badgeEl = document.getElementById('facDetailBadge');
  if (badgeEl) {
    if (summary.criticalCount > 0) {
      badgeEl.textContent = `${summary.criticalCount} CRITICAL SHORTAGES`;
      badgeEl.className = 'text-xs bg-red-100 text-red-700 font-black px-3 py-1 rounded-full border border-red-200';
    } else if (summary.warningCount > 0) {
      badgeEl.textContent = `${summary.warningCount} IMPENDING SHORTAGES`;
      badgeEl.className = 'text-xs bg-amber-100 text-amber-700 font-black px-3 py-1 rounded-full border border-amber-200';
    } else {
      badgeEl.textContent = 'STOCKS BALANCED & HEALTHY';
      badgeEl.className = 'text-xs bg-emerald-100 text-emerald-700 font-black px-3 py-1 rounded-full border border-emerald-200';
    }
  }

  const listContainer = document.getElementById('facDetailMedicineList');
  if (listContainer) {
    listContainer.innerHTML = '';
    summary.items.forEach(item => {
      const isCritical = item.status === 'CRITICAL';
      const isWarning = item.status === 'WARNING';
      const isSurplus = item.status === 'SURPLUS';

      const barColor = isCritical ? 'bg-red-500' : (isWarning ? 'bg-amber-500' : (isSurplus ? 'bg-teal-500' : 'bg-emerald-500'));
      const statusText = isCritical ? 'CRITICAL (<4d)' : (isWarning ? 'WARNING (<8d)' : (isSurplus ? 'SURPLUS (>21d)' : 'HEALTHY'));
      const badgeStyle = isCritical ? 'bg-red-100 text-red-700 border-red-200' : (isWarning ? 'bg-amber-100 text-amber-700 border-amber-200' : 'bg-emerald-100 text-emerald-700 border-emerald-200');

      const pct = Math.min(100, Math.max(5, Math.round((item.days_of_coverage / 20) * 100)));

      const card = document.createElement('div');
      card.className = 'bg-white p-4 rounded-2xl border border-clay-salmon/20 shadow-sm space-y-2';
      card.innerHTML = `
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-2.5">
            <strong class="text-sm sm:text-base font-black text-clay-dark">${escapeHtml(item.medicine_name.split('(')[0])}</strong>
            <span class="text-xs px-2.5 py-0.5 rounded-full border font-black ${badgeStyle}">${statusText}</span>
          </div>
          <div class="text-right">
            <span class="text-sm sm:text-base font-black text-clay-dark tabular-nums">${item.current_stock} units</span>
          </div>
        </div>
        <div class="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden">
          <div class="${barColor} h-2.5 rounded-full transition-all duration-500" style="width: ${pct}%"></div>
        </div>
        <div class="flex items-center justify-between text-xs text-clay-muted font-medium pt-0.5">
          <span>Coverage: <strong class="${isCritical ? 'text-red-600 font-black' : 'text-clay-dark font-black'}">${item.days_of_coverage} Days</strong></span>
          <span>Projected Burn: <strong class="text-slate-800 font-bold">${item.projected_daily_rate} u/day</strong></span>
          <span>Stockout Risk (7d): <strong class="${item.stockout_probability_7d > 0.5 ? 'text-red-600 font-black' : 'text-slate-700 font-bold'}">${Math.round(item.stockout_probability_7d * 100)}%</strong></span>
        </div>
      `;
      listContainer.appendChild(card);
    });
  }

  const modal = document.getElementById('facilityDetailModal');
  if (modal) modal.classList.remove('hidden');
}

function closeFacilityDetail() {
  const m = document.getElementById('facilityDetailModal');
  if (m) m.classList.add('hidden');
}

function renderNotifications() {
  const list = document.getElementById('notificationsList');
  if (!list) return;
  const cards = [];
  const card = (tone, title, badge, body) => cards.push(`
    <div class="p-4 bg-${tone}-50 rounded-2xl border border-${tone}-200 text-xs sm:text-sm space-y-1.5">
      <div class="flex items-center justify-between gap-2 font-black text-${tone}-800">
        <span class="text-sm sm:text-base">${title}</span>
        <span class="text-xs bg-${tone}-200 text-${tone}-900 px-2.5 py-1 rounded-full font-bold whitespace-nowrap">${badge}</span>
      </div>
      <p class="text-${tone}-700 text-xs sm:text-sm leading-relaxed font-medium">${body}</p>
    </div>`);

  const t = currentTelemetry;
  if (t) {
    const source = (t.source && t.source.includes('Open-Meteo')) ? 'Live Open-Meteo / CAMS data' : 'Simulated scenario';
    if (t.smog_episode || t.aqi > 150) {
      card('red', '🌫️ Poor Air Quality', `AQI ${escapeHtml(t.aqi)} &bull; ${escapeHtml(aqiCategory(t.aqi))}`,
        `${escapeHtml(source)} for ${escapeHtml(t.corridor || '')}: PM2.5 ${escapeHtml(t.pm25)} µg/m³${t.forecast_peak_aqi_72h ? `, 72h peak AQI ${escapeHtml(t.forecast_peak_aqi_72h)}` : ''}. Respiratory demand is raised in the forecast.`);
    }
    if (t.flood_alert) {
      card('red', '🌧️ Flood / Very Heavy Rain', `${escapeHtml(t.rain_24h_mm ?? 'n/a')} mm / 24 h`, `${escapeHtml(source)}: diarrhoea and fever usually rise in the days after; ORS and fever-medicine demand is raised in the forecast.`);
    }
    if (t.cold_wave_alert) {
      card('red', '❄️ Cold Wave', `Min ${escapeHtml(t.min_temp_c ?? t.temperature_c)}°C`, `${escapeHtml(source)}: chest infections rise in cold spells; antibiotic and fever-medicine demand is raised in the forecast.`);
    }
    if (t.heatwave_alert) {
      card('red', '☀️ Heatwave Alert', `${escapeHtml(t.temperature_c)}°C`, `${escapeHtml(source)}: heatwave threshold reached; ORS and fluids demand is raised in the forecast.`);
    }
  }
  allRisks.filter(r => r.status === 'CRITICAL').sort((a, b) => a.days_of_coverage - b.days_of_coverage).slice(0, 3).forEach(r => {
    card('amber', '⚠️ Stockout Risk', `${escapeHtml(r.days_of_coverage)} Days Cover`,
      `${escapeHtml(r.facility_name)}: ${escapeHtml(r.current_stock)} units of ${escapeHtml(r.medicine_name.split('(')[0])} left, 7-day stockout probability ${Math.round(r.stockout_probability_7d * 100)}%.`);
  });
  const pending = activeRecs.filter(r => r.status === 'PENDING_APPROVAL');
  if (pending.length) {
    const units = pending.reduce((n, r) => n + r.units_to_transfer, 0);
    card('emerald', '🚚 Transfers Awaiting Sign-off', `${pending.length} pending`,
      `${units} units across ${pending.length} proposed transfers are waiting for CMO approval.`);
  }
  list.innerHTML = cards.length ? cards.join('') : '<div class="p-4 text-center text-clay-muted text-sm font-medium">No active alerts for this corridor.</div>';
}

function openNotificationsModal() {
  renderNotifications();
  const m = document.getElementById('notificationsModal');
  if (m) m.classList.remove('hidden');
}

function closeNotificationsModal() {
  const m = document.getElementById('notificationsModal');
  if (m) m.classList.add('hidden');
}

function showInfoModal() {
  const m = document.getElementById('infoModal');
  if (m) m.classList.remove('hidden');
}

function closeInfoModal() {
  const m = document.getElementById('infoModal');
  if (m) m.classList.add('hidden');
}

function openLedgerModal() {
  const m = document.getElementById('ledgerModal');
  if (m) m.classList.remove('hidden');
  fetchAuditLog();
}

function closeLedgerModal() {
  const m = document.getElementById('ledgerModal');
  if (m) m.classList.add('hidden');
}

// Filter the dashboard to one medicine; never touches the typed field report
function filterMedicine(medId) {
  const known = allRisks.find(r => r.medicine_id === medId);
  const term = known ? known.medicine_name.split('(')[0].trim().split(' ')[0] : (MEDICINE_SHORT_NAMES[medId] || medId);
  const searchInput = document.getElementById('searchInput');
  if (searchInput) searchInput.value = term;
  filterDashboardBySearch(term);
}

const MEDICINE_SHORT_NAMES = { 'MED-001': 'Salbutamol', 'MED-002': 'ORS', 'MED-003': 'Dexamethasone', 'MED-004': 'Amoxicillin', 'MED-005': 'Paracetamol', 'MED-006': 'Cetirizine' };

// Side rail button styles (icon + label)
const NAV_BASE = 'w-full py-2.5 rounded-2xl flex flex-col items-center justify-center gap-1 transition hover:scale-105';
const NAV_ON = `${NAV_BASE} bg-white text-clay-terracotta shadow-md`;
const NAV_OFF = `${NAV_BASE} hover:bg-white/20 text-white/90`;

// "How it works" strip: scroll to a step's section and flash it
function jumpToStep(id) {
  switchMainView('district');
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  el.classList.add('step-flash');
  setTimeout(() => el.classList.remove('step-flash'), 1600);
}

function switchTab(tab) {
  const navItems = {
    'dashboard': document.getElementById('nav-dashboard'),
    'clinic': document.getElementById('nav-clinic'),
    'agents': document.getElementById('nav-agents'),
    'cmo': document.getElementById('nav-cmo'),
    'vision': document.getElementById('nav-vision'),
    'ledger': document.getElementById('nav-ledger'),
    'news': document.getElementById('nav-news')
  };

  Object.entries(navItems).forEach(([key, el]) => {
    if (!el) return;
    if (key === tab) {
      el.className = NAV_ON;
    } else {
      el.className = NAV_OFF;
    }
  });

  if (tab === 'clinic') {
    switchMainView('clinic');
  } else if (tab === 'dashboard') {
    switchMainView('district');
  } else if (tab === 'cmo') {
    openCmoModal();
  } else if (tab === 'agents') {
    // Navigation only: the paid pipeline runs when the user presses its Run button
    switchMainView('district');
    const term = document.getElementById('agentTerminalBody');
    if (term) term.scrollIntoView({ behavior: 'smooth', block: 'center' });
  } else if (tab === 'vision') {
    const btnV = document.getElementById('btnVision');
    if (btnV) btnV.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const picker = document.getElementById('visionFileInput');
    if (picker) picker.click();
  } else if (tab === 'ledger') {
    openLedgerModal();
  } else if (tab === 'news') {
    openNewsModal();
  } else {
    const canvas = document.getElementById('mainCanvas');
    if (canvas) {
      canvas.scrollTo({ top: 0, behavior: 'smooth' });
    } else {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }
}

// Search Filtering across Watchlist, Recommendations, and Map
function filterDashboardBySearch(query) {
  activeSearchQuery = (query || '').trim();
  const clearBtn = document.getElementById('clearSearchBtn');
  if (clearBtn) {
    clearBtn.classList.toggle('hidden', !activeSearchQuery);
  }

  renderWatchlist(activeSearchQuery);
  renderRecommendations(activeSearchQuery);
  applyMapFilter(activeSearchQuery);
}

function clearSearch() {
  const input = document.getElementById('searchInput');
  if (input) input.value = '';
  filterDashboardBySearch('');
}

function applyMapFilter(query) {
  const q = (query || '').toLowerCase().trim();
  let firstMatchedFac = null;

  facilities.forEach(fac => {
    const marker = facilityMarkers[fac.id];
    if (!marker) return;

    const summary = facRiskSummary[fac.id];
    const matchesMed = summary && summary.items.some(i => i.medicine_name.toLowerCase().includes(q));
    const matches = !q || 
      fac.name.toLowerCase().includes(q) || 
      fac.district.toLowerCase().includes(q) || 
      fac.type.toLowerCase().includes(q) ||
      matchesMed;

    if (matches) {
      if (marker.setOpacity) marker.setOpacity(1.0);
      if (marker.setStyle) marker.setStyle({ opacity: 0.9, fillOpacity: 0.85 });
      if (!firstMatchedFac && q) firstMatchedFac = fac;
    } else {
      if (marker.setOpacity) marker.setOpacity(0.2);
      if (marker.setStyle) marker.setStyle({ opacity: 0.15, fillOpacity: 0.1 });
    }
  });

  if (firstMatchedFac && map) {
    map.panTo([firstMatchedFac.lat, firstMatchedFac.lng]);
    if (facilityMarkers[firstMatchedFac.id]) {
      facilityMarkers[firstMatchedFac.id].openPopup();
    }
  }
}

// Event Listeners for Keyboard & Interactivity
function setupEventListeners() {
  const searchInput = document.getElementById('searchInput');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      filterDashboardBySearch(e.target.value);
    });
    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        clearSearch();
      }
    });
  }

  const cmoInput = document.getElementById('cmoQueryInput');
  if (cmoInput) {
    cmoInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        submitCmoQuery();
      }
    });
  }

  // Backdrop click listener to dismiss any open modal
  ['cmoModal', 'challanModal', 'ledgerModal', 'notificationsModal', 'infoModal', 'facilityDetailModal', 'stockActionModal', 'receiptInspectionModal', 'dispatchConsignmentModal'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('click', (e) => {
        if (e.target === el) {
          el.classList.add('hidden');
        }
      });
    }
  });

  // ESC key listener to dismiss any open modal
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      ['cmoModal', 'challanModal', 'ledgerModal', 'notificationsModal', 'infoModal', 'facilityDetailModal', 'stockActionModal', 'receiptInspectionModal', 'dispatchConsignmentModal'].forEach(id => {
        const el = document.getElementById(id);
        if (el && !el.classList.contains('hidden')) {
          el.classList.add('hidden');
        }
      });
    }
  });
}

// US AQI categories (Open-Meteo / CAMS report the US EPA index)
function aqiCategory(aqi) {
  if (aqi == null || isNaN(aqi)) return 'n/a';
  if (aqi <= 50) return 'Good';
  if (aqi <= 100) return 'Moderate';
  if (aqi <= 150) return 'Unhealthy for Sensitive Groups';
  if (aqi <= 200) return 'Unhealthy';
  if (aqi <= 300) return 'Very Unhealthy';
  return 'Hazardous';
}

function highlightScenarioButton(active) {
  const inactive = 'px-3.5 py-2 rounded-full font-bold text-xs sm:text-sm text-clay-muted hover:text-clay-dark hover:bg-white transition cursor-pointer';
  const ids = { live: 'scenarioLive', smog: 'scenarioSmog', heat: 'scenarioHeat', flood: 'scenarioFlood', cold: 'scenarioCold', normal: 'scenarioNormal' };
  Object.entries(ids).forEach(([key, id]) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (key !== active) el.className = inactive + (key === 'live' ? ' flex items-center space-x-1.5' : '');
    else if (key === 'live') el.className = 'px-3.5 py-2 rounded-full font-black text-xs sm:text-sm bg-emerald-600 text-white shadow-clay-btn transition flex items-center space-x-1.5 cursor-pointer';
    else el.className = 'px-3.5 py-2 rounded-full font-black text-xs sm:text-sm bg-clay-terracotta text-white shadow-clay-btn transition cursor-pointer';
  });
}

// Best-effort readable error from a failed API response (FastAPI puts it in `detail`)
async function apiErrorMessage(res, fallback) {
  try {
    const data = await res.json();
    if (typeof data.detail === 'string') return data.detail;
    if (Array.isArray(data.detail) && data.detail[0] && data.detail[0].msg) return data.detail[0].msg;
  } catch (e) { /* non-JSON body */ }
  return `${fallback} (HTTP ${res.status})`;
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// IDs interpolated into inline JS handlers: allow only ID characters
function safeId(id) {
  return String(id || '').replace(/[^A-Za-z0-9_-]/g, '');
}

// ==============================================================================
// CLINIC DAILY DESK - FRONTLINE PHARMACIST WORKSPACE
// ==============================================================================

function switchMainView(view, loadDesk = true) {
  const districtContainer = document.getElementById('districtViewContainer');
  const clinicContainer = document.getElementById('clinicDeskViewContainer');
  const btnDistrict = document.getElementById('btnViewDistrict');
  const btnClinic = document.getElementById('btnViewClinic');
  const navDashboard = document.getElementById('nav-dashboard');
  const navClinic = document.getElementById('nav-clinic');

  if (view === 'clinic') {
    if (districtContainer) districtContainer.classList.add('hidden');
    if (clinicContainer) {
      clinicContainer.classList.remove('hidden');
      clinicContainer.classList.add('flex');
    }
    if (btnDistrict) {
      btnDistrict.className = 'px-3.5 py-2 rounded-full font-black text-xs sm:text-sm text-clay-muted hover:text-clay-dark hover:bg-white transition flex items-center space-x-1.5 cursor-pointer';
    }
    if (btnClinic) {
      btnClinic.className = 'px-3.5 py-2 rounded-full font-black text-xs sm:text-sm bg-clay-terracotta text-white shadow-clay-btn transition flex items-center space-x-1.5 cursor-pointer';
    }
    if (navDashboard) navDashboard.className = NAV_OFF;
    if (navClinic) navClinic.className = NAV_ON;

    if (loadDesk) loadClinicDesk(currentClinicFacilityId);
  } else {
    if (clinicContainer) {
      clinicContainer.classList.add('hidden');
      clinicContainer.classList.remove('flex');
    }
    if (districtContainer) districtContainer.classList.remove('hidden');
    if (btnDistrict) {
      btnDistrict.className = 'px-3.5 py-2 rounded-full font-black text-xs sm:text-sm bg-clay-terracotta text-white shadow-clay-btn transition flex items-center space-x-1.5 cursor-pointer';
    }
    if (btnClinic) {
      btnClinic.className = 'px-3.5 py-2 rounded-full font-black text-xs sm:text-sm text-clay-muted hover:text-clay-dark hover:bg-white transition flex items-center space-x-1.5 cursor-pointer';
    }
    if (navDashboard) navDashboard.className = NAV_ON;
    if (navClinic) navClinic.className = NAV_OFF;

    if (map) {
      setTimeout(() => map.invalidateSize(), 150);
    }
  }
}

function onClinicFacilityChange(facilityId) {
  currentClinicFacilityId = facilityId;
  loadClinicDesk(facilityId);
}

let clinicDeskRequestSeq = 0;

// ---- Clinic view language (English / Hindi) ----
const CLINIC_I18N = {
  en: {
    eyebrow: 'Frontline Facility Workspace', demoRole: 'Demo Role Simulation',
    session: 'Signed in as: Demo Pharmacist (staff pharmacist / storekeeper) · demo stock register',
    refresh: 'Refresh Desk', recordAction: 'Record Stock Action', todayActions: "Today's Action Priorities",
    ranked: 'Most urgent first', actionsCount: '{n} Actions',
    stockShelf: 'Stock on the shelf', stockShelfSub: 'Counted stock, what is free to use, and what is reserved for transfers',
    filter: 'Filter medicine or batch...',
    incoming: 'Deliveries coming in', incomingSub: 'Sent by other clinics. On arrival, inspect, count and record the receipt.',
    outgoing: 'Stock going out', outgoingSub: 'Stock is reserved on the shelf. Hand the package to the courier and confirm dispatch.',
    incomingCount: '{n} Incoming', outgoingCount: '{n} Outgoing',
    noActionsTitle: 'All Daily Action Items Clear',
    noActionsBody: 'No impending stockouts, pending dispatches, or uninspected deliveries at this facility.',
    CRITICAL: 'CRITICAL', HIGH: 'HIGH', MEDIUM: 'MEDIUM', LOW: 'LOW',
    available: 'Available', onHand: 'On Hand', reserved: 'Reserved', quarantined: 'Quarantined', inTransit: 'In Transit',
    batch: 'Batch', pack: 'Pack', exp: 'Exp', units: 'units', Units: 'Units', register: 'Register', update: 'Update', resolve: 'Resolve',
    frozen: 'DEFICIT FROZEN', deficit: 'Deficit', noMatch: 'No medicine batches match your search filter.',
    badgeInTransit: '🚚 In Transit', badgePreparing: '⏳ Donor Preparing', from: 'From', to: 'To', vehicle: 'Vehicle',
    notRecorded: 'not recorded', notAssigned: 'not assigned yet', confirmReceipt: 'Inspect & Confirm Receipt',
    awaitingCourier: 'Awaiting physical courier dispatch from donor facility.',
    badgeReserved: '📦 Stock Reserved', badgeDispatched: '🚚 Dispatched', courierHandover: 'Courier Handover', cancel: 'Cancel',
    viewChallan: 'View Challan', noInbound: 'No inbound deliveries currently en route to this facility.',
    noOutbound: 'No outbound consignments scheduled for this facility.', district: 'District', pop: 'Pop'
  },
  hi: {
    eyebrow: 'क्लिनिक कार्यक्षेत्र', demoRole: 'डेमो भूमिका',
    session: 'लॉग-इन: डेमो फ़ार्मासिस्ट (फ़ार्मासिस्ट / भंडारपाल) · डेमो स्टॉक रजिस्टर',
    refresh: 'रीफ़्रेश करें', recordAction: 'स्टॉक दर्ज करें', todayActions: 'आज के ज़रूरी काम',
    ranked: 'सबसे ज़रूरी पहले', actionsCount: '{n} काम',
    stockShelf: 'शेल्फ़ पर स्टॉक', stockShelfSub: 'गिना हुआ स्टॉक, इस्तेमाल के लिए उपलब्ध, और ट्रांसफ़र के लिए आरक्षित',
    filter: 'दवा या बैच खोजें…',
    incoming: 'आने वाली खेप', incomingSub: 'दूसरे केंद्रों से भेजी गई। पहुँचने पर जाँचें, गिनें और रसीद दर्ज करें।',
    outgoing: 'जाने वाला स्टॉक', outgoingSub: 'स्टॉक शेल्फ़ पर आरक्षित है। पैकेट कूरियर को सौंपें और भेजना पक्का करें।',
    incomingCount: '{n} आ रही', outgoingCount: '{n} जा रही',
    noActionsTitle: 'आज कोई ज़रूरी काम बाकी नहीं',
    noActionsBody: 'इस केंद्र पर न दवा खत्म हो रही है, न कोई खेप भेजनी या जाँचनी बाकी है।',
    CRITICAL: 'गंभीर', HIGH: 'ज़रूरी', MEDIUM: 'सामान्य', LOW: 'कम',
    available: 'उपलब्ध', onHand: 'कुल', reserved: 'आरक्षित', quarantined: 'अलग रखा', inTransit: 'रास्ते में',
    batch: 'बैच', pack: 'पैक', exp: 'एक्सपायरी', units: 'यूनिट', Units: 'यूनिट', register: 'रजिस्टर', update: 'अपडेट', resolve: 'सुलझाएँ',
    frozen: 'कमी: रोका गया', deficit: 'कमी', noMatch: 'खोज से कोई दवा या बैच नहीं मिला।',
    badgeInTransit: '🚚 रास्ते में', badgePreparing: '⏳ भेजने की तैयारी', from: 'कहाँ से', to: 'कहाँ', vehicle: 'वाहन',
    notRecorded: 'दर्ज नहीं', notAssigned: 'अभी तय नहीं', confirmReceipt: 'जाँचें और रसीद पक्की करें',
    awaitingCourier: 'भेजने वाले केंद्र से कूरियर का इंतज़ार।',
    badgeReserved: '📦 स्टॉक आरक्षित', badgeDispatched: '🚚 भेज दिया', courierHandover: 'कूरियर को सौंपें', cancel: 'रद्द करें',
    viewChallan: 'चालान देखें', noInbound: 'इस केंद्र के लिए अभी कोई खेप रास्ते में नहीं है।',
    noOutbound: 'इस केंद्र से अभी कुछ भेजना तय नहीं है।', district: 'ज़िला', pop: 'आबादी'
  }
};
const CLINIC_LANG_KEY = 'aarogya.clinicLang';
let clinicLang = 'en';
try { if (localStorage.getItem(CLINIC_LANG_KEY) === 'hi') clinicLang = 'hi'; } catch (e) { /* storage blocked */ }

function t(key, vars) {
  let text = (CLINIC_I18N[clinicLang] || {})[key] ?? CLINIC_I18N.en[key] ?? key;
  if (vars) Object.entries(vars).forEach(([k, v]) => { text = text.replace(`{${k}}`, v); });
  return text;
}

function applyClinicLang() {
  const root = document.getElementById('clinicDeskViewContainer');
  if (!root) return;
  root.lang = clinicLang;
  root.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  [['en', 'clinicLangEn'], ['hi', 'clinicLangHi']].forEach(([lang, id]) => {
    const btn = document.getElementById(id);
    if (!btn) return;
    const on = lang === clinicLang;
    btn.className = `px-3 py-1.5 rounded-lg text-xs font-black transition ${on ? 'bg-clay-terracotta text-white' : 'text-clay-muted hover:text-clay-dark'}`;
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
}

function setClinicLang(lang) {
  clinicLang = lang === 'hi' ? 'hi' : 'en';
  try { localStorage.setItem(CLINIC_LANG_KEY, clinicLang); } catch (e) { /* keep for this page only */ }
  applyClinicLang();
  if (activeClinicDeskData) renderClinicDesk(activeClinicDeskData);
}

function renderClinicDesk(data) {
  const badgeEl = document.getElementById('clinicFacilityBadge');
  if (badgeEl && data.facility) {
    badgeEl.textContent = `${data.facility.type} • ${data.facility.district} ${t('district')} • ${t('pop')}: ${(data.facility.population_served || 20000).toLocaleString()}`;
  }
  renderClinicActionItems(data.action_items || []);
  renderClinicInventory(data.inventory || []);
  renderClinicConsignments(data.inbound_consignments || [], data.outbound_consignments || []);
  if (window.lucide) lucide.createIcons();
}

async function loadClinicDesk(facilityId) {
  if (!facilityId) facilityId = currentClinicFacilityId || (currentRegion === 'bhubaneswar' ? "PHC-BBS-01" : "PHC-LKO-01");
  currentClinicFacilityId = facilityId;
  // Only the latest request may render, so a slow response for another facility can't overwrite it
  const seq = ++clinicDeskRequestSeq;

  const select = document.getElementById('clinicFacilitySelect');
  if (select && select.value !== facilityId) {
    select.value = facilityId;
  }

  try {
    const res = await fetch(`/api/clinic/${encodeURIComponent(facilityId)}/desk`);
    if (seq !== clinicDeskRequestSeq) return;
    if (!res.ok) {
      console.error("Failed to load clinic desk:", res.status);
      return;
    }
    const data = await res.json();
    if (seq !== clinicDeskRequestSeq) return;
    activeClinicDeskData = data;

    applyClinicLang();

    // Fetch and display safe system capability indicator
    if (!window._systemCapsLoaded) {
      fetch('/api/system/capabilities')
        .then(r => r.json())
        .then(caps => {
          window._systemCapsLoaded = true;
          const capBadge = document.getElementById('systemCapabilityBadge');
          if (capBadge) {
            const isDurable = caps.durable_storage;
            const storageLabel = caps.storage_backend === 'firestore' ? 'Cloud Firestore (Durable)' : 'Demo Mode (Ephemeral)';
            capBadge.innerHTML = `Storage: <strong>${storageLabel}</strong> &bull; Audit: <strong>Hash-Linked SHA-256</strong>`;
            if (!isDurable) {
              capBadge.className = 'px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-700 border border-slate-300';
            } else {
              capBadge.className = 'px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-800 border border-emerald-300';
            }
          }
        }).catch(() => {});
    }

    renderClinicDesk(data);
  } catch (err) {
    console.error("loadClinicDesk error:", err);
  }
}

function renderClinicActionItems(items) {
  const container = document.getElementById('clinicActionItemsList');
  const countBadge = document.getElementById('clinicActionCountBadge');
  if (!container) return;

  if (countBadge) {
    countBadge.textContent = t('actionsCount', { n: items.length });
    if (items.length === 0) {
      countBadge.className = "px-2.5 py-0.5 rounded-full text-xs font-black bg-emerald-100 text-emerald-800";
    } else {
      countBadge.className = "px-2.5 py-0.5 rounded-full text-xs font-black bg-red-100 text-red-700";
    }
  }

  if (items.length === 0) {
    container.innerHTML = `
      <div class="col-span-full bg-white rounded-2xl p-6 text-center border border-emerald-200 shadow-sm">
        <span class="text-2xl block mb-1">🎉</span>
        <h4 class="text-sm font-black text-emerald-800">${t('noActionsTitle')}</h4>
        <p class="text-xs text-clay-muted mt-1 font-medium">${t('noActionsBody')}</p>
      </div>
    `;
    return;
  }

  container.innerHTML = '';
  const hi = clinicLang === 'hi';
  items.forEach(item => {
    let urgencyColor = "bg-red-50 border-red-200 text-red-900";
    let badgeColor = "bg-red-600 text-white";
    let iconName = "alert-triangle";

    if (item.urgency === 'CRITICAL') {
      urgencyColor = "bg-red-50/90 border-red-200 text-red-900";
      badgeColor = "bg-red-600 text-white";
      iconName = "alert-triangle";
    } else if (item.urgency === 'HIGH') {
      urgencyColor = "bg-amber-50/90 border-amber-200 text-amber-900";
      badgeColor = "bg-amber-600 text-white";
      iconName = "alert-circle";
    } else if (item.urgency === 'MEDIUM') {
      urgencyColor = "bg-blue-50/90 border-blue-200 text-blue-900";
      badgeColor = "bg-blue-600 text-white";
      iconName = "info";
    } else {
      urgencyColor = "bg-slate-50/90 border-slate-200 text-slate-900";
      badgeColor = "bg-slate-600 text-white";
      iconName = "check-circle";
    }

    let onclickStr = '';
    const medId = safeId(item.target_medicine_id);
    const batch = safeId(item.target_batch);
    if (item.action_type === 'INBOUND_TRANSFER_PENDING') {
      onclickStr = `openReceiptModal('${safeId(item.target_consignment_id)}')`;
    } else if (item.action_type === 'OUTBOUND_DISPATCH_PENDING') {
      onclickStr = `openDispatchModal('${safeId(item.target_consignment_id)}')`;
    } else if (item.action_type === 'RECONCILIATION_REQUIRED') {
      onclickStr = `openResolveReconciliationModal('${medId}', '${batch}')`;
    } else if (item.action_type === 'IMPENDING_STOCKOUT') {
      onclickStr = `requestTransferFor('${safeId(currentClinicFacilityId)}', '${medId}')`;
    } else {
      onclickStr = `openStockActionModal('${medId}', '${batch}')`;
    }

    const card = document.createElement('div');
    card.className = `p-4 rounded-2xl border ${urgencyColor} flex flex-col justify-between space-y-3 shadow-sm`;
    card.innerHTML = `
      <div>
        <div class="flex items-center justify-between gap-2 mb-1.5">
          <span class="inline-flex items-center space-x-1 text-[10px] font-black uppercase px-2 py-0.5 rounded-full ${badgeColor}">
            <i data-lucide="${iconName}" class="w-3 h-3"></i>
            <span>${escapeHtml(t(item.urgency))}</span>
          </span>
          <span class="text-[10px] font-mono font-bold text-clay-muted">${escapeHtml(item.action_type)}</span>
        </div>
        <h4 class="text-sm font-black text-clay-dark leading-snug">${escapeHtml(hi && item.title_hi ? item.title_hi : item.title)}</h4>
        <p class="text-xs text-clay-muted mt-1 leading-relaxed font-medium">${escapeHtml(hi && item.description_hi ? item.description_hi : item.description)}</p>
      </div>
      <button onclick="${onclickStr}" class="w-full bg-white hover:bg-clay-bg border border-clay-salmon/30 text-clay-dark font-black text-xs py-2 px-3 rounded-xl transition shadow-sm flex items-center justify-center space-x-1.5 hover:scale-[1.01] cursor-pointer">
        <span>${escapeHtml(hi && item.cta_label_hi ? item.cta_label_hi : item.cta_label)}</span>
        <i data-lucide="chevron-right" class="w-3.5 h-3.5 text-clay-terracotta"></i>
      </button>
    `;
    container.appendChild(card);
  });
}

// "Request Stock Transfer": show the solver's proposed transfer for this facility and medicine,
// or run the agent pipeline for the facility when none is proposed yet
function requestTransferFor(facilityId, medicineId) {
  switchMainView('district', false);
  const rec = activeRecs.find(r => r.recipient_facility_id === facilityId && r.medicine_id === medicineId && r.status === 'PENDING_APPROVAL');
  if (rec) {
    const searchInput = document.getElementById('searchInput');
    if (searchInput) searchInput.value = rec.recipient_facility_name;
    filterDashboardBySearch(rec.recipient_facility_name);
    const list = document.getElementById('recommendationsList');
    if (list) list.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return;
  }
  alert('No donor transfer is proposed for this item yet. Running the agent pipeline for this facility to search for one.');
  runTransferFor(facilityId);
}

function filterClinicInventory(query) {
  clinicInventoryFilterQuery = (query || '').toLowerCase().trim();
  if (activeClinicDeskData) {
    renderClinicInventory(activeClinicDeskData.inventory || []);
  }
}

function renderClinicInventory(inventory) {
  const container = document.getElementById('clinicInventoryList');
  if (!container) return;

  const q = clinicInventoryFilterQuery;
  const filtered = inventory.filter(item => {
    if (!q) return true;
    return (
      (item.medicine_name && item.medicine_name.toLowerCase().includes(q)) ||
      (item.medicine_id && item.medicine_id.toLowerCase().includes(q)) ||
      (item.batch_number && item.batch_number.toLowerCase().includes(q)) ||
      (item.category && item.category.toLowerCase().includes(q))
    );
  });

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="p-8 text-center text-clay-muted text-xs font-bold bg-white rounded-2xl border border-clay-salmon/15">
        ${t('noMatch')}
      </div>
    `;
    return;
  }

  container.innerHTML = '';
  filtered.forEach(item => {
    const onHand = item.on_hand != null ? item.on_hand : (item.current_stock || 0);
    const reserved = item.reserved || 0;
    const quarantined = item.quarantined || 0;
    const available = item.available != null ? item.available : Math.max(0, onHand - reserved - quarantined);
    const inTransit = item.in_transit || 0;
    const isFrozen = item.is_frozen || item.is_reconciliation_required || false;
    const deficit = item.reconciliation_deficit || 0;

    const row = document.createElement('div');
    row.className = `p-4 rounded-2xl bg-white border ${isFrozen ? 'border-red-400 ring-2 ring-red-200' : 'border-clay-salmon/20'} shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4 transition hover:border-clay-salmon/40`;

    row.innerHTML = `
      <div class="flex-1">
        <div class="flex items-center space-x-2">
          <h4 class="text-sm font-black text-clay-dark">${escapeHtml(item.medicine_name)}</h4>
          <span class="text-[10px] font-bold text-clay-muted bg-clay-inner px-2 py-0.5 rounded-md border border-clay-salmon/20">${item.category || 'EDL'}</span>
          ${isFrozen ? `<span class="text-[10px] font-black uppercase tracking-wider bg-red-600 text-white px-2 py-0.5 rounded-md animate-pulse">${t('frozen')}</span>` : ''}
          ${deficit > 0 ? `<span class="text-[10px] font-extrabold text-red-700 bg-red-50 border border-red-200 px-2 py-0.5 rounded-md font-mono">${t('deficit')}: -${deficit}</span>` : ''}
        </div>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1 text-xs text-clay-muted font-mono">
          <span>${t('batch')}: <strong class="text-clay-dark">${escapeHtml(item.batch_number || 'BAT-DEFAULT')}</strong></span>
          <span>•</span>
          <span>${t('pack')}: <strong class="text-clay-dark">${item.pack_size || 10} ${t('units')}</strong></span>
          <span>•</span>
          <span>${t('exp')}: <strong class="text-clay-dark">${item.expiry_date || '2027-12-31'}</strong></span>
        </div>
      </div>

      <!-- Segregated Stock Pill Metrics -->
      <div class="flex flex-wrap items-center gap-2">
        <div class="px-3 py-1.5 rounded-xl bg-emerald-50 border border-emerald-200 text-center min-w-[70px]" title="Available for immediate dispensing">
          <span class="text-[9px] uppercase font-black text-emerald-700 block">${t('available')}</span>
          <span class="text-sm font-black text-emerald-800 font-mono">${available}</span>
        </div>

        <div class="px-3 py-1.5 rounded-xl bg-slate-50 border border-slate-200 text-center min-w-[70px]" title="Physical on-hand stock in storage">
          <span class="text-[9px] uppercase font-bold text-slate-500 block">${t('onHand')}</span>
          <span class="text-sm font-black text-slate-700 font-mono">${onHand}</span>
        </div>

        <div class="px-3 py-1.5 rounded-xl ${reserved > 0 ? 'bg-amber-50 border border-amber-200 text-amber-800' : 'bg-slate-50/50 border border-slate-100 text-slate-400'} text-center min-w-[65px]" title="Reserved for approved transfers awaiting dispatch">
          <span class="text-[9px] uppercase font-bold block">${t('reserved')}</span>
          <span class="text-sm font-black font-mono">${reserved}</span>
        </div>

        <div class="px-3 py-1.5 rounded-xl ${quarantined > 0 ? 'bg-red-50 border border-red-200 text-red-800' : 'bg-slate-50/50 border border-slate-100 text-slate-400'} text-center min-w-[65px]" title="Quarantined damaged or expired units">
          <span class="text-[9px] uppercase font-bold block">${t('quarantined')}</span>
          <span class="text-sm font-black font-mono">${quarantined}</span>
        </div>

        ${inTransit > 0 ? `
          <div class="px-3 py-1.5 rounded-xl bg-cyan-50 border border-cyan-200 text-center min-w-[65px]" title="In transit en route to this facility">
            <span class="text-[9px] uppercase font-bold text-cyan-700 block">${t('inTransit')}</span>
            <span class="text-sm font-black text-cyan-800 font-mono">+${inTransit}</span>
          </div>
        ` : ''}

        ${isFrozen ? `
          <button onclick="openResolveReconciliationModal('${safeId(item.medicine_id)}', '${safeId(item.batch_number)}')" class="px-3 py-2 rounded-xl bg-red-600 hover:bg-red-700 text-white text-xs font-black shadow-sm transition flex items-center space-x-1 cursor-pointer" title="Resolve Over-Commitment Exception">
            <i data-lucide="shield-alert" class="w-3.5 h-3.5"></i>
            <span>${t('resolve')}</span>
          </button>
        ` : ''}

        <button onclick="openStockMovementRegister('${safeId(item.medicine_id)}', '${safeId(item.batch_number)}')" class="px-3 py-2 rounded-xl bg-white hover:bg-clay-inner text-clay-dark text-xs font-black border border-clay-salmon/25 shadow-sm transition flex items-center space-x-1 cursor-pointer" title="View Stock Movement Register & Handover Ledger">
          <i data-lucide="clipboard-list" class="w-3.5 h-3.5 text-clay-terracotta"></i>
          <span>${t('register')}</span>
        </button>

        <button onclick="openStockActionModal('${safeId(item.medicine_id)}', '${safeId(item.batch_number)}')" class="px-3.5 py-2 rounded-xl bg-clay-inner hover:bg-clay-bg text-clay-dark text-xs font-black border border-clay-salmon/30 shadow-sm transition flex items-center space-x-1 hover:scale-105 cursor-pointer" title="Record Physical Count or Stock Adjustment">
          <i data-lucide="edit" class="w-3.5 h-3.5 text-clay-terracotta"></i>
          <span>${t('update')}</span>
        </button>
      </div>
    `;
    container.appendChild(row);
  });
}

function renderClinicConsignments(inbound, outbound) {
  // Inbound List
  const inContainer = document.getElementById('clinicInboundList');
  const inBadge = document.getElementById('clinicInboundCountBadge');
  
  const activeInbound = inbound.filter(c => c.status === 'DISPATCHED' || c.status === 'APPROVED_RESERVED');
  if (inBadge) inBadge.textContent = t('incomingCount', { n: activeInbound.length });

  if (inContainer) {
    if (activeInbound.length === 0) {
      inContainer.innerHTML = `
        <div class="p-5 text-center text-clay-muted text-xs font-medium bg-white rounded-2xl border border-clay-salmon/15">
          ${t('noInbound')}
        </div>
      `;
    } else {
      inContainer.innerHTML = '';
      activeInbound.forEach(c => {
        const isDispatched = c.status === 'DISPATCHED';
        const card = document.createElement('div');
        card.className = "p-3.5 rounded-2xl bg-white border border-clay-salmon/20 shadow-sm space-y-2.5";
        card.innerHTML = `
          <div class="flex items-center justify-between">
            <span class="text-[10px] font-mono font-bold text-clay-muted">${escapeHtml(c.challan_id || c.id)}</span>
            <span class="text-[10px] font-black uppercase px-2 py-0.5 rounded-full ${isDispatched ? 'bg-cyan-100 text-cyan-800' : 'bg-slate-100 text-slate-700'}">
              ${isDispatched ? t('badgeInTransit') : t('badgePreparing')}
            </span>
          </div>
          <div>
            <h5 class="text-xs font-black text-clay-dark">${escapeHtml(c.medicine_name)} (${escapeHtml(isDispatched ? c.units_dispatched : c.units_requested)} ${t('Units')})</h5>
            <p class="text-[11px] text-clay-muted mt-0.5">${t('from')}: <strong class="text-clay-dark font-semibold">${escapeHtml(c.donor_facility_name)}</strong></p>
            <p class="text-[10px] font-mono text-clay-muted">${t('batch')}: ${escapeHtml(c.batch_number)} • ${t('vehicle')}: ${escapeHtml(c.vehicle_number || (isDispatched ? t('notRecorded') : t('notAssigned')))}</p>
          </div>
          ${isDispatched ? `
            <button onclick="openReceiptModal('${safeId(c.id)}')" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-black text-xs py-2 px-3 rounded-xl transition shadow-sm flex items-center justify-center space-x-1.5 cursor-pointer">
              <i data-lucide="package-check" class="w-3.5 h-3.5"></i>
              <span>${t('confirmReceipt')}</span>
            </button>
          ` : `
            <div class="text-[11px] text-clay-muted italic bg-clay-inner/60 p-2 rounded-lg text-center">
              ${t('awaitingCourier')}
            </div>
          `}
        `;
        inContainer.appendChild(card);
      });
    }
  }

  // Outbound List
  const outContainer = document.getElementById('clinicOutboundList');
  const outBadge = document.getElementById('clinicOutboundCountBadge');
  
  const activeOutbound = outbound.filter(c => c.status === 'APPROVED_RESERVED' || c.status === 'DISPATCHED');
  if (outBadge) outBadge.textContent = t('outgoingCount', { n: activeOutbound.length });

  if (outContainer) {
    if (activeOutbound.length === 0) {
      outContainer.innerHTML = `
        <div class="p-5 text-center text-clay-muted text-xs font-medium bg-white rounded-2xl border border-clay-salmon/15">
          ${t('noOutbound')}
        </div>
      `;
    } else {
      outContainer.innerHTML = '';
      activeOutbound.forEach(c => {
        const isApproved = c.status === 'APPROVED_RESERVED';
        const card = document.createElement('div');
        card.className = "p-3.5 rounded-2xl bg-white border border-clay-salmon/20 shadow-sm space-y-2.5";
        card.innerHTML = `
          <div class="flex items-center justify-between">
            <span class="text-[10px] font-mono font-bold text-clay-muted">${escapeHtml(c.challan_id || c.id)}</span>
            <span class="text-[10px] font-black uppercase px-2 py-0.5 rounded-full ${isApproved ? 'bg-amber-100 text-amber-800' : 'bg-cyan-100 text-cyan-800'}">
              ${isApproved ? t('badgeReserved') : t('badgeDispatched')}
            </span>
          </div>
          <div>
            <h5 class="text-xs font-black text-clay-dark">${escapeHtml(c.medicine_name)} (${escapeHtml(isApproved ? c.units_requested : c.units_dispatched)} ${t('Units')})</h5>
            <p class="text-[11px] text-clay-muted mt-0.5">${t('to')}: <strong class="text-clay-dark font-semibold">${escapeHtml(c.recipient_facility_name)}</strong></p>
            <p class="text-[10px] font-mono text-clay-muted">${t('batch')}: ${escapeHtml(c.batch_number)}</p>
          </div>
          ${isApproved ? `
            <div class="flex items-center space-x-2">
              <button onclick="openDispatchModal('${safeId(c.id)}')" class="flex-1 bg-amber-600 hover:bg-amber-700 text-white font-black text-xs py-2 px-3 rounded-xl transition shadow-sm flex items-center justify-center space-x-1 cursor-pointer">
                <i data-lucide="truck" class="w-3.5 h-3.5"></i>
                <span>${t('courierHandover')}</span>
              </button>
              <button onclick="cancelConsignmentAction('${safeId(c.id)}')" class="px-3 py-2 bg-clay-inner hover:bg-red-50 text-red-700 border border-clay-salmon/30 font-bold text-xs rounded-xl transition cursor-pointer" title="Cancel Consignment & Release Stock">
                <span>${t('cancel')}</span>
              </button>
            </div>
          ` : `
            <div class="flex items-center justify-between bg-clay-inner/60 p-2 rounded-lg text-[11px]">
              <span class="text-clay-muted">${t('vehicle')}: <strong class="text-clay-dark font-mono">${escapeHtml(c.vehicle_number || t('notRecorded'))}</strong></span>
              <button onclick="showChallanModal('${safeId(c.id)}')" class="text-clay-terracotta font-bold hover:underline cursor-pointer">${t('viewChallan')}</button>
            </div>
          `}
        `;
        outContainer.appendChild(card);
      });
    }
  }
}

// ------------------------------------------------------------------------------
// MODAL WORKFLOWS
// ------------------------------------------------------------------------------

function openStockActionModal(medicineId = null, batchNumber = null) {
  if (!activeClinicDeskData || !activeClinicDeskData.inventory || activeClinicDeskData.inventory.length === 0) {
    alert("No inventory records available for this facility.");
    return;
  }

  let item = null;
  if (medicineId) {
    item = activeClinicDeskData.inventory.find(i => 
      i.medicine_id === medicineId && (!batchNumber || i.batch_number === batchNumber)
    );
    if (!item) {
      item = activeClinicDeskData.inventory.find(i => i.medicine_id === medicineId);
    }
  }
  if (!item) {
    item = activeClinicDeskData.inventory[0];
  }

  currentStockActionMedicineId = item.medicine_id;
  currentStockActionBatchNumber = item.batch_number;

  const medNameEl = document.getElementById('modalMedName');
  if (medNameEl) medNameEl.textContent = `${item.medicine_name} (${item.category || 'Medicine'})`;

  const packEl = document.getElementById('modalPackSize');
  if (packEl) packEl.textContent = `Pack Size: ${item.pack_size || 10} units`;

  const batchEl = document.getElementById('modalBatchNum');
  if (batchEl) batchEl.textContent = item.batch_number || 'BAT-DEFAULT';

  const expEl = document.getElementById('modalExpiryDate');
  if (expEl) expEl.textContent = item.expiry_date || '2027-12-31';

  setStockActionType('PHYSICAL_COUNT');

  const qtyInput = document.getElementById('stockActionQtyInput');
  if (qtyInput) qtyInput.value = item.on_hand != null ? item.on_hand : (item.current_stock || 0);

  const reasonInput = document.getElementById('stockActionReasonInput');
  if (reasonInput) reasonInput.value = '';

  updateStockActionPreview();

  const modal = document.getElementById('stockActionModal');
  if (modal) modal.classList.remove('hidden');
}

function closeStockActionModal() {
  const el = document.getElementById('stockActionModal');
  if (el) el.classList.add('hidden');
}

function setStockActionType(type) {
  selectedStockActionType = type;
  const btnCount = document.getElementById('btnActCount');
  const btnReceive = document.getElementById('btnActReceive');
  const btnIssue = document.getElementById('btnActIssue');
  const btnQuarantine = document.getElementById('btnActQuarantine');
  const label = document.getElementById('stockActionQtyLabel');

  const activeClass = 'p-3 rounded-xl border-2 border-clay-terracotta bg-clay-salmon/10 font-bold text-xs text-clay-dark text-left transition flex flex-col justify-between cursor-pointer';
  const inactiveClass = 'p-3 rounded-xl border border-clay-salmon/20 bg-white font-bold text-xs text-clay-dark text-left transition flex flex-col justify-between hover:bg-clay-inner cursor-pointer';

  if (btnCount) btnCount.className = (type === 'PHYSICAL_COUNT') ? activeClass : inactiveClass;
  if (btnReceive) btnReceive.className = (type === 'STOCK_RECEIVED') ? activeClass : inactiveClass;
  if (btnIssue) btnIssue.className = (type === 'STOCK_ISSUED') ? activeClass : inactiveClass;
  if (btnQuarantine) btnQuarantine.className = (type === 'QUARANTINE_DAMAGED') ? activeClass : inactiveClass;

  if (label) {
    if (type === 'PHYSICAL_COUNT') label.textContent = 'Counted Units on Shelf';
    else if (type === 'STOCK_RECEIVED') label.textContent = 'Units Received from Supplier / Depot';
    else if (type === 'STOCK_ISSUED') label.textContent = 'Units Dispensed / Issued to Ward';
    else if (type === 'QUARANTINE_DAMAGED') label.textContent = 'Units Damaged / Contaminated to Quarantine';
  }

  updateStockActionPreview();
}

function updateStockActionPreview() {
  if (!activeClinicDeskData || !activeClinicDeskData.inventory) return;
  const item = activeClinicDeskData.inventory.find(i => 
    i.medicine_id === currentStockActionMedicineId && 
    (!currentStockActionBatchNumber || i.batch_number === currentStockActionBatchNumber)
  );
  if (!item) return;

  const prevOnHand = item.on_hand != null ? item.on_hand : (item.current_stock || 0);
  const prevReserved = item.reserved || 0;
  const prevQuarantined = item.quarantined || 0;
  const prevAvail = Math.max(0, prevOnHand - prevReserved - prevQuarantined);

  const inputVal = parseInt(document.getElementById('stockActionQtyInput').value);
  const qty = isNaN(inputVal) ? 0 : Math.max(0, inputVal);

  let newOnHand = prevOnHand;
  let newReserved = prevReserved;
  let newQuarantined = prevQuarantined;
  let newAvail = prevAvail;
  let reconWarning = false;

  if (selectedStockActionType === 'PHYSICAL_COUNT') {
    newOnHand = qty;
    newReserved = prevReserved;
    newQuarantined = prevQuarantined;
    newAvail = Math.max(0, newOnHand - newReserved - newQuarantined);
    if (newOnHand < prevReserved + prevQuarantined) {
      reconWarning = true;
    }
  } else if (selectedStockActionType === 'STOCK_RECEIVED') {
    newOnHand = prevOnHand + qty;
    newReserved = prevReserved;
    newQuarantined = prevQuarantined;
    newAvail = Math.max(0, newOnHand - newReserved - newQuarantined);
  } else if (selectedStockActionType === 'STOCK_ISSUED') {
    newOnHand = Math.max(0, prevOnHand - qty);
    newReserved = prevReserved;
    newQuarantined = prevQuarantined;
    newAvail = Math.max(0, newOnHand - newReserved - newQuarantined);
  } else if (selectedStockActionType === 'QUARANTINE_DAMAGED') {
    newOnHand = prevOnHand;
    newQuarantined = prevQuarantined + qty;
    newReserved = prevReserved;
    newAvail = Math.max(0, newOnHand - newReserved - newQuarantined);
  }

  const elPrevOh = document.getElementById('prevOnHand');
  const elNewOh = document.getElementById('newOnHand');
  const elPrevAv = document.getElementById('prevAvailable');
  const elNewAv = document.getElementById('newAvailable');
  const elPrevRes = document.getElementById('prevReserved');
  const elNewRes = document.getElementById('newReserved');
  const elPrevQua = document.getElementById('prevQuarantined');
  const elNewQua = document.getElementById('newQuarantined');

  if (elPrevOh) elPrevOh.textContent = prevOnHand;
  if (elNewOh) elNewOh.textContent = newOnHand;
  if (elPrevAv) elPrevAv.textContent = prevAvail;
  if (elNewAv) elNewAv.textContent = newAvail;
  if (elPrevRes) elPrevRes.textContent = prevReserved;
  if (elNewRes) elNewRes.textContent = newReserved;
  if (elPrevQua) elPrevQua.textContent = prevQuarantined;
  if (elNewQua) elNewQua.textContent = newQuarantined;

  const warnEl = document.getElementById('reconciliationWarningNotice');
  if (warnEl) {
    if (reconWarning) {
      warnEl.classList.remove('hidden');
      warnEl.textContent = `⚠️ Warning: Physical count (${newOnHand}) is below active commitments (${prevReserved} reserved + ${prevQuarantined} quarantined). Committing will trigger a Reconciliation Exception and freeze dispatches until audited.`;
    } else {
      warnEl.classList.add('hidden');
    }
  }
}

async function submitStockAction() {
  const btn = document.getElementById('btnSubmitStockAction');
  if (!currentStockActionMedicineId) {
    alert("Please select a medicine first.");
    return;
  }
  const inputVal = parseInt(document.getElementById('stockActionQtyInput').value);
  if (isNaN(inputVal) || inputVal < 0) {
    alert("Please enter a valid non-negative quantity.");
    return;
  }
  const reason = document.getElementById('stockActionReasonInput').value.trim() || 
    (selectedStockActionType === 'PHYSICAL_COUNT' ? 'Morning shelf routine verification' :
     selectedStockActionType === 'STOCK_RECEIVED' ? 'Receipt of central warehouse batch' :
     selectedStockActionType === 'STOCK_ISSUED' ? 'Dispensed for acute respiratory ward' : 'Damaged / expired ampoules quarantined');

  const origBtnText = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="animate-spin mr-1">⏳</span> Committing...`;
  }

  try {
    const payload = {
      facility_id: currentClinicFacilityId,
      medicine_id: currentStockActionMedicineId,
      batch_number: currentStockActionBatchNumber,
      action_type: selectedStockActionType,
      quantity: inputVal,
      reason: reason,
      operator_name: "Demo Pharmacist",
      operator_role: "PHARMACIST"
    };

    const res = await fetch(`/api/clinic/${currentClinicFacilityId}/stock-action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (res.ok) {
      closeStockActionModal();
      await loadClinicDesk(currentClinicFacilityId);
      await fetchRisks();
      await fetchRecommendations();
      await fetchAuditLog();
      
      let msg = `${data.success === false ? '⚠️' : '✅'} Action Recorded: ${data.message}`;
      if (data.reconciliation_exception) {
        msg += "\n⚠️ RECONCILIATION EXCEPTION: Dispatches for this batch have been FROZEN until supervisor audit.";
      }
      alert(msg);
    } else {
      alert("Stock Action Failed: " + (data.detail || "Server error"));
    }
  } catch (err) {
    console.error("submitStockAction error:", err);
    alert("Network error while submitting stock action.");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origBtnText;
    }
  }
}

function openReceiptModal(consignmentId) {
  let c = null;
  if (activeClinicDeskData && activeClinicDeskData.inbound_consignments) {
    c = activeClinicDeskData.inbound_consignments.find(item => item.id === consignmentId);
  }
  if (!c && activeRecs) {
    const rec = activeRecs.find(r => r.id === consignmentId);
    if (rec) {
      c = {
        id: rec.id,
        challan_id: rec.id,
        medicine_name: rec.medicine_name,
        donor_facility_name: rec.donor_facility_name,
        batch_number: rec.batch_number,
        units_requested: rec.units_to_transfer,
        units_dispatched: rec.units_to_transfer
      };
    }
  }
  if (!c) {
    alert("Consignment record not found: " + consignmentId);
    return;
  }

  currentReceiptConsignment = c;
  const dispatched = c.units_dispatched != null ? c.units_dispatched : (c.units_requested || 0);

  const challanEl = document.getElementById('receiptModalChallan');
  const medEl = document.getElementById('receiptMedName');
  const dispEl = document.getElementById('receiptDispatchedQty');
  const donorEl = document.getElementById('receiptDonorName');
  const batchEl = document.getElementById('receiptBatchNum');

  if (challanEl) challanEl.textContent = c.challan_id || c.id;
  if (medEl) medEl.textContent = c.medicine_name;
  if (dispEl) dispEl.textContent = dispatched;
  if (donorEl) donorEl.textContent = c.donor_facility_name;
  if (batchEl) batchEl.textContent = c.batch_number;

  const accInput = document.getElementById('receiptAcceptedInput');
  const quaInput = document.getElementById('receiptQuarantinedInput');
  const misInput = document.getElementById('receiptMissingInput');
  const notesInput = document.getElementById('receiptConditionNotes');

  if (accInput) accInput.value = dispatched;
  if (quaInput) quaInput.value = 0;
  if (misInput) misInput.value = 0;
  if (notesInput) notesInput.value = '';

  updateReceiptMath();

  const modal = document.getElementById('receiptInspectionModal');
  if (modal) modal.classList.remove('hidden');
}

function closeReceiptModal() {
  const el = document.getElementById('receiptInspectionModal');
  if (el) el.classList.add('hidden');
}

function updateReceiptMath() {
  if (!currentReceiptConsignment) return;
  const dispatched = currentReceiptConsignment.units_dispatched != null ? 
    currentReceiptConsignment.units_dispatched : (currentReceiptConsignment.units_requested || 0);

  const acc = parseInt(document.getElementById('receiptAcceptedInput').value) || 0;
  const qua = parseInt(document.getElementById('receiptQuarantinedInput').value) || 0;
  const mis = parseInt(document.getElementById('receiptMissingInput').value) || 0;
  const total = acc + qua + mis;

  const alertEl = document.getElementById('receiptMathAlert');
  const indEl = document.getElementById('receiptEqualityIndicator');
  const btn = document.getElementById('btnSubmitReceipt');

  if (total === dispatched) {
    if (alertEl) alertEl.classList.add('hidden');
    if (indEl) {
      indEl.className = 'text-xs font-bold text-emerald-700 font-mono';
      indEl.textContent = `✓ Balanced: ${acc} accepted + ${qua} quarantined + ${mis} missing == ${dispatched} dispatched`;
    }
    if (btn) btn.disabled = false;
  } else {
    if (alertEl) {
      alertEl.classList.remove('hidden');
      alertEl.textContent = `Physical sum (${total}) does not equal dispatched count (${dispatched}). Discrepancy: ${Math.abs(dispatched - total)} units ${total > dispatched ? 'excess' : 'shortage'}. All units must be accounted for.`;
    }
    if (indEl) {
      indEl.className = 'text-xs font-bold text-red-700 font-mono';
      indEl.textContent = `✗ Unbalanced: ${total} / ${dispatched} dispatched`;
    }
    if (btn) btn.disabled = true;
  }
}

async function submitReceiptInspection() {
  if (!currentReceiptConsignment) return;
  const dispatched = currentReceiptConsignment.units_dispatched != null ? 
    currentReceiptConsignment.units_dispatched : (currentReceiptConsignment.units_requested || 0);

  const acc = parseInt(document.getElementById('receiptAcceptedInput').value) || 0;
  const qua = parseInt(document.getElementById('receiptQuarantinedInput').value) || 0;
  const mis = parseInt(document.getElementById('receiptMissingInput').value) || 0;

  if (acc + qua + mis !== dispatched) {
    alert(`Cannot commit: All dispatched units must be accounted for.\nDispatched: ${dispatched}\nAccounted: ${acc + qua + mis}`);
    return;
  }

  const btn = document.getElementById('btnSubmitReceipt');
  const origText = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="animate-spin mr-1">⏳</span> Receiving...`;
  }

  try {
    const payload = {
      consignment_id: currentReceiptConsignment.id,
      operator_name: "Demo Pharmacist",
      operator_role: "PHARMACIST",
      accepted_units: acc,
      quarantined_units: qua,
      missing_units: mis,
      condition_intact: qua === 0 && mis === 0,
      discrepancy_notes: document.getElementById('receiptConditionNotes').value.trim() || null
    };

    const res = await fetch('/api/transfer/receive', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (res.ok) {
      closeReceiptModal();
      await loadClinicDesk(currentClinicFacilityId);
      await fetchRisks();
      await fetchRecommendations();
      await fetchAuditLog();
      alert(`✅ Receipt Confirmed! Accepted ${acc} units credited to active shelf stock. Consignment status: ${data.status}`);
    } else {
      alert("Receipt Confirmation Failed: " + (data.detail || "Server error"));
    }
  } catch (err) {
    console.error("submitReceiptInspection error:", err);
    alert("Network error while confirming receipt.");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origText;
    }
  }
}

function openDispatchModal(consignmentId) {
  let c = null;
  if (activeClinicDeskData && activeClinicDeskData.outbound_consignments) {
    c = activeClinicDeskData.outbound_consignments.find(item => item.id === consignmentId);
  }
  if (!c) {
    alert("Consignment record not found: " + consignmentId);
    return;
  }

  currentDispatchConsignment = c;
  const challanEl = document.getElementById('dispatchModalChallan');
  const medEl = document.getElementById('dispatchMedName');
  const unitsEl = document.getElementById('dispatchUnits');
  const recEl = document.getElementById('dispatchRecipientName');
  const batchEl = document.getElementById('dispatchBatchNum');
  const vehInput = document.getElementById('dispatchVehicleInput');
  const notesInput = document.getElementById('dispatchNotesInput');

  if (challanEl) challanEl.textContent = c.challan_id || c.id;
  if (medEl) medEl.textContent = c.medicine_name;
  if (unitsEl) unitsEl.textContent = c.units_requested;
  if (recEl) recEl.textContent = c.recipient_facility_name;
  if (batchEl) batchEl.textContent = c.batch_number;
  if (vehInput) {
    vehInput.value = c.vehicle_number || '';
    vehInput.placeholder = regionForFacility(c.donor_facility_id) === 'bhubaneswar' ? 'e.g. OD-02-AB-1234' : 'e.g. UP-32-AB-1234';
  }
  if (notesInput) notesInput.value = '';

  const modal = document.getElementById('dispatchConsignmentModal');
  if (modal) modal.classList.remove('hidden');
}

function closeDispatchModal() {
  const el = document.getElementById('dispatchConsignmentModal');
  if (el) el.classList.add('hidden');
}

async function submitDispatchConsignment() {
  if (!currentDispatchConsignment) return;
  const btn = document.querySelector('#dispatchConsignmentModal button[onclick="submitDispatchConsignment()"]');
  const origText = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="animate-spin mr-1">⏳</span> Dispatching...`;
  }

  try {
    const payload = {
      consignment_id: currentDispatchConsignment.id,
      operator_name: "Demo Pharmacist",
      operator_role: "PHARMACIST",
      vehicle_number: document.getElementById('dispatchVehicleInput').value.trim() || null,
      courier_notes: document.getElementById('dispatchNotesInput').value.trim() || "Insulated cold-box handover verified"
    };

    const res = await fetch('/api/transfer/dispatch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      const data = await res.json();
      closeDispatchModal();
      await loadClinicDesk(currentClinicFacilityId);
      await fetchRisks();
      await fetchRecommendations();
      await fetchAuditLog();
      alert(`✅ Outbound consignment dispatched. On-hand stock deducted${payload.vehicle_number ? `, vehicle ${payload.vehicle_number}` : ''}.`);
      showChallanModal(data.id, { consignment: data });
    } else {
      alert("Dispatch Handover Failed: " + await apiErrorMessage(res, "Server error"));
    }
  } catch (err) {
    console.error("submitDispatchConsignment error:", err);
    alert("Network error while submitting dispatch.");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origText;
    }
  }
}

async function cancelConsignmentAction(consignmentId) {
  if (!confirm("Are you sure you want to cancel this transfer order? The reserved stock will be immediately released back to available shelf inventory.")) {
    return;
  }

  try {
    const payload = {
      consignment_id: consignmentId,
      operator_name: "Dr. Authorized MOIC",
      operator_role: "MOIC",
      reason: "Cancelled by facility MOIC prior to physical dispatch"
    };

    const res = await fetch('/api/transfer/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (res.ok) {
      await loadClinicDesk(currentClinicFacilityId);
      await fetchRisks();
      await fetchRecommendations();
      await fetchAuditLog();
      alert("Transfer consignment cancelled. Reserved units have been restored to available stock.");
    } else {
      alert("Cancellation failed: " + (data.detail || "Server error"));
    }
  } catch (err) {
    console.error("cancelConsignmentAction error:", err);
    alert("Network error while cancelling consignment.");
  }
}

async function openClinicDeskForVoiceDraft(facilityId, medicineId, reportedQty) {
  // The desk only lists the current region's facilities, so move to the facility's region first
  const facRegion = facilityId ? regionForFacility(facilityId) : currentRegion;
  if (facRegion !== currentRegion) {
    await switchRegion(facRegion);
    if (currentRegion !== facRegion) return;  // switch failed and was reported
  }
  if (facilityId) currentClinicFacilityId = facilityId;
  switchMainView('clinic', false);
  await loadClinicDesk(currentClinicFacilityId);
  if (!activeClinicDeskData || (facilityId && activeClinicDeskData.facility && activeClinicDeskData.facility.id !== facilityId)) {
    alert('Could not load the Clinic Desk for this facility.');
    return;
  }
  openStockActionModal(medicineId);
  if (reportedQty != null) {
    const input = document.getElementById('stockActionQtyInput');
    if (input) input.value = reportedQty;
    const reason = document.getElementById('stockActionReasonInput');
    if (reason) reason.value = "Confirmed frontline voice log report";
    updateStockActionPreview();
  }
}

// ==============================================================================
// RECONCILIATION EXCEPTION & OVER-COMMITMENT RESOLUTION
// ==============================================================================
let currentReconMedicineId = null;
let currentReconBatchNumber = null;
let selectedReconResolutionType = "SUPERVISOR_RECOUNT";

function openResolveReconciliationModal(medicineId, batchNumber) {
  if (!activeClinicDeskData) return;
  const item = (activeClinicDeskData.inventory || []).find(i => 
    i.medicine_id === medicineId && (!batchNumber || i.batch_number === batchNumber)
  );
  if (!item) {
    alert("Item not found for reconciliation resolution.");
    return;
  }

  currentReconMedicineId = item.medicine_id;
  currentReconBatchNumber = item.batch_number || "BAT-DEFAULT";

  const onHand = item.on_hand != null ? item.on_hand : (item.current_stock || 0);
  const reserved = item.reserved || 0;
  const quarantined = item.quarantined || 0;
  const rawAvail = onHand - reserved - quarantined;
  const deficit = rawAvail < 0 ? Math.abs(rawAvail) : (item.reconciliation_deficit || 0);

  const medNameEl = document.getElementById('reconModalMedName');
  const defBadgeEl = document.getElementById('reconModalDeficitBadge');
  const onHandEl = document.getElementById('reconModalOnHand');
  const resEl = document.getElementById('reconModalReserved');
  const quarEl = document.getElementById('reconModalQuarantined');
  const netEl = document.getElementById('reconModalNetBalance');
  const freezeExpEl = document.getElementById('reconModalFreezeExplanation');
  const minCountEl = document.getElementById('reconMinRequiredCount');
  const verifiedCountInput = document.getElementById('reconVerifiedCountInput');
  const quarInput = document.getElementById('reconQuarantineInput');
  const notesInput = document.getElementById('reconNotesInput');

  if (medNameEl) medNameEl.textContent = `${item.medicine_name} (${currentReconBatchNumber})`;
  if (defBadgeEl) defBadgeEl.textContent = `Deficit: ${deficit} units`;
  if (onHandEl) onHandEl.textContent = onHand;
  if (resEl) resEl.textContent = reserved;
  if (quarEl) quarEl.textContent = quarantined;
  if (netEl) netEl.textContent = rawAvail;

  const explanation = item.freeze_reason || `Physical shelf count (${onHand}) is below active commitments (${reserved} reserved + ${quarantined} quarantined). Deficit: ${deficit} units.`;
  if (freezeExpEl) freezeExpEl.textContent = `${explanation} Stock issues and outbound dispatches remain frozen until resolved.`;

  if (minCountEl) minCountEl.textContent = reserved + quarantined;
  if (verifiedCountInput) verifiedCountInput.value = reserved + quarantined;
  if (quarInput) quarInput.value = Math.max(0, quarantined - deficit);
  if (notesInput) notesInput.value = '';

  // Populate affected consignments if any
  const consList = document.getElementById('reconConsignmentsList');
  if (consList) {
    consList.innerHTML = '';
    const outbound = (activeClinicDeskData.outbound_consignments || []).filter(c => 
      c.medicine_id === medicineId && c.status === 'APPROVED_RESERVED'
    );
    if (outbound.length === 0) {
      consList.innerHTML = '<p class="text-xs text-clay-muted font-medium p-2">No active approved consignments reserved for this medicine.</p>';
    } else {
      outbound.forEach(c => {
        const div = document.createElement('div');
        div.className = "flex items-center space-x-2 bg-white p-2.5 rounded-xl border border-clay-salmon/20 text-xs";
        div.innerHTML = `
          <input type="checkbox" name="reconConsignment" value="${escapeHtml(c.id)}" id="recon_c_${safeId(c.id)}" class="rounded text-red-600 focus:ring-red-500 cursor-pointer">
          <label for="recon_c_${safeId(c.id)}" class="flex-1 font-mono text-[11px] cursor-pointer">
            <strong>${escapeHtml(c.challan_id || c.id)}</strong> &bull; ${escapeHtml(c.units_requested)} units &bull; Destination: ${escapeHtml(c.recipient_facility_name)}
          </label>
        `;
        consList.appendChild(div);
      });
    }
  }

  setReconResolutionType("SUPERVISOR_RECOUNT");
  const modal = document.getElementById('resolveReconciliationModal');
  if (modal) modal.classList.remove('hidden');
}

function closeResolveReconciliationModal() {
  const modal = document.getElementById('resolveReconciliationModal');
  if (modal) modal.classList.add('hidden');
}

function setReconResolutionType(type) {
  selectedReconResolutionType = type;
  const btnRecount = document.getElementById('btnReconRecount');
  const btnCancel = document.getElementById('btnReconCancel');
  const btnQuar = document.getElementById('btnReconQuarantine');

  const secRecount = document.getElementById('reconRecountSection');
  const secCancel = document.getElementById('reconCancelSection');
  const secQuar = document.getElementById('reconQuarantineSection');

  // Reset classes
  [btnRecount, btnCancel, btnQuar].forEach(b => {
    if (b) {
      b.className = "p-3 rounded-xl border border-clay-salmon/20 bg-white font-bold text-xs text-clay-dark text-left transition flex flex-col justify-between hover:bg-clay-inner cursor-pointer";
    }
  });

  if (secRecount) secRecount.classList.add('hidden');
  if (secCancel) secCancel.classList.add('hidden');
  if (secQuar) secQuar.classList.add('hidden');

  if (type === 'SUPERVISOR_RECOUNT') {
    if (btnRecount) btnRecount.className = "p-3 rounded-xl border-2 border-clay-terracotta bg-clay-salmon/10 font-bold text-xs text-clay-dark text-left transition flex flex-col justify-between cursor-pointer";
    if (secRecount) secRecount.classList.remove('hidden');
  } else if (type === 'CANCEL_RESERVATIONS') {
    if (btnCancel) btnCancel.className = "p-3 rounded-xl border-2 border-amber-600 bg-amber-50 font-bold text-xs text-clay-dark text-left transition flex flex-col justify-between cursor-pointer";
    if (secCancel) secCancel.classList.remove('hidden');
  } else if (type === 'ADJUST_QUARANTINE') {
    if (btnQuar) btnQuar.className = "p-3 rounded-xl border-2 border-slate-700 bg-slate-100 font-bold text-xs text-clay-dark text-left transition flex flex-col justify-between cursor-pointer";
    if (secQuar) secQuar.classList.remove('hidden');
  }
}

async function submitResolveReconciliation() {
  const notes = (document.getElementById('reconNotesInput').value || '').trim();
  if (!notes) {
    alert("Please provide supervisor audit justification notes before unfreezing.");
    return;
  }

  const payload = {
    facility_id: currentClinicFacilityId,
    medicine_id: currentReconMedicineId,
    batch_number: currentReconBatchNumber,
    resolution_type: selectedReconResolutionType,
    supervisor_name: "Demo MOIC (Supervisor)",
    supervisor_role: "MOIC",
    resolution_notes: notes
  };

  if (selectedReconResolutionType === 'SUPERVISOR_RECOUNT') {
    const verified = parseInt(document.getElementById('reconVerifiedCountInput').value);
    if (isNaN(verified) || verified < 0) {
      alert("Please enter a valid verified physical count.");
      return;
    }
    payload.verified_physical_count = verified;
  } else if (selectedReconResolutionType === 'CANCEL_RESERVATIONS') {
    const checked = Array.from(document.querySelectorAll('input[name="reconConsignment"]:checked')).map(cb => cb.value);
    if (checked.length === 0) {
      alert("Please select at least one consignment to cancel.");
      return;
    }
    payload.cancelled_consignment_ids = checked;
  } else if (selectedReconResolutionType === 'ADJUST_QUARANTINE') {
    const quar = parseInt(document.getElementById('reconQuarantineInput').value);
    if (isNaN(quar) || quar < 0) {
      alert("Please enter a valid quarantine adjustment.");
      return;
    }
    payload.quarantine_adjustment = quar;
  }

  const btn = document.getElementById('btnSubmitRecon');
  let origText = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = 'Resolving...';
  }

  try {
    const res = await fetch(`/api/clinic/${currentClinicFacilityId}/resolve-reconciliation`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (res.ok) {
      closeResolveReconciliationModal();
      await loadClinicDesk(currentClinicFacilityId);
      await fetchRisks();
      await fetchRecommendations();
      await fetchAuditLog();
      alert(`${data.success ? '✅' : '⚠️'} Reconciliation Update: ${data.message}`);
    } else {
      alert("Reconciliation Resolution Failed: " + (data.detail || "Server error"));
    }
  } catch (err) {
    console.error("submitResolveReconciliation error:", err);
    alert("Network error while resolving reconciliation exception.");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origText;
    }
  }
}

// ==============================================================================
// STOCK MOVEMENT REGISTER (HANDOVER & DISCREPANCY LEDGER)
// ==============================================================================
async function openStockMovementRegister(medicineId, batchNumber) {
  try {
    let url = `/api/clinic/${currentClinicFacilityId}/stock-register?medicine_id=${encodeURIComponent(medicineId)}`;
    if (batchNumber) url += `&batch_number=${encodeURIComponent(batchNumber)}`;

    const res = await fetch(url);
    if (!res.ok) {
      const err = await res.json();
      alert("Failed to load stock register: " + (err.detail || res.statusText));
      return;
    }
    const reg = await res.json();

    document.getElementById('registerFacilityName').textContent = reg.facility_name || reg.facility_id;
    document.getElementById('registerMedicineName').textContent = reg.medicine_name || reg.medicine_id;
    document.getElementById('registerBatchNumber').textContent = reg.batch_number;
    document.getElementById('registerOpeningOnHand').textContent = reg.opening_on_hand;
    document.getElementById('registerOpeningAvailable').textContent = reg.opening_available;
    document.getElementById('registerClosingOnHand').textContent = reg.closing_on_hand;
    document.getElementById('registerClosingAvailable').textContent = reg.closing_available;
    document.getElementById('registerClosingReserved').textContent = reg.closing_reserved;
    document.getElementById('registerClosingQuarantined').textContent = reg.closing_quarantined;
    document.getElementById('registerGeneratedAt').textContent = reg.generated_at;

    const tbody = document.getElementById('registerMovementsTbody');
    tbody.innerHTML = '';

    if (!reg.movements || reg.movements.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="9" class="p-6 text-center text-clay-muted font-medium">
            No movements recorded yet for this batch. Balance opened at ${reg.opening_on_hand} units.
          </td>
        </tr>
      `;
    } else {
      reg.movements.forEach(m => {
        const tr = document.createElement('tr');
        tr.className = "hover:bg-slate-50/80 transition font-mono text-[11px]";

        let deltaPClass = m.delta_physical > 0 ? 'text-emerald-700 font-bold' : (m.delta_physical < 0 ? 'text-red-700 font-bold' : 'text-slate-400');
        let deltaAClass = m.delta_available > 0 ? 'text-emerald-700 font-bold' : (m.delta_available < 0 ? 'text-red-700 font-bold' : 'text-slate-400');
        let deltaPText = m.delta_physical > 0 ? `+${m.delta_physical}` : `${m.delta_physical}`;
        let deltaAText = m.delta_available > 0 ? `+${m.delta_available}` : `${m.delta_available}`;

        tr.innerHTML = `
          <td class="p-2.5 font-bold text-slate-500">${m.index}</td>
          <td class="p-2.5 whitespace-nowrap text-slate-600">${m.timestamp.substring(11, 19) || m.timestamp}</td>
          <td class="p-2.5 font-sans font-extrabold text-clay-dark">${escapeHtml(m.movement_type)}</td>
          <td class="p-2.5 text-right ${deltaPClass}">${deltaPText}</td>
          <td class="p-2.5 text-right ${deltaAClass}">${deltaAText}</td>
          <td class="p-2.5 text-center whitespace-nowrap">
            <span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-800 font-bold">${m.resulting_on_hand} OH</span>
            <span class="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 font-bold">${m.resulting_available} Avail</span>
            ${m.resulting_reserved > 0 ? `<span class="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 font-bold">${m.resulting_reserved} Res</span>` : ''}
            ${m.resulting_quarantined > 0 ? `<span class="px-1.5 py-0.5 rounded bg-red-100 text-red-800 font-bold">${m.resulting_quarantined} Quar</span>` : ''}
          </td>
          <td class="p-2.5 font-sans whitespace-nowrap"><strong>${escapeHtml(m.operator_name)}</strong> <span class="text-clay-muted text-[10px]">(${escapeHtml(m.operator_role)})</span></td>
          <td class="p-2.5 font-sans text-clay-muted max-w-xs truncate" title="${escapeHtml(m.reason || '')}">${escapeHtml(m.reason || '—')}</td>
          <td class="p-2.5 text-clay-muted text-[10px] truncate max-w-[90px]" title="${escapeHtml(m.audit_hash)}">${escapeHtml(String(m.audit_hash || "").substring(0, 8))}...</td>
        `;
        tbody.appendChild(tr);
      });
    }

    const modal = document.getElementById('stockMovementRegisterModal');
    if (modal) modal.classList.remove('hidden');
    if (window.lucide) lucide.createIcons();
  } catch (err) {
    console.error("openStockMovementRegister error:", err);
    alert("Network error while loading stock register.");
  }
}

function closeStockMovementRegister() {
  const modal = document.getElementById('stockMovementRegisterModal');
  if (modal) modal.classList.add('hidden');
}

// ==========================================
// Regional Health & Climate News Bureau
// ==========================================
async function fetchNews(region = null, forceRefresh = false) {
  const reg = region || currentRegion;
  try {
    const url = `/api/news?region=${encodeURIComponent(reg)}${forceRefresh ? '&force_refresh=true' : ''}`;
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    allNewsArticles = data.articles || [];

    // Update live news ticker with top headline
    const ticker = document.getElementById('liveNewsTicker');
    if (ticker && allNewsArticles.length > 0) {
      const top = allNewsArticles[0];
      const prefix = top.severity === 'critical' ? '🔴' : (top.severity === 'warning' ? '🟡' : '🟢');
      ticker.innerHTML = `${prefix} <span class="font-extrabold text-clay-terracotta">[${escapeHtml(top.source)}]:</span> <span>${escapeHtml(top.title)}</span> &bull; <span class="text-xs font-normal text-clay-muted">(${escapeHtml(top.published_at)})</span>`;
    }

    // Update region badge in news modal
    const badge = document.getElementById('newsRegionBadge');
    if (badge) {
      badge.textContent = (reg === 'bhubaneswar' ? 'Bhubaneswar–Cuttack (OD)' : 'Lucknow–Unnao (UP)');
    }

    renderNewsList();
  } catch (err) {
    console.error("fetchNews error:", err);
  }
}

async function refreshLiveNews() {
  const btn = document.getElementById('btnRefreshNews');
  if (btn) btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Fetching Live Wire...</span>`;
  if (window.lucide) lucide.createIcons();
  await fetchNews(currentRegion, true);
  if (btn) btn.innerHTML = `<i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i><span>Refresh Live Wire</span>`;
  if (window.lucide) lucide.createIcons();
}

function renderNewsList() {
  const container = document.getElementById('newsArticlesList');
  if (!container) return;

  const q = (activeNewsSearch || '').toLowerCase().trim();
  const cat = activeNewsCategory;

  let filtered = allNewsArticles.filter(item => {
    if (cat !== 'all' && item.category.toLowerCase() !== cat.toLowerCase()) return false;
    if (q) {
      const haystack = `${item.title} ${item.summary} ${item.source} ${item.district} ${(item.related_medicines || []).join(' ')}`.toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="text-center py-10 bg-clay-inner rounded-3xl border border-clay-salmon/20 p-6 space-y-2">
        <p class="text-clay-dark font-extrabold text-base">No news dispatches found</p>
        <p class="text-clay-muted text-xs">Try clearing the search filter or selecting 'All Dispatches'</p>
      </div>
    `;
    return;
  }

  container.innerHTML = '';

  const catEmojiMap = {
    'climate': '☀️ Climate & Heatwave',
    'air_quality': '🌫️ Air Quality & Inversion',
    'epidemic': '🦠 Epidemic Alert',
    'supply_chain': '💊 Medical Supply Chain',
    'clinical': '📋 Clinical Guideline'
  };

  const severityBadgeMap = {
    'critical': '<span class="bg-red-100 text-red-700 border border-red-200 text-[10px] font-black px-2.5 py-0.5 rounded-full uppercase tracking-wider">🚨 Critical Emergency</span>',
    'warning': '<span class="bg-amber-100 text-amber-800 border border-amber-200 text-[10px] font-black px-2.5 py-0.5 rounded-full uppercase tracking-wider">⚠️ Surveillance Alert</span>',
    'info': '<span class="bg-emerald-100 text-emerald-800 border border-emerald-200 text-[10px] font-black px-2.5 py-0.5 rounded-full uppercase tracking-wider">ℹ️ Official Notice</span>'
  };

  filtered.forEach(art => {
    const card = document.createElement('div');
    card.className = 'bg-white rounded-3xl p-4 sm:p-5 border border-clay-salmon/20 shadow-sm hover:shadow-md transition space-y-3';

    // Build medicine badges
    const medBadges = (art.related_medicines || []).map(mid => {
      const medName = MEDICINE_SHORT_NAMES[mid] || mid;
      return `<button onclick="filterMedicine('${safeId(mid)}'); closeNewsModal();" class="text-[11px] bg-clay-inner hover:bg-clay-bg text-clay-terracotta border border-clay-salmon/30 font-bold px-2.5 py-0.5 rounded-full transition cursor-pointer" title="Filter dashboard for ${escapeHtml(medName)}">${escapeHtml(mid)} &bull; ${escapeHtml(medName)}</button>`;
    }).join(' ');

    const catLabel = catEmojiMap[art.category] || '📰 General Health';
    const safeUrl = /^https?:\/\//i.test(art.url || '') ? art.url : null;
    const sevBadge = severityBadgeMap[art.severity] || severityBadgeMap['info'];
    const liveWireBadge = art.is_live ? `<span class="bg-emerald-50 text-emerald-700 border border-emerald-300/60 text-[10px] font-black px-2 py-0.5 rounded-full flex items-center space-x-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-ping"></span><span>Live Wire</span></span>` : '';

    card.innerHTML = `
      <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-2.5">
        <div class="flex items-center space-x-2">
          ${sevBadge}
          ${liveWireBadge}
          <span class="text-xs font-bold text-clay-muted">${catLabel}</span>
        </div>
        <span class="text-xs font-semibold text-clay-muted flex items-center space-x-1">
          <i data-lucide="clock" class="w-3.5 h-3.5"></i>
          <span>${escapeHtml(art.published_at)}</span>
        </span>
      </div>

      <div>
        ${safeUrl ? `<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer" class="block text-sm sm:text-base font-extrabold text-clay-dark leading-snug hover:text-clay-terracotta transition">
          ${escapeHtml(art.title)}
        </a>` : `<h4 class="text-sm sm:text-base font-extrabold text-clay-dark leading-snug">${escapeHtml(art.title)}</h4>`}
        <p class="text-xs text-clay-muted font-medium mt-1.5 leading-relaxed">
          ${escapeHtml(art.summary)}
        </p>
      </div>

      <!-- Clinical & Supply Chain Impact Box -->
      <div class="bg-clay-inner rounded-2xl p-3 border border-clay-salmon/20 space-y-2">
        <div class="flex flex-wrap items-center justify-between gap-1 text-xs">
          <div class="flex items-center space-x-1 text-clay-terracotta font-extrabold">
            <i data-lucide="activity" class="w-3.5 h-3.5"></i>
            <span>Projected Impact:</span>
          </div>
          <span class="text-clay-dark font-black">${escapeHtml(art.clinical_impact)}</span>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-clay-salmon/15 text-xs">
          <div class="flex items-center space-x-1.5">
            <span class="text-[11px] font-bold text-clay-muted">Target EDL:</span>
            <div class="flex flex-wrap gap-1">${medBadges}</div>
          </div>
          <div class="flex items-center space-x-2">
            <button onclick="simulateNewsImpact('${safeId(art.id)}')" class="text-xs bg-clay-terracotta hover:bg-clay-terracottaDark text-white px-3.5 py-1.5 rounded-full font-black shadow-clay-btn transition flex items-center space-x-1 cursor-pointer">
              <span>${escapeHtml(art.action_label || 'Analyze Impact')}</span>
            </button>
          </div>
        </div>
      </div>

      <div class="flex flex-wrap items-center justify-between text-[11px] text-clay-muted font-medium pt-1 border-t border-slate-100 gap-2">
        <span>Source: <strong class="text-clay-dark font-bold">${escapeHtml(art.source)}</strong> &bull; District: <strong class="text-clay-dark">${escapeHtml(art.district)}</strong></span>
        ${safeUrl ? `
          <a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer" class="text-clay-terracotta hover:text-clay-terracottaDark hover:underline font-bold inline-flex items-center space-x-1 bg-clay-inner px-2.5 py-1 rounded-full border border-clay-salmon/25 shadow-sm transition cursor-pointer" title="Read original verified article">
            <span>Read Original Dispatch</span>
            <i data-lucide="external-link" class="w-3 h-3"></i>
          </a>
        ` : ''}
      </div>
    `;

    container.appendChild(card);
  });

  if (window.lucide) lucide.createIcons();
}

function openNewsModal() {
  const m = document.getElementById('newsModal');
  if (m) m.classList.remove('hidden');
  fetchNews();
  if (window.lucide) lucide.createIcons();
}

function closeNewsModal() {
  const m = document.getElementById('newsModal');
  if (m) m.classList.add('hidden');
}

function filterNewsCategory(cat) {
  activeNewsCategory = cat;
  const pills = ['all', 'climate', 'air_quality', 'epidemic', 'supply_chain', 'clinical'];
  pills.forEach(p => {
    const el = document.getElementById(`newsCat-${p}`);
    if (!el) return;
    if (p === cat) {
      el.className = 'px-3 py-1.5 rounded-full text-xs font-black bg-clay-terracotta text-white shadow-sm transition cursor-pointer';
    } else {
      el.className = 'px-3 py-1.5 rounded-full text-xs font-bold bg-clay-inner text-clay-dark border border-clay-salmon/20 hover:bg-white transition cursor-pointer';
    }
  });
  renderNewsList();
}

function onNewsSearchInput(val) {
  activeNewsSearch = (val || '').trim().toLowerCase();
  renderNewsList();
}

function simulateNewsImpact(articleId) {
  const art = allNewsArticles.find(a => a.id === articleId);
  if (!art) return;

  closeNewsModal();

  // Focus the dashboard on what the article concerns; it never changes the live/scenario telemetry
  if (art.related_medicines && art.related_medicines.length > 0) {
    filterMedicine(art.related_medicines[0]);
  }

  if (art.target_facility_id) {
    setTimeout(() => {
      openFacilityDetail(art.target_facility_id);
    }, 350);
  }
}



