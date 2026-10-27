// ── TAPO LIGHT HUB: HIGH-PERFORMANCE WEB CLIENT & ENGINE ────────────────────

let state = {
  devices: {},
  modes: [],
  effects_l900: [],
  effects_l930: [],
  active_effects: [],
  effects_catalog: {},
  audio_device: "auto",
  audio_style: "neon_drive",
  composite_mode: "off",
  circadian_enabled: false
};

let currentDevId = "strip1";
let currentTab = "music";
let currentEffectFilter = "all";
let effectSearchQuery = "";
let authToken = localStorage.getItem("tapo_auth_token") || "";

let ws = null;
let reconnectTimer = null;
let lastAudioData = null;
let lastZonePreview = null;
let animFrameId = null;
let isTabVisible = true;

// ── Music Reactivity Modes Catalog ──────────────────────────────────────────
const MUSIC_STYLES = [
  { id: "neon_drive", name: "Neon Drive", icon: "⚡", glow: "#06b6d4", desc: "80s Retrowave grid with snappy electric magenta & cyan beat sync." },
  { id: "sub_blast", name: "Sub Blast", icon: "💥", glow: "#8b5cf6", desc: "Kinetic sub-bass cannon detonating deep low-frequency shockwaves." },
  { id: "pulse", name: "Pulse", icon: "🌊", glow: "#3b82f6", desc: "Rhythmic bass-locked waves rippling outward from musical bar origins." },
  { id: "vocal_glow", name: "Vocal Glow", icon: "🎤", glow: "#f59e0b", desc: "Isolates human singing & lead melodies in an organic breathing halo." },
  { id: "liquid_groove", name: "Liquid Groove", icon: "💧", glow: "#10b981", desc: "Viscous fluid dynamics surging and cresting with downbeats & rhythm." },
  { id: "spectrum", name: "Spectrum", icon: "📊", glow: "#ec4899", desc: "50-Zone direct frequency equalizer mapping sub-bass to treble." },
  { id: "flow", name: "Flow", icon: "≈", glow: "#06b6d4", desc: "Silky undulating acoustic ribbons smoothly following musical contour." },
  { id: "edm", name: "EDM Drop", icon: "ϟ", glow: "#f43f5e", desc: "Explosive strobe flashes and laser sweeps built for bass drops." },
  { id: "chill", name: "Chill", icon: "☕", glow: "#d97706", desc: "Warm amber bass swells and gentle harmonic lo-fi relaxation." },
  { id: "reactive_aurora", name: "Aurora", icon: "🌌", glow: "#10b981", desc: "Northern lights reactive curtain dancing to chords & frequencies." },
  { id: "twinkle", name: "Twinkle", icon: "✨", glow: "#a855f7", desc: "High-frequency transients and cymbals shimmering like stardust." },
  { id: "movie", name: "Movie", icon: "🎬", glow: "#6366f1", desc: "Cinematic dialogue bias & sub-bass rumble without glare." },
  { id: "party", name: "Party", icon: "🎉", glow: "#f59e0b", desc: "High-energy multi-color celebration with upbeat rhythmic shifts." },
  { id: "bpm_resonator", name: "Resonator", icon: "⏱", glow: "#06b6d4", desc: "Phase-locked tempo metronome resonating strictly with detected BPM." },
  { id: "chain_reaction", name: "Chain Reaction", icon: "🎆", glow: "#ec4899", desc: "Chaotic sparks igniting on beats and cascading across nearby LEDs." }
];

