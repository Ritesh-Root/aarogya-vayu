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

// Advanced Atmospheric GIS & Courier Fleet Telemetry
let facilityMarkersLayer = null;
let courierMarkersLayer = null;
let sensorMarkersLayer = null;
let atmosphericPlumeLayer = null;
let activeCouriers = [];
let courierTransitInterval = null;
let activeMapFilter = 'all';
let currentInspectFacilityId = null;
let isSpeaking = false;
let currentTelemetry = null;

// Lucknow-Unnao Atmospheric Inversion Polygon Coordinates
const CORRIDOR_POLYGON = [
  [27.02, 80.45],
  [27.00, 80.85],
  [26.90, 81.16],
  [26.72, 81.15],
  [26.54, 80.70],
  [26.46, 80.35],
  [26.60, 80.22],
  [26.85, 80.32]
];

document.addEventListener('DOMContentLoaded', async () => {
  initMap();
  await loadInitialData();
  setupEventListeners();
  lucide.createIcons();

  const urlParams = new URLSearchParams(window.location.search);
  const view = urlParams.get('view') || urlParams.get('tab');
  if (view) {
    setTimeout(async () => {
      if (view === 'cmo') {
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
        useVoiceTemplate(1);
        setTimeout(() => submitVoiceIntake(), 200);
      } else if (view === 'agents') {
        const term = document.getElementById('agentTerminalBody');
        if (term) term.scrollIntoView({ behavior: 'instant', block: 'center' });
        await runAgentPipeline();
      } else if (view === 'vision') {
        const btnV = document.getElementById('btnVision');
        if (btnV) btnV.scrollIntoView({ behavior: 'instant', block: 'center' });
        await runVisionVerification();
      }
    }, 400);
  }
});

