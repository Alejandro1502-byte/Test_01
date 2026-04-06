/**
 * js/drone_state.js
 * Client-side registry of all drone states received from the server.
 * Drives the telemetry cards, map markers, and sidebar fleet list.
 */
const DroneState = (() => {
  const _drones = {};   // id → state object
  let _selected = null; // currently selected drone id

  // ── WS message handlers ──────────────────────────────────────────────────
  WS.on('hello', msg => {
    (msg.drones || []).forEach(d => _upsert(d));
    _renderFleet();
    _renderCards();
  });

  WS.on('drone_added', msg => {
    _upsert(msg.drone);
    Map3D.addDroneMarker(msg.drone);
    _renderFleet();
    _renderCards();
    UI.log(`Drone añadido: ${msg.drone.name} [${msg.drone.id}]`, 'info');
    // Auto-seleccionar si es el primero o no hay selección
    if (!_selected) select(msg.drone.id);
  });

  WS.on('drone_removed', msg => {
    delete _drones[msg.drone_id];
    Map3D.removeDroneMarker(msg.drone_id);
    if (_selected === msg.drone_id) select(null);
    _renderFleet();
    _renderCards();
  });

  WS.on('telemetry_batch', msg => {
    (msg.drones || []).forEach(d => {
      _upsert(d);
      Map3D.updateDroneMarker(d);
    });
    _updateCards();
    HUD.updateBatch(msg);
  });

  WS.on('mode_changed', msg => {
    if (_drones[msg.drone_id]) {
      _drones[msg.drone_id].mode  = msg.mode;
      _drones[msg.drone_id].phase = msg.phase || _drones[msg.drone_id].phase;
    }
    _renderFleet();
    if (msg.drone_id === _selected) UI.refreshModeButtons(msg.mode);
  });

  WS.on('mission_planned', msg => {
    const d = _drones[msg.result.drone_id];
    if (d) {
      d.waypoints = msg.result.waypoints;
      Map3D.updateWaypointLayer(d.id, d.waypoints, d.color);
      UI.renderWPList(d.waypoints);
      UI.log(`Misión planificada: ${d.waypoints.length} WPs`, 'info');
    }
  });

  WS.on('waypoint_added', msg => {
    const d = _drones[msg.drone_id];
    if (d) {
      d.waypoints = d.waypoints || [];
      d.waypoints.push(msg.waypoint);
      Map3D.updateWaypointLayer(d.id, d.waypoints, d.color);
      UI.renderWPList(d.waypoints);
    }
  });

  WS.on('reset', () => {
    Object.keys(_drones).forEach(id => {
      Map3D.removeDroneMarker(id);
      delete _drones[id];
    });
    _selected = null;
    _renderFleet();
    _renderCards();
    UI.log('Sistema reiniciado', 'warn');
  });

  // ── Internal helpers ─────────────────────────────────────────────────────
  function _upsert(d) {
    _drones[d.id] = Object.assign(_drones[d.id] || {}, d);
  }

  // ── Selection ────────────────────────────────────────────────────────────
  function select(id) {
    _selected = id;
    _renderFleet();
    const d = _drones[id];
    if (d) {
      document.getElementById('drone-controls').style.display = 'block';
      document.getElementById('sel-name').textContent = d.name;
      UI.refreshModeButtons(d.mode);
      UI.renderWPList(d.waypoints || []);
      document.getElementById('p-speed').value = d.speed || 12;
      Map3D.flyTo(d.lat, d.lon, 14);
    } else {
      document.getElementById('drone-controls').style.display = 'none';
    }
  }

  // ── Fleet list ────────────────────────────────────────────────────────────
  function _renderFleet() {
    const el = document.getElementById('fleet-list');
    el.innerHTML = '';
    Object.values(_drones).forEach(d => {
      const item = document.createElement('div');
      item.className = 'fleet-item' + (d.id === _selected ? ' selected' : '');
      item.innerHTML = `
        <div class="fleet-color" style="background:${d.color}"></div>
        <div class="fleet-name">${d.name}</div>
        <div class="fleet-mode">${d.mode || '—'}</div>
        <button class="fleet-del" title="Remove" onclick="event.stopPropagation();UI.removeDrone('${d.id}')">✕</button>`;
      item.addEventListener('click', () => select(d.id));
      el.appendChild(item);
    });
  }

  // ── Telemetry cards ───────────────────────────────────────────────────────
  function _renderCards() {
    const wrap = document.getElementById('drone-cards');
    const empty = document.getElementById('empty-state');
    const dlist = Object.values(_drones);
    empty.style.display = dlist.length ? 'none' : 'block';
    wrap.innerHTML = '';
    dlist.forEach(d => {
      wrap.innerHTML += _cardHTML(d);
    });
  }

  function _updateCards() {
    Object.values(_drones).forEach(d => {
      // Update live values without full re-render
      const spd   = document.getElementById(`cv-spd-${d.id}`);
      const alt   = document.getElementById(`cv-alt-${d.id}`);
      const bat   = document.getElementById(`cv-bat-${d.id}`);
      const hdg   = document.getElementById(`cv-hdg-${d.id}`);
      const ph    = document.getElementById(`cv-phase-${d.id}`);
      const vz    = document.getElementById(`cv-vz-${d.id}`);
      const abf   = document.getElementById(`alt-bar-fill-${d.id}`);
      const wpBar = document.getElementById(`wp-bar-fill-${d.id}`);
      const card  = document.getElementById(`card-${d.id}`);

      if (!spd) { _renderCards(); return; }  // card doesn't exist yet

      spd.textContent   = d.speed?.toFixed(1) + ' m/s';
      alt.textContent   = d.alt?.toFixed(0)   + ' m';
      bat.textContent   = d.battery?.toFixed(0) + '%';
      hdg.textContent   = d.yaw?.toFixed(0)   + '°';
      if (ph)    ph.textContent  = d.phase || '—';
      if (vz)    vz.textContent  = (d.vz >= 0 ? '+' : '') + d.vz?.toFixed(1) + ' m/s';
      if (abf)   abf.style.width = Math.min(100, (d.alt / 300) * 100) + '%';
      if (wpBar && d.wp_total > 0)
        wpBar.style.width = (d.wp_idx / d.wp_total * 100) + '%';

      if (card) {
        card.className = 'drone-card ' + _cardClass(d.mode);
      }

      // Mode badge
      const mb = document.getElementById(`mode-badge-${d.id}`);
      if (mb) {
        mb.textContent  = d.mode || '—';
        mb.className    = `dc-mode ${d.mode}`;
      }
    });
  }

  function _cardClass(mode) {
    const map = { ACRO:'acro', RTL:'rtl', LOITER:'flying', AUTO:'flying', ALT_HOLD:'flying', IDLE:'landed' };
    return map[mode] || 'flying';
  }

  function _cardHTML(d) {
    const altPct = Math.min(100, (d.alt / 300) * 100);
    const wpPct  = d.wp_total > 0 ? (d.wp_idx / d.wp_total * 100) : 0;
    return `
    <div class="drone-card ${_cardClass(d.mode)}" id="card-${d.id}">
      <div class="dc-hdr">
        <span class="dc-id" style="color:${d.color}">${d.name}</span>
        <span class="dc-mode ${d.mode}" id="mode-badge-${d.id}">${d.mode}</span>
      </div>
      <div class="dc-metrics">
        <span class="dc-label">SPD</span><span class="dc-val live" id="cv-spd-${d.id}">${(d.speed||0).toFixed(1)} m/s</span>
        <span class="dc-label">ALT</span><span class="dc-val live" id="cv-alt-${d.id}">${(d.alt||0).toFixed(0)} m</span>
        <span class="dc-label">HDG</span><span class="dc-val"       id="cv-hdg-${d.id}">${(d.yaw||0).toFixed(0)}°</span>
        <span class="dc-label">V/S</span><span class="dc-val"       id="cv-vz-${d.id}">${(d.vz||0).toFixed(1)} m/s</span>
        <span class="dc-label">BAT</span><span class="dc-val"       id="cv-bat-${d.id}">${(d.battery||100).toFixed(0)}%</span>
        <span class="dc-label">GPS</span><span class="dc-val">${d.gps_sats||0} sat</span>
      </div>
      <div class="dc-label" style="font-size:8px;margin-bottom:2px" id="cv-phase-${d.id}">${d.phase||'—'}</div>
      <div class="alt-bar-wrap">
        <span>ALT</span>
        <div class="alt-bar"><div class="alt-bar-fill" id="alt-bar-fill-${d.id}"
          style="width:${altPct}%;background:${d.color}"></div></div>
        <span>${(d.alt||0).toFixed(0)}m</span>
      </div>
      <div class="wp-progress-row">
        <span>WP ${d.wp_idx||0}/${d.wp_total||0}</span>
        <div class="wp-bar"><div class="wp-bar-fill" id="wp-bar-fill-${d.id}"
          style="width:${wpPct}%"></div></div>
      </div>
    </div>`;
  }

  // ── Public API ────────────────────────────────────────────────────────────
  function getSelected()  { return _selected ? _drones[_selected] : null; }
  function getAll()       { return Object.values(_drones); }
  function get(id)        { return _drones[id]; }

  return { select, getSelected, getAll, get };
})();