// Curated Vibrant Effect Gradients for Instant CSS Rendering
const EFFECT_GRADIENTS = {
  tide: "linear-gradient(135deg, #02202b, #00c7be)",
  embers: "linear-gradient(135deg, #1c0502, #ea580c)",
  breathe: "linear-gradient(135deg, #2e1065, #a855f7)",
  drift: "linear-gradient(135deg, #1e1b4b, #6366f1)",
  starfield: "linear-gradient(135deg, #030712, #38bdf8)",
  lava_lamp: "linear-gradient(135deg, #450a0a, #ff4500)",
  golden_hour: "linear-gradient(135deg, #451a03, #f59e0b)",
  aurora: "linear-gradient(135deg, #022c22, #10b981)",
  cyber_chase: "linear-gradient(135deg, #500724, #f43f5e)",
  comet: "linear-gradient(135deg, #3b0764, #c084fc)",
  deep_ocean: "linear-gradient(135deg, #082f49, #0284c7)",
  raindrop: "linear-gradient(135deg, #0c4a6e, #38bdf8)",
  lightning: "linear-gradient(135deg, #1e1b4b, #818cf8)",
  rainbow: "linear-gradient(135deg, #ef4444, #3b82f6)",
  oil_slick: "linear-gradient(135deg, #064e3b, #06b6d4)",
  silk_ribbons: "linear-gradient(135deg, #4c0519, #ec4899)",
  nebula_bloom: "linear-gradient(135deg, #3b0764, #8b5cf6)",
  holographic_moire: "linear-gradient(135deg, #1e3a8a, #38bdf8)",
  bioluminescent_tide: "linear-gradient(135deg, #042f2e, #14b8a6)",
  ember_drift: "linear-gradient(135deg, #431407, #f97316)",
  cyberpunk: "linear-gradient(135deg, #701a75, #06b6d4)",
  sinelon: "linear-gradient(135deg, #312e81, #a855f7)",
  spiral_vortex: "linear-gradient(135deg, #1e1b4b, #f43f5e)",
  gravity_slosh: "linear-gradient(135deg, #0f172a, #06b6d4)",
  lissajous_orbit: "linear-gradient(135deg, #2e1065, #fbbf24)",
  planar_wind: "linear-gradient(135deg, #042f2e, #34d399)",
  radar_sweep: "linear-gradient(135deg, #022c22, #10b981)",
  candy_cane: "linear-gradient(135deg, #991b1b, #f87171)",
  police: "linear-gradient(135deg, #1e3a8a, #dc2626)",
  haunted_mansion: "linear-gradient(135deg, #052e16, #a855f7)",
  colortwinkles: "linear-gradient(135deg, #3b0764, #38bdf8)",
  fireworks_1d: "linear-gradient(135deg, #450a0a, #fbbf24)",
  dancing_shadows: "linear-gradient(135deg, #18181b, #71717a)",
  dissolve_random: "linear-gradient(135deg, #1e1b4b, #c084fc)",
  bouncing_balls: "linear-gradient(135deg, #042f2e, #f59e0b)",
  fire_2012: "linear-gradient(135deg, #450a0a, #ea580c)"
};

// ── Initialization ───────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initDOMListeners();
  renderMusicStylesGrid();
  connectWebSocket();
  fetchInitialState();
  startAnimationLoop();

  document.addEventListener("visibilitychange", () => {
    isTabVisible = !document.hidden;
    if (isTabVisible && !animFrameId) {
      startAnimationLoop();
    }
  });
});

function initDOMListeners() {
  // Master Power
  document.getElementById("btnMasterPower")?.addEventListener("click", () => {
    const anyOn = Object.values(state.devices).some(d => d.power);
    apiPost(`/api/device/all/power`, { power: !anyOn });
  });

  // Device Power
  document.getElementById("btnDevicePower")?.addEventListener("click", () => {
    const dev = getActiveDevice();
    if (!dev) return;
    apiPost(`/api/device/${currentDevId}/power`, { power: !dev.power });
  });

  // Brightness Slider
  const bSlider = document.getElementById("brightSlider");
  if (bSlider) {
    bSlider.addEventListener("input", (e) => {
      const val = parseInt(e.target.value, 10);
      document.getElementById("brightVal").textContent = `${val}%`;
      debouncedBrightness(val);
    });
  }

  // Quick Brightness Buttons
  document.querySelectorAll(".quick-levels button").forEach(btn => {
    btn.addEventListener("click", () => {
      const lvl = parseInt(btn.dataset.level, 10);
      document.getElementById("brightSlider").value = lvl;
      document.getElementById("brightVal").textContent = `${lvl}%`;
      apiPost(`/api/device/${currentDevId}/brightness`, { brightness: lvl });
    });
  });

  // Color Swatches
  document.querySelectorAll(".swatch-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const h = parseInt(btn.dataset.h, 10);
      const s = parseInt(btn.dataset.s, 10);
      const v = 100;
      apiPost(`/api/device/${currentDevId}/color`, { h, s, v });
    });
  });

  // Native Color Picker
  const cPicker = document.getElementById("nativeColorPicker");
  if (cPicker) {
    cPicker.addEventListener("input", (e) => {
      const [r, g, b] = hexToRgb(e.target.value);
      const [h, s, v] = rgbToHsv(r, g, b);
      apiPost(`/api/device/${currentDevId}/color`, { h, s, v });
    });
  }
}