function initMap() {
  // Center roughly between Lucknow and Unnao
  map = L.map('map', { zoomControl: true }).setView([26.75, 80.72], 10);
  
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

async function loadInitialData() {
  try {
    await fetchEnvironmental();
    await fetchFacilities();
    await fetchRisks();
    await fetchRecommendations();
    await fetchAuditLog();
  } catch (err) {
    console.error("Initialization error:", err);
  }
}

async function fetchEnvironmental() {
  try {
    const res = await fetch('/api/environmental');
    const data = await res.json();
    const t = data.telemetry;
    currentTelemetry = t;

    const valAqi = document.getElementById('valAqi');
    if (valAqi) valAqi.textContent = `${t.aqi} (${t.aqi > 300 ? 'Severe' : t.aqi > 200 ? 'Poor' : 'Moderate'})`;

    const valPm25 = document.getElementById('valPm25');
    if (valPm25) valPm25.textContent = `${t.pm25} µg/m³`;

    const valTemp = document.getElementById('valTemp');
    if (valTemp) valTemp.textContent = `${t.temperature_c}°C`;

    const valCorridor = document.getElementById('valCorridor');
    if (valCorridor) valCorridor.textContent = t.corridor;

    const bannerTitle = document.getElementById('bannerTitle');
    const bannerDesc = document.getElementById('bannerDesc');
    const mults = data.surge_multipliers || {};

    if (t.smog_episode) {
      if (bannerTitle) bannerTitle.textContent = "Lucknow-Unnao Smog Inversion Active";
      if (bannerDesc) bannerDesc.textContent = `AQI ${t.aqi} • PM2.5: ${t.pm25} µg/m³ • +${Math.round(((mults['AQI / Smog'] || 1.62) - 1) * 100)}% Acute Respiratory Demand • 42h Lag Onset`;
    } else if (t.heatwave_alert) {
      if (bannerTitle) bannerTitle.textContent = "Central Awadh Heatwave Alert Active";
      if (bannerDesc) bannerDesc.textContent = `Temp: ${t.temperature_c}°C • +${Math.round(((mults['Heatwave / Drought'] || 1.85) - 1) * 100)}% Dehydration / ORS Demand`;
    } else {
      if (bannerTitle) bannerTitle.textContent = "All District Corridors Operating at Baseline";
      if (bannerDesc) bannerDesc.textContent = `AQI ${t.aqi} • Temp: ${t.temperature_c}°C • Baseline Normal Consumption`;
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

  let strokeColor = '#DE6B48';
  let fillColor = '#DE6B48';
  let fillOpacity = 0.22;
  let label = `🌫️ Lucknow-Unnao Smog Inversion Corridor (AQI ${t.aqi})`;

  if (t.smog_episode) {
    strokeColor = '#C25433';
    fillColor = '#DE6B48';
    fillOpacity = 0.32;
    label = `🌫️ Severe Smog Inversion Corridor • Inversion Base: 320m • AQI ${t.aqi} • PM2.5: ${t.pm25} µg/m³`;
  } else if (t.heatwave_alert) {
    strokeColor = '#DC2626';
    fillColor = '#F97316';
    fillOpacity = 0.28;
    label = `🔥 Central Awadh Heatwave Isotherm Zone • Max Temp: ${t.temperature_c}°C • Extreme Dehydration Risk`;
  } else {
    fillOpacity = 0.08;
    strokeColor = '#0284C7';
    fillColor = '#38BDF8';
    label = `🍃 Baseline Atmospheric Zone • AQI ${t.aqi} • Normal Ventilation`;
  }

  atmosphericPlumeLayer = L.polygon(CORRIDOR_POLYGON, {
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
        <div>Corridor: <strong class="text-slate-900">${t.corridor}</strong></div>
        <div>Active AQI: <strong class="text-[#DE6B48]">${t.aqi}</strong> (PM2.5: ${t.pm25} µg/m³)</div>
        <div>Inversion Ceiling: <strong>${t.smog_episode ? '320m AGL (Severe Trap)' : '1,200m AGL'}</strong></div>
        <div>Ventilation Index: <strong>${t.smog_episode ? '1,850 m²/s (Stagnant)' : '6,400 m²/s (Good)'}</strong></div>
      </div>
    </div>
  `);

  if (activeMapFilter === 'all' || activeMapFilter === 'plume') {
    atmosphericPlumeLayer.addTo(map);
  }

  // Update Glassmorphic Map HUD
  const hudCorridor = document.getElementById('hudCorridor');
  if (hudCorridor) {
    hudCorridor.textContent = t.smog_episode ? "AQI 385 • Severe Smog Inversion" : (t.heatwave_alert ? `${t.temperature_c}°C • Heatwave Alert` : `AQI ${t.aqi} • Baseline Normal`);
  }
  const hudInversion = document.getElementById('hudInversion');
  if (hudInversion) {
    hudInversion.textContent = t.smog_episode ? "320m AGL (Trapping High)" : (t.heatwave_alert ? "Thermal Dome Active" : "Normal Dispersion");
  }
}

function updateSensorStations(t) {
  if (!sensorMarkersLayer) return;
  sensorMarkersLayer.clearLayers();

  const sensorData = [
    {
      id: "SNS-LKO-01",
      name: "Talkatora Industrial CPCB Stn",
      type: "Continuous Ambient Air Quality Node",
      lat: 26.832,
      lng: 80.892,
      aqi: t.smog_episode ? 412 : (t.heatwave_alert ? 165 : 82),
      pm25: t.smog_episode ? 298.4 : 35.0,
      temp: t.temperature_c,
      status: t.smog_episode ? "Hazardous" : "Moderate"
    },
    {
      id: "SNS-LKO-02",
      name: "Amausi Airport Met Center (IMD)",
      type: "Synoptic Automated Doppler Node",
      lat: 26.760,
      lng: 80.880,
      aqi: t.smog_episode ? 375 : (t.heatwave_alert ? 145 : 70),
      pm25: t.smog_episode ? 245.0 : 26.0,
      temp: t.temperature_c - 0.5,
      status: t.smog_episode ? "Very Poor" : "Satisfactory"
    },
    {
      id: "SNS-UNA-03",
      name: "Unnao Industrial Cluster Node",
      type: "UPPCB IoT Emission Hub",
      lat: 26.545,
      lng: 80.495,
      aqi: t.smog_episode ? 398 : (t.heatwave_alert ? 155 : 78),
      pm25: t.smog_episode ? 278.2 : 31.0,
      temp: t.temperature_c + 0.5,
      status: t.smog_episode ? "Severe" : "Moderate"
    },
    {
      id: "SNS-LKO-04",
      name: "Malihabad Agro-Met Station",
      type: "Agri-Weather & Particulate Node",
      lat: 26.925,
      lng: 80.705,
      aqi: t.smog_episode ? 310 : (t.heatwave_alert ? 130 : 62),
      pm25: t.smog_episode ? 195.5 : 22.0,
      temp: t.temperature_c - 1.0,
      status: t.smog_episode ? "Poor" : "Good"
    },
    {
      id: "SNS-LKO-05",
      name: "Gomti River Basin Hydrological Node",
      type: "River Valley Inversion Monitor",
      lat: 26.865,
      lng: 80.950,
      aqi: t.smog_episode ? 340 : (t.heatwave_alert ? 138 : 68),
      pm25: t.smog_episode ? 220.0 : 25.0,
      temp: t.temperature_c - 0.2,
      status: t.smog_episode ? "Poor" : "Good"
    }
  ];

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
          <span class="font-black text-slate-900 text-sm">${s.name}</span>
        </div>
        <div class="text-slate-600 text-xs space-y-1 font-medium">
          <div>Station Type: <strong class="text-slate-800">${s.type}</strong></div>
          <div>Real-Time AQI: <strong class="${isSevere ? 'text-red-600 font-black' : 'text-slate-900 font-black'}">${s.aqi} (${s.status})</strong></div>
          <div>PM2.5 Sensor: <strong class="text-slate-800">${s.pm25} µg/m³</strong></div>
          <div>Ambient Temp: <strong class="text-slate-800">${s.temp}°C</strong></div>
        </div>
      </div>
    `);
  });
}

async function fetchFacilities() {
  try {
    const res = await fetch('/api/facilities');
    facilities = await res.json();
    
    const select = document.getElementById('voiceFacilitySelect');
    if (select) {
      select.innerHTML = '<option value="">Auto-Detect from Voice Transcript</option>';
      facilities.forEach(fac => {
        const opt = document.createElement('option');
        opt.value = fac.id;
        opt.textContent = `${fac.name} (${fac.district} - ${fac.type})`;
        select.appendChild(opt);
      });
    }
  } catch (err) {
    console.error("fetchFacilities error:", err);
  }
}

async function fetchRisks() {
  try {
    const res = await fetch('/api/risks');
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
          <div class="facility-pin cursor-pointer" onclick="openFacilityDetail('${fac.id}')">
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
            <strong class="text-slate-900 block text-sm sm:text-base font-black">${fac.name}</strong>
            <span class="text-xs font-black ${isCritical ? 'bg-red-100 text-red-700' : 'bg-emerald-100 text-emerald-700'} px-2.5 py-0.5 rounded-full">${fac.type}</span>
          </div>
          <div class="text-slate-600 text-xs font-medium py-0.5">${fac.district} &bull; ${fac.doctor}</div>
          <div class="mt-1 space-y-1">
      `;

      summary.items.slice(0, 4).forEach(item => {
        const badgeColor = item.status === 'CRITICAL' ? 'text-red-600 font-black' : item.status === 'WARNING' ? 'text-amber-600 font-bold' : 'text-emerald-600 font-bold';
        popupContent += `
          <div class="flex justify-between border-b border-slate-100 pb-1 text-xs">
            <span class="font-medium text-slate-700">${item.medicine_name.split('(')[0]}</span>
            <span class="${badgeColor}">${item.days_of_coverage}d cover (${item.current_stock}u)</span>
          </div>
        `;
      });

      popupContent += `
          </div>
          <div class="mt-2.5 pt-2 border-t border-slate-200 grid grid-cols-2 gap-2">
            <button onclick="openFacilityDetail('${fac.id}')" class="text-xs sm:text-sm bg-slate-900 hover:bg-slate-800 text-white px-3 py-1.5 rounded-full font-bold shadow-sm transition text-center cursor-pointer">
              Inspect Stock
            </button>
            <button onclick="runTransferFor('${fac.id}')" class="text-xs sm:text-sm bg-clay-terracotta hover:bg-clay-terracottaDark text-white px-3 py-1.5 rounded-full font-black shadow-sm transition text-center cursor-pointer">
              Solve AI
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
      <div class="flex items-center space-x-3">
        <div class="w-11 h-11 rounded-xl ${isCritical ? 'bg-red-100 text-red-600' : 'bg-amber-100 text-amber-700'} flex items-center justify-center font-black text-sm flex-shrink-0">
          ${facType}
        </div>
        <div>
          <h4 class="text-sm font-black text-clay-dark">${item.facility_name}</h4>
          <p class="text-xs ${isCritical ? 'text-red-500 font-bold' : 'text-amber-600 font-bold'}">${item.medicine_name.split('(')[0]} &bull; ${item.days_of_coverage}d Cover</p>
        </div>
      </div>
      <div class="text-right flex items-center space-x-2">
        <span class="text-sm font-black text-clay-dark whitespace-nowrap">${item.current_stock} Units</span>
        <button onclick="runTransferFor('${item.facility_id}')" class="text-xs ${isCritical ? 'bg-clay-terracotta hover:bg-clay-terracottaDark text-white' : 'bg-clay-terracotta/10 text-clay-terracotta hover:bg-clay-terracotta hover:text-white'} px-3.5 py-1.5 rounded-full font-bold shadow-sm transition cursor-pointer">
          ${isCritical ? 'Solve' : 'View'}
        </button>
      </div>
    `;
    watchlistContainer.appendChild(row);
  });
}

async function fetchRecommendations() {
  try {
    const res = await fetch('/api/recommendations');
    activeRecs = await res.json();

    const statActiveTransfers = document.getElementById('statActiveTransfers');
    if (statActiveTransfers) statActiveTransfers.textContent = `${activeRecs.filter(r => r.status === 'PENDING_APPROVAL').length} Pending`;

    let totalExpiryPrevented = 0;
    let totalDist = 0;

    activeRecs.forEach(r => {
      if (r.expiry_waste_prevented) totalExpiryPrevented += r.units_to_transfer;
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

function updateCourierFleet() {
  if (!courierMarkersLayer) return;
  courierMarkersLayer.clearLayers();
  activeCouriers = [];

  const baseTransfers = activeRecs.length > 0 ? activeRecs : [
    {
      id: "REC-LIVE-01",
      donor_facility_id: "CHC-LKO-02",
      recipient_facility_id: "PHC-LKO-01",
      donor_facility_name: "CHC Malihabad",
      recipient_facility_name: "PHC Kakori",
      medicine_name: "Salbutamol Respirator Solution (Respules 2.5mg)",
      units_to_transfer: 30,
      distance_km: 14.2,
      vehicle_id: "UP-32-G-4812"
    },
    {
      id: "REC-LIVE-02",
      donor_facility_id: "CHC-UNA-09",
      recipient_facility_id: "CHC-LKO-06",
      donor_facility_name: "CHC Nawabganj",
      recipient_facility_name: "CHC Sarojini Nagar",
      medicine_name: "Oral Rehydration Salts (ORS WHO Formula)",
      units_to_transfer: 120,
      distance_km: 26.5,
      vehicle_id: "UP-35-AH-2041"
    },
    {
      id: "REC-LIVE-03",
      donor_facility_id: "CHC-LKO-04",
      recipient_facility_id: "PHC-LKO-03",
      donor_facility_name: "CHC Gosainganj",
      recipient_facility_name: "PHC Mohanlalganj",
      medicine_name: "Amoxicillin + Clavulanate 625mg",
      units_to_transfer: 50,
      distance_km: 18.0,
      vehicle_id: "UP-32-BG-9014"
    }
  ];

  baseTransfers.forEach((rec, idx) => {
    const donor = facilities.find(f => f.id === rec.donor_facility_id);
    const recip = facilities.find(f => f.id === rec.recipient_facility_id);
    if (!donor || !recip) return;

    const initialProgress = (0.22 + idx * 0.32) % 0.9;
    const currentLat = donor.lat + (recip.lat - donor.lat) * initialProgress;
    const currentLng = donor.lng + (recip.lng - donor.lng) * initialProgress;

    const vehicleId = rec.vehicle_id || `UP-32-BG-${3200 + idx * 142}`;
    const medicineShort = rec.medicine_name.split('(')[0];

    const vanIcon = L.divIcon({
      className: 'courier-van-marker',
      html: `
        <div class="flex items-center space-x-1.5 bg-slate-950 text-white font-black text-xs px-3 py-1 rounded-full shadow-xl border border-emerald-400 cursor-pointer hover:scale-105 transition">
          <span class="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-ping"></span>
          <span>🚑 ${vehicleId}</span>
        </div>
      `,
      iconSize: [135, 28],
      iconAnchor: [67, 14]
    });

    const marker = L.marker([currentLat, currentLng], { icon: vanIcon }).addTo(courierMarkersLayer);

    marker.bindPopup(`
      <div class="p-1.5 font-sans text-xs sm:text-sm space-y-1.5">
        <div class="flex items-center justify-between pb-1.5 border-b border-slate-200">
          <span class="font-black text-slate-900 text-sm">🚑 ${vehicleId}</span>
          <span class="bg-emerald-100 text-emerald-800 text-xs font-black px-2.5 py-0.5 rounded-full">TRANSIT ACTIVE</span>
        </div>
        <div class="text-slate-600 text-xs space-y-1 font-medium">
          <div>Donor: <strong class="text-slate-900">${donor.name}</strong></div>
          <div>Destination: <strong class="text-[#DE6B48]">${recip.name}</strong></div>
          <div>Cargo: <strong class="text-slate-900">${rec.units_to_transfer} Units</strong> (${medicineShort})</div>
          <div>Transit: <strong class="text-slate-900">${Math.round(initialProgress * 100)}% Complete</strong> &bull; ETA ${Math.max(4, Math.round((1 - initialProgress) * 25))} mins</div>
          <div class="text-emerald-700 text-xs font-bold pt-0.5">Green Corridor Logistics Active &bull; Cold Chain: 4.2°C</div>
        </div>
      </div>
    `);

    activeCouriers.push({
      id: rec.id,
      vehicleId,
      donor,
      recip,
      units: rec.units_to_transfer,
      medicine: medicineShort,
      progress: initialProgress,
      marker
    });
  });

  const hudCouriers = document.getElementById('hudCouriers');
  if (hudCouriers) {
    hudCouriers.textContent = `${activeCouriers.length} Active Fleet Units`;
  }
}

function startCourierAnimationLoop() {
  if (courierTransitInterval) clearInterval(courierTransitInterval);
  courierTransitInterval = setInterval(() => {
    simulateCourierTransitStep(false);
  }, 2200);
}

function simulateCourierTransitStep(userTriggered = true) {
  if (!activeCouriers || activeCouriers.length === 0) return;

  activeCouriers.forEach(c => {
    c.progress += 0.04;
    if (c.progress >= 0.96) {
      c.progress = 0.05;
    }

    const curLat = c.donor.lat + (c.recip.lat - c.donor.lat) * c.progress;
    const curLng = c.donor.lng + (c.recip.lng - c.donor.lng) * c.progress;

    if (c.marker) {
      c.marker.setLatLng([curLat, curLng]);
      c.marker.setPopupContent(`
        <div class="p-1.5 font-sans text-xs sm:text-sm space-y-1.5">
          <div class="flex items-center justify-between pb-1.5 border-b border-slate-200">
            <span class="font-black text-slate-900 text-sm">🚑 ${c.vehicleId}</span>
            <span class="bg-emerald-100 text-emerald-800 text-xs font-black px-2.5 py-0.5 rounded-full">TRANSIT ACTIVE</span>
          </div>
          <div class="text-slate-600 text-xs space-y-1 font-medium">
            <div>Donor: <strong class="text-slate-900">${c.donor.name}</strong></div>
            <div>Destination: <strong class="text-[#DE6B48]">${c.recip.name}</strong></div>
            <div>Cargo: <strong class="text-slate-900">${c.units} Units</strong> (${c.medicine})</div>
            <div>Transit: <strong class="text-slate-900">${Math.round(c.progress * 100)}% Complete</strong> &bull; ETA ${Math.max(3, Math.round((1 - c.progress) * 25))} mins</div>
            <div class="text-emerald-700 text-xs font-bold pt-0.5">Green Corridor Logistics Active &bull; Cold Chain: 4.2°C</div>
          </div>
        </div>
      `);
    }
  });

  if (userTriggered) {
    const toast = document.createElement('div');
    toast.className = 'fixed bottom-6 right-6 bg-slate-950 text-white text-xs px-4 py-2.5 rounded-2xl shadow-2xl border border-emerald-400 z-50 transition transform flex items-center space-x-2 animate-bounce';
    toast.innerHTML = '<span class="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-ping"></span><span>GPS Pulse: All active couriers advanced +4% along priority corridor</span>';
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
    container.innerHTML = `<div class="col-span-full text-center py-6 text-clay-muted text-xs">${q ? `No transfer orders matching "${escapeHtml(searchQuery)}"` : 'All district inventories are balanced. Zero acute stockouts detected.'}</div>`;
    return;
  }

  items.forEach(rec => {
    const card = document.createElement('div');
    card.className = `bg-white border ${rec.status === 'APPROVED' ? 'border-emerald-300 bg-emerald-50/40' : 'border-clay-salmon/30'} rounded-2xl p-4 sm:p-5 flex flex-col justify-between space-y-3 shadow-sm transition hover:shadow-md`;

    const statusBadge = rec.status === 'APPROVED'
      ? `<span class="bg-emerald-100 text-emerald-800 border border-emerald-300 text-xs px-3 py-1 rounded-full font-black">APPROVED &amp; DISPATCHED</span>`
      : `<span class="bg-[#FFF1EB] text-clay-terracotta border border-clay-salmon/40 text-xs px-3 py-1 rounded-full font-black">AWAITING CMO SIGN-OFF</span>`;

    const expiryBadge = rec.expiry_waste_prevented
      ? `<span class="bg-[#EBF3EF] text-emerald-800 border border-emerald-300 text-xs px-2.5 py-1 rounded-full font-bold">Prevents Expiry Waste (${rec.batch_expiry_days}d left)</span>`
      : '';

    card.innerHTML = `
      <div>
        <div class="flex items-center justify-between">
          <span class="text-xs font-mono text-clay-muted font-bold">${rec.id}</span>
          ${statusBadge}
        </div>

        <div class="mt-2.5 flex items-center justify-between bg-clay-inner p-3 rounded-xl border border-clay-salmon/20">
          <div>
            <span class="text-[10px] text-clay-muted uppercase font-extrabold tracking-wider block">Donor (Surplus)</span>
            <strong class="text-sm font-black text-clay-dark">${rec.donor_facility_name}</strong>
          </div>
          <div class="text-clay-muted text-xs px-2 flex flex-col items-center">
            <span>&rarr;</span>
            <span class="text-xs font-black text-clay-terracotta">${rec.distance_km} km</span>
          </div>
          <div class="text-right">
            <span class="text-[10px] text-clay-muted uppercase font-extrabold tracking-wider block">Recipient (Deficit)</span>
            <strong class="text-sm font-black text-red-600">${rec.recipient_facility_name}</strong>
          </div>
        </div>

        <div class="mt-2.5">
          <div class="flex justify-between items-center text-sm">
            <span class="font-black text-clay-dark sm:text-base">${rec.medicine_name.split('(')[0]}</span>
            <span class="font-black text-clay-terracotta text-base sm:text-lg">${rec.units_to_transfer} Units</span>
          </div>
          <div class="text-xs sm:text-sm text-clay-muted mt-0.5 font-medium">
            Coverage: ${rec.recipient_initial_coverage_days}d &rarr; <strong class="text-emerald-700 font-black">${rec.recipient_new_coverage_days}d</strong>
          </div>
        </div>

        <div class="mt-2">
          ${expiryBadge}
        </div>
      </div>

      <div class="pt-2.5 border-t border-clay-salmon/20">
        ${rec.status === 'APPROVED' 
          ? `<button onclick="showChallanModal('${rec.id}')" class="w-full bg-clay-inner hover:bg-clay-bg text-clay-dark text-xs sm:text-sm py-2.5 rounded-full font-bold border border-clay-salmon/30 transition cursor-pointer">View Official Challan</button>`
          : `<button onclick="approveTransfer('${rec.id}')" class="w-full bg-clay-terracotta hover:bg-clay-terracottaDark text-white text-xs sm:text-sm py-2.5 rounded-full font-black shadow-clay-btn transition cursor-pointer">Approve &amp; Dispatch</button>`
        }
      </div>
    `;

    container.appendChild(card);
  });
}

async function approveTransfer(recId) {
  try {
    const res = await fetch('/api/approve-transfer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        recommendation_id: recId,
        officer_name: "Dr. S. K. Saxena (Chief Medical Officer, District Health Society)",
        comments: "Approved for immediate district ambulance/van courier transfer under Climate Surge Protocol."
      })
    });

    const data = await res.json();
    if (res.ok) {
      await loadInitialData();
      showChallanModal(recId, data);
    } else {
      alert("Transfer approval failed: " + (data.detail || "Server error"));
    }
  } catch (err) {
    console.error(err);
    alert("Network error while approving transfer");
  }
}

function showChallanModal(recId, approvalData = null) {
  const rec = activeRecs.find(r => r.id === recId);
  if (!rec) return;

  document.getElementById('modalChallanId').textContent = approvalData ? approvalData.dispatch_challan_id : `CHALLAN-UP-20260905-${rec.id}`;
  document.getElementById('modalDate').textContent = new Date().toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
  document.getElementById('modalDonor').textContent = rec.donor_facility_name;
  document.getElementById('modalRecipient').textContent = rec.recipient_facility_name;
  document.getElementById('modalMed').textContent = rec.medicine_name;
  document.getElementById('modalUnits').textContent = `${rec.units_to_transfer} Units`;
  document.getElementById('modalBatch').textContent = rec.batch_number;
  document.getElementById('modalDist').textContent = `${rec.distance_km} km`;
  document.getElementById('modalRationale').textContent = rec.rationale_en;
  document.getElementById('modalHash').textContent = approvalData ? approvalData.cryptographic_hash : "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

  document.getElementById('challanModal').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('challanModal').classList.add('hidden');
}

async function fetchAuditLog() {
  try {
    const res = await fetch('/api/audit-log');
    allLogs = await res.json();

    const tbody = document.getElementById('auditTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';

    allLogs.forEach(e => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-clay-inner/80 transition';

      let detailsPreview = JSON.stringify(e.details);
      if (detailsPreview.length > 60) detailsPreview = detailsPreview.substring(0, 60) + '...';

      tr.innerHTML = `
        <td class="py-3 px-3.5 text-clay-muted font-mono font-bold text-xs sm:text-sm">#${e.index}</td>
        <td class="py-3 px-3.5 text-clay-dark font-semibold text-xs sm:text-sm">${e.timestamp.substring(11, 19)}</td>
        <td class="py-3 px-3.5 font-bold text-clay-terracotta text-xs sm:text-sm">${e.event_type}</td>
        <td class="py-3 px-3.5 text-clay-dark font-medium text-xs sm:text-sm">${e.approved_by}</td>
        <td class="py-3 px-3.5 text-clay-muted font-mono text-xs sm:text-sm" title='${JSON.stringify(e.details)}'>${detailsPreview}</td>
        <td class="py-3 px-3.5 text-slate-500 font-mono text-xs font-semibold">${e.current_hash.substring(0, 16)}...</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("fetchAuditLog error:", err);
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

function loadSampleVoice(idx) {
  showWaveformBriefly(2500);
  const txt = document.getElementById('voiceTranscript');
  const facSelect = document.getElementById('voiceFacilitySelect');
  if (idx === 1) {
    txt.value = "This is PHC Kakori reporting. We only have 15 respules of Salbutamol left and treated 40 acute respiratory patients yesterday.";
    if (facSelect) facSelect.value = "PHC-LKO-01";
  } else if (idx === 2) {
    txt.value = "Sarojini Nagar CHC reporting: 120 packets of ORS oral rehydration salt remain, with 35 new acute dehydration cases.";
    if (facSelect) facSelect.value = "CHC-LKO-06";
  } else if (idx === 3) {
    txt.value = "PHC Itaunja reporting: Paracetamol syrup stock is depleted, urgently require 50 bottles for pediatric cases.";
    if (facSelect) facSelect.value = "PHC-LKO-08";
  }
}

async function submitVoiceIntake() {
  const text = document.getElementById('voiceTranscript').value.trim();
  if (!text) {
    alert("Please enter or record a voice message in English or Hindi.");
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
  btn.innerHTML = `<span>Processing Audio with Gemini 3.8 Flash...</span>`;

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

    const result = await res.json();
    btn.disabled = false;
    btn.innerHTML = `<span>Process &amp; Commit Record</span>`;

    const box = document.getElementById('voiceResultBox');
    if (box) box.classList.remove('hidden');

    const badge = document.getElementById('voiceResultBadge');
    if (badge) {
      if (result.quality_checks_passed) {
        badge.textContent = "QA PASSED & LOGGED";
        badge.className = "text-[10px] font-bold text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded-full";
      } else {
        badge.textContent = "ANOMALY FLAGGED";
        badge.className = "text-[10px] font-bold text-red-600 bg-red-100 px-2 py-0.5 rounded-full";
      }
    }

    const conf = document.getElementById('voiceConfidence');
    if (conf) conf.textContent = `Confidence: ${Math.round(result.confidence_score * 100)}%`;
    const facNameEl = document.getElementById('voiceFacName');
    if (facNameEl) facNameEl.textContent = result.facility_name;
    const medNameEl = document.getElementById('voiceMedName');
    if (medNameEl) medNameEl.textContent = result.medicine_name;
    const stockEl = document.getElementById('voiceStockQty');
    if (stockEl) stockEl.textContent = `${result.reported_stock} units`;
    const dispEl = document.getElementById('voiceDispQty');
    if (dispEl) dispEl.textContent = result.dispensed_yesterday !== null ? `${result.dispensed_yesterday} units` : 'N/A';
    const actionEl = document.getElementById('voiceActionText');
    if (actionEl) actionEl.textContent = result.anomaly_flag || result.action_taken;

    // Refresh dashboard
    await loadInitialData();
  } catch (err) {
    console.error(err);
    btn.disabled = false;
    btn.innerHTML = `<span>Process &amp; Commit Record</span>`;
    alert("Error processing voice intake");
  } finally {
    if (wave) {
      wave.classList.add('hidden');
      wave.classList.remove('flex');
    }
  }
}

function recordMockMic() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    alert("Browser speech recognition is not supported in this environment. Please click on one of the sample scenario buttons!");
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.lang = 'en-US';
  recognition.interimResults = false;

  const micBtn = document.getElementById('btnMic');
  const wave = document.getElementById('voiceWaveform');
  if (micBtn) micBtn.classList.add('bg-red-600', 'text-white');

  recognition.onstart = () => {
    const txt = document.getElementById('voiceTranscript');
    if (txt) txt.placeholder = "Listening in English (speak now)...";
    if (wave) {
      wave.classList.remove('hidden');
      wave.classList.add('flex');
    }
  };

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    const txt = document.getElementById('voiceTranscript');
    if (txt) txt.value = transcript;
    if (micBtn) micBtn.classList.remove('bg-red-600', 'text-white');
    if (wave) {
      wave.classList.add('hidden');
      wave.classList.remove('flex');
    }
  };

  recognition.onerror = () => {
    if (micBtn) micBtn.classList.remove('bg-red-600', 'text-white');
    if (wave) {
      wave.classList.add('hidden');
      wave.classList.remove('flex');
    }
  };

  recognition.start();
}

async function switchScenario(type) {
  let envData = {};
  const activeClass = 'px-4 py-2 rounded-full font-bold text-xs bg-clay-terracotta text-white shadow-clay-btn transition';
  const inactiveClass = 'px-4 py-2 rounded-full font-bold text-xs text-clay-muted hover:text-clay-dark hover:bg-white transition';

  const btnSmog = document.getElementById('scenarioSmog');
  const btnHeat = document.getElementById('scenarioHeat');
  const btnNormal = document.getElementById('scenarioNormal');

  if (type === 'smog') {
    envData = {
      aqi: 385,
      pm25: 265.0,
      temperature_c: 17.5,
      humidity_pct: 78.0,
      heatwave_alert: false,
      smog_episode: true,
      corridor: "Lucknow-Unnao Indo-Gangetic Smog Corridor (Severe Inversion)"
    };
    if (btnSmog) btnSmog.className = activeClass;
    if (btnHeat) btnHeat.className = inactiveClass;
    if (btnNormal) btnNormal.className = inactiveClass;
  } else if (type === 'heat') {
    envData = {
      aqi: 140,
      pm25: 65.0,
      temperature_c: 43.5,
      humidity_pct: 35.0,
      heatwave_alert: true,
      smog_episode: false,
      corridor: "Central Awadh Heatwave Corridor (Severe Dehydration Risk)"
    };
    if (btnHeat) btnHeat.className = activeClass;
    if (btnSmog) btnSmog.className = inactiveClass;
    if (btnNormal) btnNormal.className = inactiveClass;
  } else {
    envData = {
      aqi: 75,
      pm25: 28.0,
      temperature_c: 26.0,
      humidity_pct: 60.0,
      heatwave_alert: false,
      smog_episode: false,
      corridor: "Baseline Seasonal Conditions"
    };
    if (btnNormal) btnNormal.className = activeClass;
    if (btnSmog) btnSmog.className = inactiveClass;
    if (btnHeat) btnHeat.className = inactiveClass;
  }

  await fetch('/api/environmental', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(envData)
  });

  await loadInitialData();
}

function fitMapBounds() {
  if (facilities.length > 0) {
    const group = new L.featureGroup(Object.values(facilityMarkers));
    map.fitBounds(group.getBounds().pad(0.15));
  }
}

// Multi-Agent Pipeline Runner with Google ADK Orchestration
async function runAgentPipeline(targetFacId = null) {
  const btn = document.getElementById('btnRunAgents');
  const term = document.getElementById('agentTerminalBody');
  const snippet = document.getElementById('voiceTranscript').value.trim() || null;
  const facSelect = document.getElementById('voiceFacilitySelect');
  
  const facId = targetFacId || (facSelect ? (facSelect.value || 'PHC-LKO-01') : 'PHC-LKO-01');
  if (facSelect && facId) facSelect.value = facId;

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Orchestrating ADK Multi-Agent System...</span>`;
    lucide.createIcons();
  }

  term.innerHTML = '<div class="text-indigo-400 animate-pulse">// Initializing Google ADK Multi-Agent Context &middot; Loading Vertex AI Grounding Store...</div>';

  try {
    const res = await fetch('/api/agents/run-resilience-pipeline', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target_facility_id: facId,
        voice_snippet: snippet
      })
    });

    const data = await res.json();
    term.innerHTML = '';

    const traces = data.traces || [];
    for (let i = 0; i < traces.length; i++) {
      const step = traces[i];
      await new Promise(r => setTimeout(r, 260)); // Dramatic pacing for demo

      const stepDiv = document.createElement('div');
      stepDiv.className = 'border-l-2 pl-3 py-1 space-y-1';

      let agentColor = 'border-blue-500 text-blue-400';
      let badgeColor = 'bg-blue-500/20 text-blue-300 border-blue-500/30';
      if (step.agent === 'FrontlineIntakeAgent') {
        agentColor = 'border-purple-500 text-purple-400';
        badgeColor = 'bg-purple-500/20 text-purple-300 border-purple-500/30';
      } else if (step.agent === 'LogisticsAgent') {
        agentColor = 'border-amber-500 text-amber-400';
        badgeColor = 'bg-amber-500/20 text-amber-300 border-amber-500/30';
      } else if (step.agent === 'GovernanceAgent') {
        agentColor = 'border-emerald-500 text-emerald-400';
        badgeColor = 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30';
      }

      stepDiv.className += ` ${agentColor}`;

      let typeBadge = `<span class="px-2 py-0.5 rounded text-xs font-bold border ${badgeColor}">${step.type}</span>`;
      
      let extraContent = '';
      if (step.type === 'TOOL_CALL') {
        const payload = step.payload || {};
        const toolName = payload.tool || 'calculate_optimal_transfer';
        const args = payload.arguments || (payload.target_facility_id ? {
          target_facility_id: payload.target_facility_id,
          medicine_id: payload.medicine_id,
          max_distance_km: payload.max_distance_km,
          donor_safety_buffer_days: payload.donor_safety_buffer_days
        } : {
          target_facility_id: facId,
          medicine_id: "MED-001",
          max_distance_km: 35.0,
          donor_safety_buffer_days: 14.0
        });
        extraContent = `
          <div class="mt-2 bg-[#0d121c] p-3.5 rounded-xl border border-amber-500/40 text-xs font-mono text-amber-300 shadow-inner">
            <div class="flex items-center space-x-2 text-slate-400 text-xs uppercase font-mono font-bold mb-1.5">
              <span class="w-2 h-2 rounded-full bg-amber-400 animate-ping"></span>
              <span>// GEMINI FUNCTION CALLING INVOKED</span>
            </div>
            <div class="text-amber-200 font-bold">&gt; tool: <strong>${toolName}()</strong></div>
            <div class="mt-1 text-slate-300 font-mono text-xs leading-relaxed">&gt; args: <span class="text-amber-100 font-semibold">${JSON.stringify(args)}</span></div>
          </div>
        `;
      } else if (step.type === 'GROUNDING_MATCH') {
        const entity = (step.payload && step.payload.grounded_entity) || {
          standard_name: "Salbutamol Respirator Solution (Respules 2.5mg)",
          code: "MED-001",
          category: "Schedule H - Bronchodilator"
        };
        extraContent = `
          <div class="mt-2 bg-[#0d121c] p-3.5 rounded-xl border border-purple-500/40 text-xs font-mono text-purple-300 shadow-inner">
            <div class="flex items-center space-x-2 text-slate-400 text-xs uppercase font-mono font-bold mb-1.5">
              <span class="w-2 h-2 rounded-full bg-purple-400 animate-ping"></span>
              <span>// VERTEX AI GROUNDING (EDL-UP-2026)</span>
            </div>
            <div>&gt; verified entity: <strong class="text-purple-200">${entity.standard_name}</strong> (${entity.code})</div>
            <div class="mt-1 text-slate-300">&gt; clinical class: <span class="text-purple-100 font-semibold">${entity.category}</span></div>
          </div>
        `;
      } else if (step.type === 'TOOL_RESULT') {
        const payload = step.payload || {};
        const units = payload.units_to_transfer || 50;
        const donor = payload.donor_facility_name || payload.donor_name || 'CHC Nawabganj';
        const dist = payload.distance_km || payload.transit_distance_km || 18.2;
        const expiry = payload.batch_expiry_days || 72;
        extraContent = `
          <div class="mt-2 bg-[#0d121c] p-3.5 rounded-xl border border-emerald-500/40 text-xs font-mono text-emerald-300 shadow-inner">
            <div class="flex items-center space-x-2 text-slate-400 text-xs uppercase font-mono font-bold mb-1.5">
              <span class="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
              <span>// DETERMINISTIC OR SOLVER RESULT</span>
            </div>
            <div>&gt; transfer: <strong class="text-emerald-300 font-bold">${units} units</strong> from <strong class="text-emerald-200 font-bold">${donor}</strong></div>
            <div class="mt-1">&gt; distance: <strong class="text-emerald-200">${dist} km</strong> | expiry salvaged: <strong class="text-emerald-200">${expiry}d left</strong></div>
          </div>
        `;
      } else if (step.agent === 'EnvironmentalSentinelAgent' && step.type === 'DISPATCH' && step.payload && step.payload.aqi) {
        extraContent = `
          <div class="mt-2 bg-[#0d121c] p-3 rounded-xl border border-blue-500/40 text-xs font-mono text-blue-300 shadow-inner flex flex-wrap gap-x-4 gap-y-1">
            <span>Surface AQI: <strong class="text-red-400">${step.payload.aqi}</strong></span>
            <span>PM2.5: <strong class="text-red-400">${step.payload.pm25} µg/m³</strong></span>
            <span>Wind: <strong class="text-slate-200">${step.payload.wind_speed_kmh} km/h</strong></span>
            <span>FIRMS Hotspots: <strong class="text-amber-400">${step.payload.firms_hotspots}</strong></span>
            <span>AOD Anomaly: <strong class="text-purple-300">+${step.payload.sentinel5p_aod_sigma}σ</strong></span>
          </div>
        `;
      }

      stepDiv.innerHTML = `
        <div class="flex items-center space-x-2 text-xs">
          <span class="text-slate-400 font-mono">${step.timestamp}</span>
          <strong class="text-white font-bold">${step.agent}</strong>
          ${typeBadge}
        </div>
        <p class="text-slate-200 text-xs sm:text-sm leading-relaxed font-sans">${step.message}</p>
        ${extraContent}
      `;

      term.appendChild(stepDiv);
      term.scrollTop = term.scrollHeight;
    }

    // Refresh UI
    await loadInitialData();
  } catch (err) {
    console.error("Agent pipeline error:", err);
    term.innerHTML = '<div class="text-red-400">// Error executing Multi-Agent Pipeline</div>';
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="play" class="w-4 h-4 fill-current"></i><span>Run ADK Pipeline (Live Demo)</span>`;
      lucide.createIcons();
    }
  }
}

