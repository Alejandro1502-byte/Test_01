/**
 * js/params_panel.js
 * Panel de parámetros ArduPilot en el frontend.
 * Permite editar los parámetros del autopiloto simulado
 * con los nombres estándar (WPNAV_SPEED, RTL_ALT, etc.)
 */
const ParamsPanel = (() => {

  const PARAM_GROUPS = {
    "Navegación (AUTO)": [
      { name: "WPNAV_SPEED",    label: "Velocidad WP",    unit: "cm/s", min: 50,  max: 2000, step: 50  },
      { name: "WPNAV_SPEED_UP", label: "Vel. subida",     unit: "cm/s", min: 50,  max: 500,  step: 25  },
      { name: "WPNAV_SPEED_DN", label: "Vel. bajada",     unit: "cm/s", min: 50,  max: 500,  step: 25  },
      { name: "WPNAV_ACCEL",    label: "Aceleración",     unit: "cm/s²",min: 50,  max: 1000, step: 50  },
      { name: "WPNAV_RADIUS",   label: "Radio WP",        unit: "cm",   min: 100, max: 1000, step: 50  },
    ],
    "RTL": [
      { name: "RTL_ALT",        label: "Altitud RTL",     unit: "cm",   min: 500, max: 8000, step: 100 },
      { name: "RTL_SPEED",      label: "Vel. RTL",        unit: "cm/s", min: 0,   max: 2000, step: 50  },
      { name: "RTL_LOIT_TIME",  label: "Loiter RTL",      unit: "ms",   min: 0,   max: 30000,step: 500 },
      { name: "RTL_CONE_SLOPE", label: "Cono RTL",        unit: "",     min: 0,   max: 10,   step: 0.5 },
    ],
    "LOITER": [
      { name: "LOIT_SPEED",     label: "Vel. máx Loiter", unit: "cm/s", min: 100, max: 2000, step: 50  },
      { name: "LOIT_ACC_MAX",   label: "Acel. Loiter",    unit: "cm/s²",min: 50,  max: 1000, step: 50  },
      { name: "LOIT_BRK_ACCEL", label: "Frenada",         unit: "cm/s²",min: 25,  max: 500,  step: 25  },
    ],
    "ACRO": [
      { name: "ACRO_ROLL_RATE", label: "Roll Rate",       unit: "°/s",  min: 10,  max: 720,  step: 10  },
      { name: "ACRO_PITCH_RATE",label: "Pitch Rate",      unit: "°/s",  min: 10,  max: 720,  step: 10  },
      { name: "ACRO_YAW_RATE",  label: "Yaw Rate",        unit: "°/s",  min: 10,  max: 360,  step: 5   },
      { name: "ACRO_EXPO",      label: "Expo",            unit: "",     min: 0,   max: 1,    step: 0.05},
    ],
    "Failsafe": [
      { name: "BATT_LOW_VOLT",  label: "Batería baja",    unit: "V",    min: 10,  max: 25,   step: 0.1 },
      { name: "BATT_CRT_VOLT",  label: "Batería crítica", unit: "V",    min: 9,   max: 24,   step: 0.1 },
      { name: "BATT_FAILSAFE",  label: "Acción failsafe", unit: "",     min: 0,   max: 3,    step: 1,
        options: {0:"Ninguna", 1:"Warning", 2:"RTL", 3:"Land"} },
      { name: "FENCE_ENABLE",   label: "Geofence",        unit: "",     min: 0,   max: 1,    step: 1,
        options: {0:"Desactivado", 1:"Activado"} },
      { name: "FENCE_RADIUS",   label: "Radio geofence",  unit: "m",    min: 50,  max: 5000, step: 50  },
      { name: "FENCE_ALT_MAX",  label: "Alt. máx geofence",unit:"m",   min: 20,  max: 500,  step: 10  },
    ],
  };

  // Current values per drone
  const _values = {};   // droneId → { PARAM_NAME: value }

  // ── Build panel DOM ──────────────────────────────────────────────────────
  function buildPanel() {
    const modal = document.createElement('div');
    modal.id = 'params-modal';
    modal.innerHTML = `
      <div class="params-overlay" onclick="ParamsPanel.hide()"></div>
      <div class="params-box">
        <div class="params-header">
          <span class="params-title">◈ ARDUPILOT PARAMETERS</span>
          <span class="params-drone-name" id="pp-drone-name">—</span>
          <button class="params-close" onclick="ParamsPanel.hide()">✕</button>
        </div>
        <div class="params-body" id="pp-body"></div>
        <div class="params-footer">
          <button class="btn-action btn-green" onclick="ParamsPanel.saveAll()" style="width:auto;padding:6px 20px">
            ✓ APLICAR
          </button>
          <button class="btn-action btn-amber" onclick="ParamsPanel.resetDefaults()" style="width:auto;padding:6px 20px">
            ↺ DEFAULTS
          </button>
          <span id="pp-status" style="font-size:9px;color:var(--green-dim)"></span>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.style.display = 'none';

    // Inject styles
    const style = document.createElement('style');
    style.textContent = `
      #params-modal { position:fixed; inset:0; z-index:1000; display:flex; align-items:center; justify-content:center; }
      .params-overlay { position:absolute; inset:0; background:rgba(0,0,0,0.75); backdrop-filter:blur(3px); }
      .params-box {
        position:relative; z-index:1;
        width:580px; max-height:80vh;
        background:var(--panel); border:1px solid var(--green);
        display:flex; flex-direction:column;
        box-shadow: 0 0 40px rgba(0,255,136,0.15);
      }
      .params-header {
        display:flex; align-items:center; gap:12px;
        padding:10px 14px; border-bottom:1px solid var(--border);
        flex-shrink:0;
      }
      .params-title { font-family:'Orbitron',monospace; font-size:10px; letter-spacing:3px; color:var(--green-dim); }
      .params-drone-name { font-family:'Orbitron',monospace; font-size:11px; font-weight:700; color:var(--green); flex:1; }
      .params-close { background:none; border:none; color:var(--text-dim); cursor:pointer; font-size:14px; }
      .params-close:hover { color:var(--red); }
      .params-body { flex:1; overflow-y:auto; padding:10px 14px; }
      .params-body::-webkit-scrollbar { width:3px; }
      .params-body::-webkit-scrollbar-thumb { background:var(--border); }
      .pp-group { margin-bottom:16px; }
      .pp-group-title {
        font-family:'Orbitron',monospace; font-size:8px; letter-spacing:3px;
        color:var(--green-dim); margin-bottom:8px;
        padding-bottom:4px; border-bottom:1px solid var(--border);
      }
      .pp-row {
        display:grid; grid-template-columns:1fr 130px 50px;
        align-items:center; gap:8px;
        padding:4px 0; border-bottom:1px solid rgba(26,58,37,0.3);
        font-size:10px;
      }
      .pp-label { color:var(--text); }
      .pp-name  { color:var(--text-dim); font-size:8px; display:block; }
      .pp-input {
        background:var(--bg); border:1px solid var(--border);
        color:var(--green); font-family:'Share Tech Mono',monospace;
        font-size:10px; padding:3px 6px; text-align:right; width:100%; outline:none;
      }
      .pp-input:focus { border-color:var(--green); }
      .pp-unit { color:var(--text-dim); font-size:9px; text-align:left; }
      .params-footer {
        display:flex; align-items:center; gap:8px; padding:8px 14px;
        border-top:1px solid var(--border); flex-shrink:0;
      }
    `;
    document.head.appendChild(style);
    return modal;
  }

  // ── Show / hide ──────────────────────────────────────────────────────────
  function show(droneId) {
    const drone = DroneState.get(droneId);
    if (!drone) return;

    let modal = document.getElementById('params-modal');
    if (!modal) modal = buildPanel();

    // Set title
    document.getElementById('pp-drone-name').textContent = drone.name + ' [' + droneId + ']';
    modal._droneId = droneId;

    // Ensure values exist
    if (!_values[droneId]) {
      _values[droneId] = _defaultValues();
    }

    // Render param rows
    const body = document.getElementById('pp-body');
    body.innerHTML = '';

    Object.entries(PARAM_GROUPS).forEach(([groupName, params]) => {
      const grp = document.createElement('div');
      grp.className = 'pp-group';
      grp.innerHTML = `<div class="pp-group-title">${groupName}</div>`;

      params.forEach(p => {
        const val = _values[droneId][p.name] ?? p.options ? Object.keys(p.options)[0] : p.min;
        const row = document.createElement('div');
        row.className = 'pp-row';

        let input;
        if (p.options) {
          input = `<select class="pp-input" data-param="${p.name}">
            ${Object.entries(p.options).map(([k,v]) =>
              `<option value="${k}" ${val == k ? 'selected':''}>${v}</option>`
            ).join('')}
          </select>`;
        } else {
          input = `<input type="number" class="pp-input" data-param="${p.name}"
            value="${val}" min="${p.min}" max="${p.max}" step="${p.step}">`;
        }

        row.innerHTML = `
          <div><span class="pp-label">${p.label}</span><span class="pp-name">${p.name}</span></div>
          ${input}
          <span class="pp-unit">${p.unit}</span>`;
        grp.appendChild(row);
      });

      body.appendChild(grp);
    });

    modal.style.display = 'flex';
    document.getElementById('pp-status').textContent = '';
  }

  function hide() {
    const m = document.getElementById('params-modal');
    if (m) m.style.display = 'none';
  }

  // ── Save / reset ─────────────────────────────────────────────────────────
  function saveAll() {
    const modal = document.getElementById('params-modal');
    const droneId = modal?._droneId;
    if (!droneId) return;

    const params = {};
    modal.querySelectorAll('[data-param]').forEach(el => {
      params[el.dataset.param] = parseFloat(el.value);
    });

    _values[droneId] = Object.assign(_values[droneId] || {}, params);

    WS.send({
      type: 'mavlink_command',
      drone_id: droneId,
      command: 'SET_PARAMS',
      params,
    });

    document.getElementById('pp-status').textContent = '✓ Parámetros enviados';
    setTimeout(() => {
      const s = document.getElementById('pp-status');
      if (s) s.textContent = '';
    }, 2000);

    UI.log(`Parámetros actualizados [${droneId}]: ${Object.keys(params).length} params`, 'info');
  }

  function resetDefaults() {
    const modal = document.getElementById('params-modal');
    const droneId = modal?._droneId;
    if (!droneId) return;
    _values[droneId] = _defaultValues();
    show(droneId);  // re-render
    document.getElementById('pp-status').textContent = '↺ Defaults restaurados';
  }

  // ── Defaults ─────────────────────────────────────────────────────────────
  function _defaultValues() {
    const vals = {};
    Object.values(PARAM_GROUPS).flat().forEach(p => {
      vals[p.name] = p.options ? parseFloat(Object.keys(p.options)[0]) : p.min + (p.max - p.min) * 0.3;
    });
    // Override with known ArduPilot defaults
    const DEFAULTS = {
      WPNAV_SPEED: 500, WPNAV_SPEED_UP: 250, WPNAV_SPEED_DN: 150,
      WPNAV_ACCEL: 250, WPNAV_RADIUS: 200,
      RTL_ALT: 1500, RTL_SPEED: 0, RTL_LOIT_TIME: 5000, RTL_CONE_SLOPE: 3,
      LOIT_SPEED: 1250, LOIT_ACC_MAX: 500, LOIT_BRK_ACCEL: 250,
      ACRO_ROLL_RATE: 180, ACRO_PITCH_RATE: 180, ACRO_YAW_RATE: 90, ACRO_EXPO: 0.3,
      BATT_LOW_VOLT: 14.0, BATT_CRT_VOLT: 13.5, BATT_FAILSAFE: 2,
      FENCE_ENABLE: 0, FENCE_RADIUS: 300, FENCE_ALT_MAX: 100,
    };
    return Object.assign(vals, DEFAULTS);
  }

  return { show, hide, saveAll, resetDefaults };
})();