// ── Tab Navigation ──────────────────────────────────────────────────────────
function switchNavTab(tabName) {
  currentTab = tabName;
  document.querySelectorAll(".segment-tab").forEach(tab => {
    tab.classList.toggle("active", tab.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-page").forEach(page => {
    page.classList.remove("active");
  });

  const activePage = document.getElementById(`tab${tabName.charAt(0).toUpperCase() + tabName.slice(1)}`);
  if (activePage) activePage.classList.add("active");

  if (tabName === "effects" && !document.getElementById("effectsGrid").children.length) {
    renderEffectsGrid();
  }
}

// ── WebSocket Connection ────────────────────────────────────────────────────
function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const tokParam = authToken ? `?token=${encodeURIComponent(authToken)}` : "";
  const wsUrl = `${protocol}//${location.host}/ws${tokParam}`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    document.getElementById("connStatus")?.classList.add("online");
    const connText = document.getElementById("connText");
    if (connText) connText.textContent = "Connected";
    clearTimeout(reconnectTimer);
    hideAuthModal();
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === "telemetry") {
        if (data.audio) lastAudioData = data.audio;
        if (data.zone_preview) lastZonePreview = data.zone_preview;
        return;
      }
      state = data;
      renderUI();
    } catch (e) {
      console.error("WS Parse error", e);
    }
  };

  ws.onclose = (ev) => {
    document.getElementById("connStatus")?.classList.remove("online");
    const connText = document.getElementById("connText");
    if (ev.code === 4401) {
      if (connText) connText.textContent = "Auth Required";
      showAuthModal();
    } else {
      if (connText) connText.textContent = "Reconnecting...";
      reconnectTimer = setTimeout(connectWebSocket, 2000);
    }
  };

  ws.onerror = () => {
    ws.close();
  };
}

// ── Initial State Fetch ─────────────────────────────────────────────────────
async function fetchInitialState() {
  try {
    const res = await fetch("/api/state", { headers: getAuthHeaders() });
    if (res.status === 401) {
      showAuthModal();
      return;
    }
    if (res.ok) {
      state = await res.json();
      renderUI();
      renderEffectsGrid();
    }
    fetchAudioDevices();
  } catch (err) {
    console.error("Fetch state error:", err);
  }
}

async function fetchAudioDevices() {
  try {
    const res = await fetch("/api/audio/devices", { headers: getAuthHeaders() });
    if (res.ok) {
      const data = await res.json();
      const sel = document.getElementById("audioDeviceSelect");
      if (sel && data.devices) {
        sel.innerHTML = "";
        data.devices.forEach(d => {
          const opt = document.createElement("option");
          opt.value = d.id;
          opt.textContent = d.name;
          if (d.name === data.selected || d.id === data.selected) opt.selected = true;
          sel.appendChild(opt);
        });
      }
    }
  } catch (err) {
    console.error("Fetch audio devices error:", err);
  }
}