// Facility Action: Solve with ADK Pipeline
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

  const voiceTxt = document.getElementById('voiceTranscript');
  if (voiceTxt && fac) {
    voiceTxt.value = `${fac.name} Emergency Logistics Dispatch: Critical stockout imminent under climate surge. Immediate inter-facility redistribution requested.`;
  }

  const term = document.getElementById('agentTerminalBody');
  if (term) {
    term.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  runAgentPipeline(facId);
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
  const input = document.getElementById('cmoQueryInput');
  const question = input.value.trim();
  if (!question) return;

  const box = document.getElementById('cmoResponseBox');
  box.classList.remove('hidden');
  document.getElementById('cmoAnswerText').innerHTML = '<span class="text-indigo-400 animate-pulse">// Strategic Insight Agent (Gemini 3.8 Flash) evaluating scenario...</span>';
  document.getElementById('cmoMetaBox').textContent = '';

  try {
    const res = await fetch('/api/cmo/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question })
    });

    const data = await res.json();
    document.getElementById('cmoQueryTypeBadge').textContent = data.query_type || "INSIGHT READY";
    
    // Display English primary response with Hindi translation below
    const answer = `
      <div class="space-y-2">
        <div class="text-clay-dark font-medium leading-relaxed">${data.answer_en}</div>
        <div class="text-clay-muted italic border-t border-clay-salmon/20 pt-1.5 text-[11px] font-sans">${data.answer_hi}</div>
      </div>
    `;
    document.getElementById('cmoAnswerText').innerHTML = answer;

    if (data.recommended_action) {
      document.getElementById('cmoMetaBox').textContent = `Action Protocol: ${data.recommended_action}`;
    } else if (data.substitution_details) {
      document.getElementById('cmoMetaBox').textContent = `Clinical Guidance: ${data.substitution_details.name} (Equivalence: ${data.substitution_details.equivalence_ratio * 100}%)`;
    } else if (data.metrics) {
      document.getElementById('cmoMetaBox').textContent = `MP Summary: ${data.metrics.population_served.toLocaleString()} constituents protected | ${data.metrics.stockouts_prevented} stockouts averted`;
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
    document.getElementById('cmoAnswerText').textContent = "Error communicating with Strategic Insight Agent";
  }
}

