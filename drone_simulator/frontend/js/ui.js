/**
 * js/ui.js – UI controller: all button handlers, mode logic, log, WP mgmt
 */
const UI = (() => {
  const DRONE_COLORS = [
    '#00ff88','#00ccff','#ffaa00','#ff3344',
    '#aa88ff','#ff88cc','#88ffcc','#ffff44',
  ];
  let _colorIdx = 0;
  let _droneNum  = 1;
  let _wpAddActive = false;
  let _simFactor = 1;
  let _simStartT = null;
  let _simRaf   = null;

  // ── Lifecycle ─────────────────────────────────────────────────────────────
  function init() {
    // Clock
    setInterval(_updateClock, 1000);
    _updateClock();

    // Sim speed slider
    const slider = document.getElementById('sim-speed');
    slider.addEventListener('input', () => {
      _simFactor = parseFloat(slider.value);
      document.getElementById('sim-speed-v').textContent = _simFactor + '×';
    });

    // WS connect on load (optional – user can also press Connect)
    // WS.connect();  // uncomment to auto-connect
  }

  function connect() {
    const url = document.getElementById('srv-addr').value.trim();
    WS.connect(url);
  }

  // ── Drone management ─────────────────────────────────────────────────────
  function addDrone() {
    const center = Map3D.getMap().getCenter();
    const color  = DRONE_COLORS[_colorIdx % DRONE_COLORS.length];
    _colorIdx++;
    WS.send({
      type:  'add_drone',
      name:  `UAV-${String(_droneNum).padStart(2,'0')}`,
      color,
      lat:   center.lat,
      lon:   center.lng,
      alt:   0,
      armed: true,
    });
    _droneNum++;
  }

  function removeDrone(id) {
    WS.send({ type: 'remove_drone', drone_id: id });
  }

  function clearAll() {
    WS.send({ type: 'reset' });
  }

  // ── Flight modes ──────────────────────────────────────────────────────────
  function setMode(mode) {
    const d = DroneState.getSelected();
    if (!d) { log('Selecciona un dron primero', 'warn'); return; }

    const params = {};
    if (mode === 'ALT_HOLD') params.altitude = parseFloat(document.getElementById('p-alt').value);
    if (mode === 'RTL')      params.safe_alt  = parseFloat(document.getElementById('p-rtl-alt').value);

    WS.send({ type: 'set_mode', drone_id: d.id, mode, params });

    // Show/hide ACRO rate controls
    document.getElementById('acro-panel').style.display = mode === 'ACRO' ? 'block' : 'none';

    // Show mode label on map
    const ml = document.getElementById('mode-label');
    ml.textContent = `MODE: ${mode}`;
    ml.style.display = 'block';
    setTimeout(() => ml.style.display = 'none', 2500);

    refreshModeButtons(mode);
    log(`Modo → ${mode}`, 'info');
  }

  function refreshModeButtons(activeMode) {
    document.querySelectorAll('.btn-mode').forEach(b => {
      b.classList.toggle('active', b.dataset.mode === activeMode);
    });
    document.getElementById('acro-panel').style.display =
      activeMode === 'ACRO' ? 'block' : 'none';
  }

  // ── ACRO rate inputs ──────────────────────────────────────────────────────
  function acroInput(axis, value) {
    document.getElementById(`acro-${axis}-v`).textContent = value;
    const d = DroneState.getSelected();
    if (!d) return;
    WS.send({ type: 'acro_rates', drone_id: d.id, axis, rate: parseFloat(value) });
  }

  // ── Parameters ────────────────────────────────────────────────────────────
  function setSpeed(v) {
    const d = DroneState.getSelected();
    if (!d) return;
    WS.send({ type: 'set_speed', drone_id: d.id, speed: parseFloat(v) });
  }

  function setAltHold(v) {
    const d = DroneState.getSelected();
    if (!d) return;
    WS.send({ type: 'set_altitude_hold', drone_id: d.id, altitude: parseFloat(v) });
  }

  function setRTLAlt(v) {
    const d = DroneState.getSelected();
    if (d) d._rtl_safe_alt = parseFloat(v);
  }

  // ── Waypoints ─────────────────────────────────────────────────────────────
  function startAddWP() {
    const d = DroneState.getSelected();
    if (!d) { log('Selecciona un dron primero', 'warn'); return; }
    _wpAddActive = true;
    document.getElementById('btn-add-wp').classList.add('active');
    document.getElementById('click-mode').textContent = 'CLICK EN MAPA PARA WP · ESC cancela';
    document.getElementById('click-mode').style.display = 'block';

    Map3D.enterWpMode((lat, lon) => {
      const baseAlt = parseFloat(document.getElementById('p-alt').value) || 50;
      // Pedir altitud real del terreno al servidor y sumar la altura configurada
      WS.send({ type: 'get_elevation', lat, lon });
      const wpIdx = (DroneState.get(d.id)?.waypoints?.length || 0);

      // Añadir WP con altitud AGL configurada
      WS.send({ type: 'add_waypoint', drone_id: d.id,
                waypoint: { lat, lon, alt: baseAlt, wp_type: 'WAYPOINT' } });

      // Marker visual en el mapa con altitud
      Map3D.addWPMarker(lat, lon, baseAlt, wpIdx, d.color);
      log(`WP${wpIdx} → ${lat.toFixed(5)}, ${lon.toFixed(5)} @ ${baseAlt}m AGL`, 'info');
    });
  }

  function clearWPs() {
    const d = DroneState.getSelected();
    if (!d) return;
    WS.send({ type: 'plan_mission', drone_id: d.id, pattern: 'clear',
              waypoints: [] });
    Map3D.exitWpMode();
    renderWPList([]);
  }

  function renderWPList(wps) {
    const el = document.getElementById('wp-list');
    el.innerHTML = '';
    (wps || []).forEach((wp, i) => {
      const row = document.createElement('div');
      row.className = 'wp-item';
      row.innerHTML = `<span class="wp-num">WP${i}</span>
        <span>${wp.lat?.toFixed(5)}, ${wp.lon?.toFixed(5)}</span>
        <span style="color:var(--text-dim)">@${wp.alt}m</span>`;
      el.appendChild(row);
    });
  }

  // ── Mission planner ───────────────────────────────────────────────────────
  function planMission() {
    const d = DroneState.getSelected();
    if (!d) { log('Selecciona un dron primero', 'warn'); return; }
    const pattern = document.getElementById('pattern-sel').value;
    const alt     = parseFloat(document.getElementById('p-plan-alt').value);
    const center  = Map3D.getMap().getCenter();
    const bounds  = Map3D.getMap().getBounds();

    WS.send({
      type: 'plan_mission',
      drone_id: d.id,
      pattern,
      altitude: alt,
      origin: { lat: d.lat, lon: d.lon },
      target: { lat: center.lat + 0.01, lon: center.lng },
      centre: { lat: center.lat, lon: center.lng },
      bounds: { n: bounds.getNorth(), s: bounds.getSouth(),
                e: bounds.getEast(),  w: bounds.getWest() },
      n_drones: DroneState.getAll().length,
      drone_index: DroneState.getAll().findIndex(x => x.id === d.id),
    });
    log(`Planificando misión ${pattern}…`, 'info');
  }

  // ── Simulation ────────────────────────────────────────────────────────────
  function startSim() {
    if (!DroneState.getAll().length) { log('No hay drones', 'warn'); return; }
    WS.send({ type: 'start_simulation' });
    document.getElementById('btn-start').style.display = 'none';
    document.getElementById('btn-stop').style.display  = 'block';
    document.getElementById('sim-hud').style.display   = 'block';
    _simStartT = Date.now();
    log('▶ Simulación iniciada', 'warn');
  }

  function stopSim() {
    WS.send({ type: 'stop_simulation' });
    document.getElementById('btn-start').style.display = 'block';
    document.getElementById('btn-stop').style.display  = 'none';
    document.getElementById('sim-hud').style.display   = 'none';
    log('■ Simulación detenida');
  }

  // ── Takeoff ───────────────────────────────────────────────────────────────
  function takeoff() {
    const d = DroneState.getSelected();
    if (!d) { log('Selecciona un dron primero', 'warn'); return; }
    const alt = parseFloat(document.getElementById('p-takeoff-alt').value) || 30;
    WS.send({ type: 'mavlink_command', drone_id: d.id, command: 'TAKEOFF', params: { alt } });
    WS.send({ type: 'set_mode', drone_id: d.id, mode: 'LOITER', params: {} });
    log(`↑ TAKEOFF → ${alt}m [${d.name}]`, 'info');
    _showModeLabel('↑ TAKEOFF', 'var(--green)');
  }

  // ── Landing ───────────────────────────────────────────────────────────────
  function landing() {
    const d = DroneState.getSelected();
    if (!d) { log('Selecciona un dron primero', 'warn'); return; }
    WS.send({ type: 'set_mode', drone_id: d.id, mode: 'LAND', params: {} });
    log(`↓ LAND [${d.name}]`, 'warn');
    _showModeLabel('↓ LAND', 'var(--amber)');
  }

  // ── Area de vuelo ─────────────────────────────────────────────────────────
  let _areaCorners = [];

  function startDrawArea() {
    const d = DroneState.getSelected();
    if (!d) { log('Selecciona un dron primero', 'warn'); return; }
    _areaCorners = [];
    document.getElementById('btn-draw-area').classList.add('active');
    document.getElementById('area-coords').textContent = 'Click 1: esquina NW…';
    document.getElementById('click-mode').textContent = 'CLICK 1/2: ESQUINA NW del área [ESC cancela]';
    document.getElementById('click-mode').style.display = 'block';
    Map3D.getMap().getCanvas().style.cursor = 'crosshair';

    Map3D.enterWpMode((lat, lon) => {
      _areaCorners.push({ lat, lon });
      if (_areaCorners.length === 1) {
        document.getElementById('area-coords').textContent = `NW: ${lat.toFixed(4)},${lon.toFixed(4)} — click 2: SE`;
        document.getElementById('click-mode').textContent = 'CLICK 2/2: ESQUINA SE del área [ESC cancela]';
      } else if (_areaCorners.length === 2) {
        // Draw rectangle on map
        const [c1, c2] = _areaCorners;
        const bounds = {
          n: Math.max(c1.lat, c2.lat), s: Math.min(c1.lat, c2.lat),
          e: Math.max(c1.lon, c2.lon), w: Math.min(c1.lon, c2.lon),
        };
        Map3D.drawArea(bounds);
        const el = document.getElementById('area-coords');
        el.textContent = `NW:${bounds.n.toFixed(4)},${bounds.w.toFixed(4)} → SE:${bounds.s.toFixed(4)},${bounds.e.toFixed(4)}`;
        el.classList.add('defined');
        el._bounds = bounds;
        document.getElementById('btn-patrol').style.display = 'block';
        Map3D.exitWpMode();
        document.getElementById('btn-draw-area').classList.remove('active');
        log('Área de vuelo definida', 'info');
      }
    });
  }

  function clearArea() {
    _areaCorners = [];
    Map3D.clearArea();
    Map3D.exitWpMode();
    const el = document.getElementById('area-coords');
    el.textContent = 'Sin área definida';
    el.classList.remove('defined');
    el._bounds = null;
    document.getElementById('btn-patrol').style.display = 'none';
    document.getElementById('btn-draw-area').classList.remove('active');
    log('Área borrada');
  }

  function patrolArea() {
    const d = DroneState.getSelected();
    if (!d) { log('Selecciona un dron primero', 'warn'); return; }
    const el = document.getElementById('area-coords');
    if (!el._bounds) { log('Define un área primero', 'warn'); return; }
    const alt = parseFloat(document.getElementById('p-plan-alt').value) || 60;
    WS.send({
      type: 'plan_mission',
      drone_id: d.id,
      pattern: 'grid',
      altitude: alt,
      bounds: el._bounds,
      clearance: 30,
    });
    WS.send({ type: 'set_mode', drone_id: d.id, mode: 'AUTO', params: {} });
    log(`⟳ Patrulla de área iniciada [${d.name}]`, 'warn');
    _showModeLabel('⟳ PATROL AREA', 'var(--green)');
  }

  // ── Abort mission ────────────────────────────────────────────────────────
  function abortMission() {
    const d = DroneState.getSelected();
    if (!d) { log('Selecciona un dron primero', 'warn'); return; }

    // Gather rally point if set
    const rallyEl = document.getElementById('rally-coords');
    let msg = { type: 'abort_mission', drone_id: d.id };
    if (rallyEl && rallyEl._lat) {
      msg.rally_lat = rallyEl._lat;
      msg.rally_lon = rallyEl._lon;
      msg.rally_alt = parseFloat(document.getElementById('p-rtl-alt').value) || 60;
    }
    WS.send(msg);

    // Visual feedback
    const ml = document.getElementById('mode-label');
    ml.textContent = '⚠ ABORT — MISIÓN INTERRUMPIDA';
    ml.style.borderColor = 'var(--red)';
    ml.style.color = 'var(--red)';
    ml.style.display = 'block';
    setTimeout(() => {
      ml.style.display = 'none';
      ml.style.borderColor = '';
      ml.style.color = '';
    }, 4000);

    log('⚠ ABORT enviado — dron dirige a rally/home', 'err');
  }

  // ── Rally point ───────────────────────────────────────────────────────────
  function startSetRally() {
    const d = DroneState.getSelected();
    if (!d) { log('Selecciona un dron primero', 'warn'); return; }
    document.getElementById('btn-set-rally').classList.add('active');
    Map3D.enterWpMode((lat, lon) => {
      const alt = parseFloat(document.getElementById('p-rtl-alt').value) || 60;
      // Store on DOM element for abortMission to read
      const el = document.getElementById('rally-coords');
      el._lat = lat;
      el._lon = lon;
      el.textContent = `RALLY: ${lat.toFixed(5)}, ${lon.toFixed(5)}`;
      el.style.color = 'var(--amber)';
      // Send to server
      WS.send({ type: 'set_rally_point', drone_id: d.id, lat, lon, alt });
      log(`Rally point fijado: ${lat.toFixed(5)}, ${lon.toFixed(5)}`, 'warn');
      // Draw rally marker on map
      Map3D.setRallyMarker(lat, lon, d.color);
      Map3D.exitWpMode();
      document.getElementById('btn-set-rally').classList.remove('active');
    });
  }

  function clearRally() {
    const d = DroneState.getSelected();
    if (!d) return;
    const el = document.getElementById('rally-coords');
    el._lat = null; el._lon = null;
    el.textContent = 'Sin rally – usará HOME';
    el.style.color = '';
    WS.send({ type: 'set_rally_point', drone_id: d.id, lat: null, lon: null });
    Map3D.clearRallyMarker();
    log('Rally point eliminado');
  }

  // ── Map helpers (delegates to Map3D) ─────────────────────────────────────
  function toggle3D()   { Map3D.toggle3D(); }
  function toggleSat()  { Map3D.toggleSat(); }
  function tiltView()   { Map3D.tiltView(); }
  function resetNorth() { Map3D.resetNorth(); }
  function flyHome() {
    const d = DroneState.getSelected();
    if (d) Map3D.flyTo(d.lat, d.lon, 14);
    else Map3D.fitDrones(DroneState.getAll());
  }

  // ── FPV / Camera follow ───────────────────────────────────────────────────
  // Ciclo: LIBRE → FOLLOW (desde atrás) → FPV (desde morro) → LIBRE
  function toggleFPV() {
    const d = DroneState.getSelected();
    if (!d) { log('Selecciona un dron para activar FPV', 'warn'); return; }
    Map3D.toggleFollow(d.id);
    const btn = document.getElementById('btn-fpv');
    // Leer estado actual
    const badge = document.getElementById('fpv-badge');
    if (badge && badge.style.display !== 'none') {
      if (badge.textContent.includes('FOLLOW')) {
        btn.classList.add('active');
        btn.textContent = 'FPV1';
        log('🎥 Cámara FOLLOW activada — pulsa de nuevo para FPV frontal', 'info');
      } else if (badge.textContent.includes('FPV')) {
        btn.textContent = 'FPV2';
        log('📡 Vista FPV frontal activada — pulsa de nuevo para liberar cámara', 'info');
      }
    } else {
      btn.classList.remove('active');
      btn.textContent = 'FPV';
      log('Cámara libre');
    }
  }

  // ── Export ────────────────────────────────────────────────────────────────
  function exportMission() {
    const drones = DroneState.getAll();
    if (!drones.length) { log('Sin datos', 'warn'); return; }
    const lines = ['=== DRONE SIM MISSION EXPORT ===',
                   'Date: ' + new Date().toISOString(), ''];
    drones.forEach(d => {
      lines.push(`--- ${d.name} [${d.id}] ---`);
      lines.push(`  Mode: ${d.mode} | Speed: ${d.speed} m/s`);
      lines.push(`  Position: ${d.lat.toFixed(6)}, ${d.lon.toFixed(6)} @ ${d.alt.toFixed(0)}m`);
      lines.push('  Waypoints:');
      (d.waypoints||[]).forEach((wp,i) =>
        lines.push(`    WP${i}: ${wp.lat.toFixed(6)}, ${wp.lon.toFixed(6)} @ ${wp.alt}m`));
      lines.push('');
    });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([lines.join('\n')], {type:'text/plain'}));
    a.download = 'mission_' + Date.now() + '.txt';
    a.click();
    log('Misión exportada');
  }

  // ── Log ───────────────────────────────────────────────────────────────────
  function log(msg, level = '') {
    const el = document.getElementById('log-entries');
    const ts  = new Date().toTimeString().slice(0,8);
    const div = document.createElement('div');
    div.className = 'log-line ' + level;
    div.innerHTML = `<span class="log-ts">${ts}</span>${msg}`;
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
    // Cap at 200 lines
    while (el.children.length > 200) el.removeChild(el.firstChild);

    document.getElementById('status-bar').textContent = msg.slice(0, 60);
  }

  // ── Clock ─────────────────────────────────────────────────────────────────
  function _updateClock() {
    document.getElementById('clock').textContent =
      new Date().toUTCString().slice(17, 25) + ' UTC';
  }

  function _showModeLabel(text, color) {
    const ml = document.getElementById('mode-label');
    ml.textContent = text;
    ml.style.borderColor = color || 'var(--amber)';
    ml.style.color = color || 'var(--amber)';
    ml.style.display = 'block';
    setTimeout(() => { ml.style.display = 'none'; }, 3000);
  }

  return {
    init, connect,
    addDrone, removeDrone, clearAll,
    setMode, refreshModeButtons, acroInput,
    setSpeed, setAltHold, setRTLAlt,
    takeoff, landing,
    startAddWP, clearWPs, renderWPList,
    planMission,
    startSim, stopSim,
    abortMission, startSetRally, clearRally,
    startDrawArea, clearArea, patrolArea,
    toggle3D, toggleSat, tiltView, resetNorth, flyHome, toggleFPV,
    exportMission, log,
  };
})();