// ── UI Rendering & State Sync ───────────────────────────────────────────────
function renderUI() {
  const devKeys = Object.keys(state.devices || {});
  if (!devKeys.length) return;

  if (currentDevId !== "all" && !state.devices[currentDevId]) {
    currentDevId = devKeys[0];
  }

  // 1. Render Device Tabs
  const tabsContainer = document.getElementById("deviceTabs");
  if (tabsContainer) {
    let tabsHtml = "";
    devKeys.forEach(k => {
      const dev = state.devices[k];
      const isAct = currentDevId === k ? "active" : "";
      tabsHtml += `
        <button class="device-tab ${isAct}" onclick="switchDevice('${k}')">
          <span>${dev.name.split('(')[0].trim()}</span>
          <span class="tab-badge">${dev.model}</span>
        </button>
      `;
    });
    tabsHtml += `
      <button class="device-tab ${currentDevId === 'all' ? 'active' : ''}" onclick="switchDevice('all')">
        <span>Both Strips</span>
        <span class="tab-badge">Sync All</span>
      </button>
    `;
    tabsContainer.innerHTML = tabsHtml;
  }

  // 2. Active Device Information
  const activeDev = getActiveDevice();
  if (!activeDev) return;

  const activeDevNameEl = document.getElementById("activeDevName");
  if (activeDevNameEl) activeDevNameEl.textContent = activeDev.name;

  const devBadgeEl = document.getElementById("devBadge");
  if (devBadgeEl) devBadgeEl.textContent = activeDev.model;

  const nowPlayingEl = document.getElementById("nowPlayingText");
  if (nowPlayingEl) {
    nowPlayingEl.textContent = formatName(activeDev.active_label || "Idle");
  }

  // Synchronize dynamic atmospheric theme with active look
  const theme = getThemeForLabel(activeDev.active_label);
  document.body.setAttribute("data-theme", theme);

  // Power Button
  const btnPwr = document.getElementById("btnDevicePower");
  const pwrLabel = document.getElementById("pwrLabel");
  if (btnPwr && pwrLabel) {
    btnPwr.classList.toggle("active", activeDev.power);
    pwrLabel.textContent = activeDev.power ? "ON" : "OFF";
  }

  // Master Power
  const anyOn = devKeys.some(k => state.devices[k].power);
  document.getElementById("btnMasterPower")?.classList.toggle("active", anyOn);

  // Brightness
  const brightSlider = document.getElementById("brightSlider");
  const brightVal = document.getElementById("brightVal");
  if (brightSlider && brightVal) {
    brightSlider.value = activeDev.brightness;
    brightVal.textContent = `${activeDev.brightness}%`;
  }

  // Music Reactive State
  const isMusicActive = (activeDev.active_label || "").toLowerCase().includes("audio");
  const btnMusicToggle = document.getElementById("btnMusicToggle");
  const musicToggleText = document.getElementById("musicToggleText");
  if (btnMusicToggle && musicToggleText) {
    btnMusicToggle.classList.toggle("active", isMusicActive);
    musicToggleText.textContent = isMusicActive ? "AUDIO SYNC ACTIVE" : "ENABLE AUDIO SYNC";
  }

  // Active Music Style Highlight
  const curAudioStyle = state.audio_style || "neon_drive";
  document.querySelectorAll(".style-card").forEach(card => {
    card.classList.toggle("active", isMusicActive && card.dataset.style === curAudioStyle);
  });

  // Screen Sync Toggle
  const isScreenActive = (activeDev.active_label || "").toLowerCase().includes("screen");
  const btnScreen = document.getElementById("btnScreenSync");
  const screenToggleText = document.getElementById("screenToggleText");
  if (btnScreen && screenToggleText) {
    btnScreen.classList.toggle("active", isScreenActive);
    screenToggleText.textContent = isScreenActive ? "SCREEN SYNC ACTIVE" : "ENABLE SCREEN SYNC";
  }

  // Dual-Strip Composite Mode
  const curComposite = state.composite_mode || "off";
  document.querySelectorAll("#compositeButtons .synergy-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.cmode === curComposite);
  });

  // Circadian
  const btnCircadian = document.getElementById("btnCircadianToggle");
  if (btnCircadian) {
    btnCircadian.textContent = state.circadian_enabled ? "☀️ Circadian: ON" : "☀️ Circadian: OFF";
    btnCircadian.style.borderColor = state.circadian_enabled ? "#3dd68c" : "";
  }

  // Active Effect Tuner Deck Visibility
  const tunerCard = document.getElementById("effectTunerCard");
  const curLabel = (activeDev.active_label || "").toLowerCase();
  const isEffectActive = curLabel && !isMusicActive && !isScreenActive && curLabel !== "idle";
  if (tunerCard) {
    if (isEffectActive) {
      tunerCard.style.display = "flex";
      document.getElementById("tunerEffectTitle").textContent = formatName(activeDev.active_label);
      document.querySelectorAll(".fx-card").forEach(c => {
        c.classList.toggle("active", c.dataset.eff === curLabel);
      });
    } else {
      tunerCard.style.display = "none";
      document.querySelectorAll(".fx-card").forEach(c => c.classList.remove("active"));
    }
  }

  // Presets
  renderPresetsGrid();
}

function getActiveDevice() {
  const devKeys = Object.keys(state.devices || {});
  if (!devKeys.length) return null;
  if (currentDevId === "all") {
    return {
      name: "All Strips",
      model: "DUAL SYNC",
      power: devKeys.some(k => state.devices[k].power),
      brightness: Math.round(devKeys.reduce((a, k) => a + state.devices[k].brightness, 0) / devKeys.length),
      active_label: devKeys.map(k => state.devices[k].active_label).filter((v, i, a) => a.indexOf(v) === i).join(" + ")
    };
  }
  return state.devices[currentDevId] || state.devices[devKeys[0]];
}