function speakCurrentCmoBriefing() {
  if (!('speechSynthesis' in window)) {
    alert("Speech Synthesis is not supported in this browser.");
    return;
  }

  const btnLabel = document.getElementById('btnTtsLabel');
  const statusEl = document.getElementById('cmoTtsStatus');

  if (window.speechSynthesis.speaking) {
    window.speechSynthesis.cancel();
    if (btnLabel) btnLabel.textContent = "🔊 Read Briefing Aloud";
    if (statusEl) statusEl.textContent = "";
    isSpeaking = false;
    return;
  }

  const answerEl = document.getElementById('cmoAnswerText');
  if (!answerEl) return;

  const rawText = answerEl.innerText || '';
  // Extract primary English answer (before Hindi translation)
  const lines = rawText.split('\n').map(l => l.trim()).filter(Boolean);
  const textToSpeak = lines[0] || rawText;

  if (!textToSpeak || textToSpeak.includes("// Strategic Insight Agent")) {
    alert("Please submit an inquiry first to generate a response!");
    return;
  }

  const utterance = new SpeechSynthesisUtterance(textToSpeak);
  utterance.rate = 1.0;
  utterance.pitch = 1.0;
  utterance.lang = 'en-US';

  utterance.onstart = () => {
    isSpeaking = true;
    if (btnLabel) btnLabel.textContent = "⏹️ Stop Speech";
    if (statusEl) statusEl.textContent = "Synthesizing vocal briefing...";
  };

  utterance.onend = () => {
    isSpeaking = false;
    if (btnLabel) btnLabel.textContent = "🔊 Read Briefing Aloud";
    if (statusEl) statusEl.textContent = "";
  };

  utterance.onerror = () => {
    isSpeaking = false;
    if (btnLabel) btnLabel.textContent = "🔊 Read Briefing Aloud";
    if (statusEl) statusEl.textContent = "";
  };

  window.speechSynthesis.speak(utterance);
}