function switchDevice(devId) {
  currentDevId = devId;
  renderUI();
}

// ── Music Reactive Controls ─────────────────────────────────────────────────
function toggleMusicReactive() {
  apiPost(`/api/device/${currentDevId}/music`, {});
}

function selectMusicStyle(styleId) {
  apiPost(`/api/device/${currentDevId}/music/mode`, { mode: styleId });
  // If music reactivity isn't running yet, turn it on
  const activeDev = getActiveDevice();
  if (activeDev && !(activeDev.active_label || "").toLowerCase().includes("audio")) {
    apiPost(`/api/device/${currentDevId}/music`, {});
  }
}

function onSelectAudioDevice(devName) {
  apiPost(`/api/audio/select`, { device: devName });
}

let sensDebounce = null;
function onUpdateAudioSens(val) {
  document.getElementById("audioSensVal").textContent = `${parseFloat(val).toFixed(1)}×`;
  clearTimeout(sensDebounce);
  sensDebounce = setTimeout(() => {
    apiPost(`/api/device/${currentDevId}/music/sensitivity`, { sensitivity: parseFloat(val) });
  }, 50);
}

let capDebounce = null;
function onUpdateBrightCap(val) {
  document.getElementById("audioBrightCapVal").textContent = `${val}%`;
  clearTimeout(capDebounce);
  capDebounce = setTimeout(() => {
    apiPost(`/api/device/${currentDevId}/music/style_params`, { intensity: parseFloat(val) / 100.0 });
  }, 50);
}

function renderMusicStylesGrid() {
  const grid = document.getElementById("musicStylesGrid");
  if (!grid) return;

  grid.innerHTML = MUSIC_STYLES.map(s => `
    <div class="style-card" data-style="${s.id}" style="--card-glow: ${s.glow}; --card-glow-soft: ${s.glow}33" onclick="selectMusicStyle('${s.id}')">
      <div class="style-card-header">
        <span class="style-icon">${s.icon}</span>
        <span class="style-title">${s.name}</span>
      </div>
      <p class="style-desc">${s.desc}</p>
    </div>
  `).join("");
}

// ── Dynamic Effects ─────────────────────────────────────────────────────────
function filterEffects(category) {
  currentEffectFilter = category;
  document.querySelectorAll(".filter-pill").forEach(p => {
    p.classList.toggle("active", p.dataset.filter === category);
  });
  renderEffectsGrid();
}

function onSearchEffects(query) {
  effectSearchQuery = query.trim().toLowerCase();
  renderEffectsGrid();
}

function renderEffectsGrid() {
  const grid = document.getElementById("effectsGrid");
  if (!grid) return;

  const catalog = state.effects_catalog || {};
  let keys = Object.keys(catalog).filter(k => catalog[k]?.category !== "alias" && catalog[k]?.category !== "reactive");

  if (!keys.length) {
    keys = state.active_effects?.length ? state.active_effects : (state.effects_l930 || state.effects_l900 || Object.keys(EFFECT_GRADIENTS));
  }

  // Filter category
  if (currentEffectFilter === "ambient") {
    keys = keys.filter(k => catalog[k]?.group === "Ambient" || ["tide", "embers", "breathe", "drift", "golden_hour", "lava_lamp"].includes(k));
  } else if (currentEffectFilter === "motion") {
    keys = keys.filter(k => catalog[k]?.group === "Motion" || ["cyber_chase", "comet", "aurora", "deep_ocean", "raindrop"].includes(k));
  } else if (currentEffectFilter === "creative") {
    keys = keys.filter(k => catalog[k]?.dimension === "2D" || ["oil_slick", "silk_ribbons", "nebula_bloom", "holographic_moire", "bioluminescent_tide", "cyberpunk"].includes(k));
  }

  // Filter search
  if (effectSearchQuery) {
    keys = keys.filter(k => {
      const title = catalog[k]?.title || formatName(k);
      return k.toLowerCase().includes(effectSearchQuery) || title.toLowerCase().includes(effectSearchQuery);
    });
  }

  const activeLabel = (getActiveDevice()?.active_label || "").toLowerCase();

  grid.innerHTML = keys.map(k => {
    const meta = catalog[k] || {};
    const title = meta.title || meta.display_name || formatName(k);
    const grad = EFFECT_GRADIENTS[k] || "linear-gradient(135deg, #181b30, #2c3052)";
    const isActive = activeLabel === k.toLowerCase();
    const tag = meta.dimension === "2D" ? "2D Mapped" : (meta.group || "Dynamic");

    return `
      <div class="fx-card ${isActive ? 'active' : ''}" data-eff="${k}" onclick="applyEffect('${k}')">
        <div class="fx-card-thumb" style="--grad: ${grad}"></div>
        <div class="fx-card-title">${title}</div>
        <div class="fx-card-tag">${tag}</div>
      </div>
    `;
  }).join("");
}

function applyEffect(effName) {
  apiPost(`/api/device/${currentDevId}/effect`, { effect: effName });
}

let speedDebounce = null;
function updateFxSpeed(val) {
  document.getElementById("fxSpeedVal").textContent = `${parseFloat(val).toFixed(1)}×`;
  clearTimeout(speedDebounce);
  speedDebounce = setTimeout(() => {
    apiPost(`/api/device/${currentDevId}/effect_params`, { speed: parseFloat(val) });
  }, 60);
}

function updateFxPalette(val) {
  document.getElementById("fxPaletteVal").textContent = formatName(val);
  apiPost(`/api/device/${currentDevId}/effect_params`, { palette_name: val });
}

// ── Scenes & Presets ────────────────────────────────────────────────────────
const PRESETS = [
  { id: "work", name: "Work", icon: "💼" },
  { id: "focus", name: "Focus", icon: "🎯" },
  { id: "reading", name: "Reading", icon: "📖" },
  { id: "sunset", name: "Sunset", icon: "🌇" },
  { id: "dinner", name: "Dinner", icon: "🍷" },
  { id: "movie", name: "Movie", icon: "🍿" },
  { id: "sleep", name: "Sleep", icon: "🌙" },
  { id: "chill", name: "Chill", icon: "🛋️" }
];

function renderPresetsGrid() {
  const grid = document.getElementById("presetsGrid");
  if (!grid || grid.children.length) return;

  grid.innerHTML = PRESETS.map(p => `
    <button type="button" class="preset-btn" onclick="applyPreset('${p.id}')">
      <span class="preset-icon">${p.icon}</span>
      <span>${p.name}</span>
    </button>
  `).join("");
}

function applyPreset(name) {
  apiPost(`/api/device/${currentDevId}/mode`, { mode: name });
}

// ── Ambilight & Synergy ─────────────────────────────────────────────────────
function toggleScreenSync() {
  apiPost(`/api/device/${currentDevId}/screen`, {});
}

function setCompositeMode(mode) {
  apiPost(`/api/composite/mode`, { mode });
}

function toggleCircadian() {
  apiPost(`/api/circadian/toggle`, {});
}