// Gemini Vision Shelf Verification
async function runVisionVerification() {
  const btn = document.getElementById('btnVision');
  const box = document.getElementById('visionResultBox');
  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Scanning...</span>`;
  lucide.createIcons();

  try {
    const res = await fetch('/api/vision/verify-shelf-photo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_name: "phc_kakori_cupboard_01.jpg",
        facility_id: "PHC-LKO-01",
        reported_count: 15
      })
    });

    const data = await res.json();
    box.classList.remove('hidden');
    document.getElementById('visionSummaryText').textContent = data.verification_summary;

    btn.disabled = false;
    btn.innerHTML = `<span>Scan Verified &radic;</span>`;

    // Refresh audit log to show the vision verification event
    await fetchAuditLog();
  } catch (err) {
    console.error(err);
    btn.disabled = false;
    btn.innerHTML = `<span>Scan with Vision</span>`;
    alert("Vision scanning failed");
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
  if (subEl) subEl.textContent = `${fac.district} District • ${fac.type} • In-Charge: ${fac.doctor}`;

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
            <strong class="text-sm sm:text-base font-black text-clay-dark">${item.medicine_name.split('(')[0]}</strong>
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

function openNotificationsModal() {
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

function filterMedicine(medId) {
  const facSelect = document.getElementById('voiceFacilitySelect');
  const searchInput = document.getElementById('searchInput');

  if (medId === 'MED-001') {
    document.getElementById('voiceTranscript').value = "PHC Kakori: Respiratory medicine (Salbutamol) has only 15 respules remaining.";
    if (facSelect) facSelect.value = "PHC-LKO-01";
    if (searchInput) searchInput.value = "Salbutamol";
    filterDashboardBySearch("Salbutamol");
  } else if (medId === 'MED-002') {
    document.getElementById('voiceTranscript').value = "CHC Sarojini Nagar: ORS oral rehydration buffer has 120 packets remaining.";
    if (facSelect) facSelect.value = "CHC-LKO-06";
    if (searchInput) searchInput.value = "ORS";
    filterDashboardBySearch("ORS");
  }
}

function switchTab(tab) {
  const navItems = {
    'dashboard': document.getElementById('nav-dashboard'),
    'agents': document.getElementById('nav-agents'),
    'cmo': document.getElementById('nav-cmo'),
    'vision': document.getElementById('nav-vision'),
    'ledger': document.getElementById('nav-ledger')
  };

  Object.entries(navItems).forEach(([key, el]) => {
    if (!el) return;
    if (key === tab) {
      el.className = 'w-12 h-12 rounded-2xl bg-white text-clay-terracotta shadow-md flex items-center justify-center transition hover:scale-105';
    } else {
      el.className = 'w-12 h-12 rounded-2xl hover:bg-white/20 text-white/90 flex items-center justify-center transition hover:scale-105';
    }
  });

  if (tab === 'cmo') {
    openCmoModal();
  } else if (tab === 'agents') {
    const term = document.getElementById('agentTerminalBody');
    if (term) term.scrollIntoView({ behavior: 'smooth', block: 'center' });
    runAgentPipeline();
  } else if (tab === 'vision') {
    const btnV = document.getElementById('btnVision');
    if (btnV) btnV.scrollIntoView({ behavior: 'smooth', block: 'center' });
    runVisionVerification();
  } else if (tab === 'ledger') {
    openLedgerModal();
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
  ['cmoModal', 'challanModal', 'ledgerModal', 'notificationsModal', 'infoModal', 'facilityDetailModal'].forEach(id => {
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
      ['cmoModal', 'challanModal', 'ledgerModal', 'notificationsModal', 'infoModal', 'facilityDetailModal'].forEach(id => {
        const el = document.getElementById(id);
        if (el && !el.classList.contains('hidden')) {
          el.classList.add('hidden');
        }
      });
    }
  });
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