// ── Optimized Animation Loop (Canvas Spectrum & Zone Preview) ───────────────
function startAnimationLoop() {
  const specCanvas = document.getElementById("audioSpectrumCanvas");
  const specCtx = specCanvas?.getContext("2d");
  const zoneCanvas = document.getElementById("zonePreviewCanvas");
  const zoneCtx = zoneCanvas?.getContext("2d");

  let smoothedBands = new Float32Array(50);

  function loop() {
    if (!isTabVisible) {
      animFrameId = null;
      return;
    }

    // 1. Draw Real-Time Audio Spectrum
    if (specCtx && specCanvas) {
      const w = specCanvas.width;
      const h = specCanvas.height;
      specCtx.clearRect(0, 0, w, h);

      if (lastAudioData && lastAudioData.bands && lastAudioData.bands.length) {
        const bands = lastAudioData.bands;
        const nBands = Math.min(50, bands.length);
        const barWidth = (w - (nBands - 1) * 2) / nBands;

        if (lastAudioData.bpm) {
          const bpmEl = document.getElementById("audioBpmPill");
          if (bpmEl) bpmEl.textContent = `${Math.round(lastAudioData.bpm)} BPM`;
        }

        for (let i = 0; i < nBands; i++) {
          const target = Math.max(0.04, Math.min(1.0, bands[i]));
          smoothedBands[i] += (target - smoothedBands[i]) * 0.32;

          const barH = smoothedBands[i] * (h - 6);
          const x = i * (barWidth + 2);
          const y = h - barH;

          // Color gradient across frequencies: Cyan -> Violet -> Rose
          const hue = 180 + (i / nBands) * 150;
          specCtx.fillStyle = `hsl(${hue}, 90%, 60%)`;
          specCtx.shadowColor = `hsl(${hue}, 90%, 55%)`;
          specCtx.shadowBlur = 6;
          specCtx.fillRect(x, y, barWidth, barH);
        }
        specCtx.shadowBlur = 0;
      } else {
        // Resting ambient wave
        const t = performance.now() * 0.002;
        specCtx.fillStyle = "rgba(139, 92, 246, 0.15)";
        for (let i = 0; i < 50; i++) {
          const barH = 4 + Math.sin(t + i * 0.2) * 3;
          const x = i * (w / 50);
          specCtx.fillRect(x, h - barH, (w / 50) - 2, barH);
        }
      }
    }

    // 2. Draw 50-Zone Addressable Hardware Preview
    if (zoneCtx && zoneCanvas && lastZonePreview && lastZonePreview.length) {
      const zw = zoneCanvas.width;
      const zh = zoneCanvas.height;
      zoneCtx.clearRect(0, 0, zw, zh);

      const numZones = lastZonePreview.length;
      const zoneW = zw / numZones;

      for (let i = 0; i < numZones; i++) {
        const [h, s, v] = lastZonePreview[i];
        zoneCtx.fillStyle = `hsl(${h}, ${s}%, ${v * 0.55}%)`;
        zoneCtx.fillRect(i * zoneW, 0, zoneW, zh);
      }
    }

    animFrameId = requestAnimationFrame(loop);
  }

  animFrameId = requestAnimationFrame(loop);
}

// ── Helpers & Utilities ─────────────────────────────────────────────────────
let brightDebounce = null;
function debouncedBrightness(val) {
  clearTimeout(brightDebounce);
  brightDebounce = setTimeout(() => {
    apiPost(`/api/device/${currentDevId}/brightness`, { brightness: val });
  }, 40);
}

function getAuthHeaders() {
  return authToken ? { "Authorization": `Bearer ${authToken}` } : {};
}

async function apiPost(endpoint, body) {
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...getAuthHeaders()
      },
      body: JSON.stringify(body)
    });
    if (res.status === 401) showAuthModal();
    return res;
  } catch (err) {
    console.error(`POST ${endpoint} failed:`, err);
  }
}

function submitAuthToken() {
  const input = document.getElementById("authTokenInput");
  if (!input) return;
  authToken = input.value.trim();
  localStorage.setItem("tapo_auth_token", authToken);
  hideAuthModal();
  connectWebSocket();
  fetchInitialState();
}

function showAuthModal() {
  const modal = document.getElementById("authModal");
  if (modal) modal.style.display = "flex";
}

function hideAuthModal() {
  const modal = document.getElementById("authModal");
  if (modal) modal.style.display = "none";
}

function formatName(str) {
  if (!str) return "";
  return str.split("_").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

function getThemeForLabel(label) {
  const l = (label || "").toLowerCase();
  if (l.includes("fire") || l.includes("ember")) return "fireplace";
  if (l.includes("aurora") || l.includes("northern")) return "northern_lights";
  if (l.includes("sakura") || l.includes("pink")) return "sakura";
  if (l.includes("gold") || l.includes("sunset") || l.includes("sunrise")) return "golden_hour";
  return "ambient_drift";
}

function hexToRgb(hex) {
  const clean = hex.replace("#", "");
  return [
    parseInt(clean.substring(0, 2), 16),
    parseInt(clean.substring(2, 4), 16),
    parseInt(clean.substring(4, 6), 16)
  ];
}

function rgbToHsv(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h, s, v = max;
  const d = max - min;
  s = max === 0 ? 0 : d / max;
  if (max === min) {
    h = 0;
  } else {
    switch (max) {
      case r: h = (g - b) / d + (g < b ? 6 : 0); break;
      case g: h = (b - r) / d + 2; break;
      case b: h = (r - g) / d + 4; break;
    }
    h /= 6;
  }
  return [Math.round(h * 360), Math.round(s * 100), Math.round(v * 100)];
}
