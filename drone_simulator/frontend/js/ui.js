/**
 * ui.js — Flujo simplificado:
 * 1. Pulsa TAKEOFF → click en mapa → drones aparecen en formación
 * 2. Pulsa LANDING → click en mapa → destino de aterrizaje
 * 3. INICIAR SIM → vuelan solos
 * 4. ABORT → todos vuelven al punto de takeoff
 */
const UI = (() => {

  let _mode       = null;   // 'takeoff' | 'landing' | 'waypoint'
  let _tkPoint    = null;   // {lat, lon}
  let _ldPoint    = null;
  let _formation  = 'line';
  let _clickFn    = null;   // función registrada en el mapa

  // ── Init ──────────────────────────────────────────────────────────────────
  function init() {
    setInterval(_tick, 1000);
    _tick();

    document.getElementById('sim-speed').addEventListener('input', e => {
      const v = e.target.value;
      document.getElementById('sim-speed-v').textContent = v + '×';
    });

    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') _cancelMode();
    });
  }

  function _tick() {
    const el = document.getElementById('clock');
    if (el) el.textContent = new Date().toUTCString().slice(17,25) + ' UTC';
  }

  // ── Conexión ──────────────────────────────────────────────────────────────
  function connect() {
    WS.connect(document.getElementById('srv-addr').value.trim());
  }

  // ── Modo de click en mapa ─────────────────────────────────────────────────
  function _enterMapClick(mode, bannerText, color) {
    // Cancelar modo anterior si había
    _cancelMode();
    _mode = mode;

    // Banner visible en el mapa
    const banner = document.getElementById('click-banner');
    banner.style.borderColor = color || 'var(--green)';
    banner.style.color       = color || 'var(--green)';
    document.getElementById('click-banner-text').textContent = bannerText;
    banner.style.display = 'flex';

    Map3D.getMap().getCanvas().style.cursor = 'crosshair';

    // Registrar click UNA sola vez (excepto waypoint que se repite)
    _clickFn = e => {
      _handleClick(e.lngLat.lat, e.lngLat.lng);
      if (mode !== 'waypoint') {
        // Para takeoff y landing: un solo click, luego cancelar
        Map3D.getMap().off('click', _clickFn);
        _clickFn = null;
      } else {
        // Para waypoint: re-registrar para el siguiente
        Map3D.getMap().once('click', _clickFn);
      }
    };

    if (mode === 'waypoint') {
      Map3D.getMap().once('click', _clickFn);
    } else {
      Map3D.getMap().once('click', _clickFn);
    }
  }

  function _cancelMode() {
    if (_clickFn) {
      Map3D.getMap().off('click', _clickFn);
      _clickFn = null;
    }
    _mode = null;
    document.getElementById('click-banner').style.display = 'none';
    Map3D.getMap().getCanvas().style.cursor = '';
    // Quitar activo de botones
    document.getElementById('btn-takeoff')?.classList.remove('active');
    document.getElementById('btn-landing')?.classList.remove('active');
    document.getElementById('btn-add-wp')?.classList.remove('active');
  }

  function _handleClick(lat, lon) {
    if (_mode === 'takeoff') {
      _setTakeoff(lat, lon);
    } else if (_mode === 'landing') {
      _setLanding(lat, lon);
    } else if (_mode === 'waypoint') {
      _addWaypoint(lat, lon);
    }
    if (_mode !== 'waypoint') _cancelMode();
  }

  // ── TAKEOFF ───────────────────────────────────────────────────────────────
  function activateTakeoff() {
    const btn = document.getElementById('btn-takeoff');
    if (_mode === 'takeoff') { _cancelMode(); return; }
    btn.classList.add('active');
    _enterMapClick('takeoff', '↑  CLICK = PUNTO DE DESPEGUE', '#00ff88');
    log('Click en el mapa para fijar el punto de takeoff', 'info');
  }

  function _setTakeoff(lat, lon) {
    _tkPoint = { lat, lon };

    // Actualizar info
    const info = document.getElementById('tk-info');
    info.textContent = `✓ ${lat.toFixed(5)}, ${lon.toFixed(5)}`;
    info.classList.add('done');

    // Marker en mapa
    Map3D.setTakeoffMarker(lat, lon);

    // Mandar al servidor
    WS.send({ type: 'set_takeoff_point', lat, lon });

    log(`✦ Takeoff: ${lat.toFixed(5)}, ${lon.toFixed(5)}`, 'info');
    _showLabel('↑ TAKEOFF FIJADO', '#00ff88');
  }

  // ── LANDING ───────────────────────────────────────────────────────────────
  function activateLanding() {
    const btn = document.getElementById('btn-landing');
    if (_mode === 'landing') { _cancelMode(); return; }
    btn.classList.add('active');
    _enterMapClick('landing', '↓  CLICK = PUNTO DE ATERRIZAJE', '#ffaa00');
    log('Click en el mapa para fijar el punto de landing', 'info');
  }

  function _setLanding(lat, lon) {
    _ldPoint = { lat, lon };

    const info = document.getElementById('ld-info');
    info.textContent = `✓ ${lat.toFixed(5)}, ${lon.toFixed(5)}`;
    info.classList.add('done');

    Map3D.setLandingMarker(lat, lon);
    WS.send({ type: 'set_landing_point', lat, lon });

    log(`✦ Landing: ${lat.toFixed(5)}, ${lon.toFixed(5)}`, 'info');
    _showLabel('↓ LANDING FIJADO', '#ffaa00');
  }

  // ── FORMACIÓN ─────────────────────────────────────────────────────────────
  function selectFormation(btn, f) {
    document.querySelectorAll('.btn-formation').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    _formation = f;
    log('Formación: ' + f.toUpperCase());
  }

  // ── INICIAR SIM ───────────────────────────────────────────────────────────
  function startSim() {
    if (!_tkPoint) {
      log('⚠ Primero fija el punto de TAKEOFF', 'warn');
      _showLabel('⚠ DEFINE EL TAKEOFF', '#ffaa00');
      return;
    }

    const n   = parseInt(document.getElementById('p-ndrones').value) || 1;
    const alt = parseFloat(document.getElementById('p-alt').value)   || 50;
    const spd = parseFloat(document.getElementById('p-speed').value) || 10;
    const landing = _ldPoint || { lat: _tkPoint.lat + 0.005, lon: _tkPoint.lon };

    // Lanzar formación en el servidor
    WS.send({
      type:      'formation_launch',
      takeoff:   _tkPoint,
      landing,
      formation: _formation,
      n_drones:  n,
      altitude:  alt,
      speed:     spd,
    });

    // Arrancar simulación
    WS.send({ type: 'start_simulation' });

    document.getElementById('btn-start').style.display = 'none';
    document.getElementById('btn-stop').style.display  = 'block';
    document.getElementById('sim-hud').style.display   = 'block';

    log(`▶ ${n} drones · formación ${_formation} · ${alt}m · ${spd}m/s`, 'warn');
    _showLabel(`▶ ${n} DRONES EN VUELO`, '#00ff88');
  }

  function stopSim() {
    WS.send({ type: 'stop_simulation' });
    document.getElementById('btn-start').style.display = 'block';
    document.getElementById('btn-stop').style.display  = 'none';
    document.getElementById('sim-hud').style.display   = 'none';
    log('■ Simulación detenida');
  }

  // ── ABORT — todos al takeoff ──────────────────────────────────────────────
  function abortAll() {
    WS.send({ type: 'abort_all', home: _tkPoint });
    log('⚠ ABORT — todos los drones vuelven al takeoff', 'err');
    _showLabel('⚠ ABORT — RTL TODOS', '#ff3344');
  }

  // ── CLEAR ─────────────────────────────────────────────────────────────────
  function clearAll() {
    WS.send({ type: 'reset' });
    WS.send({ type: 'stop_simulation' });
    _tkPoint = null; _ldPoint = null;
    document.getElementById('tk-info').textContent = 'Sin definir — pulsa el botón y haz click en el mapa';
    document.getElementById('tk-info').classList.remove('done');
    document.getElementById('ld-info').textContent = 'Sin definir — pulsa el botón y haz click en el mapa';
    document.getElementById('ld-info').classList.remove('done');
    document.getElementById('btn-start').style.display = 'block';
    document.getElementById('btn-stop').style.display  = 'none';
    document.getElementById('sim-hud').style.display   = 'none';
    Map3D.clearMissionMarkers();
    _cancelMode();
    log('Limpiado', 'warn');
  }

  // ── WAYPOINTS extra ───────────────────────────────────────────────────────
  function activateWaypoint() {
    if (_mode === 'waypoint') { _cancelMode(); return; }
    document.getElementById('btn-add-wp')?.classList.add('active');
    _enterMapClick('waypoint', '✛  CLICK = AÑADIR WAYPOINT', '#00ccff');
    log('Click en el mapa para añadir waypoints. ESC para terminar.', 'info');
  }

  function _addWaypoint(lat, lon) {
    const d = DroneState.getSelected();
    if (!d) return;
    const alt   = parseFloat(document.getElementById('p-alt')?.value) || 50;
    const wpIdx = d.waypoints?.length || 0;
    WS.send({ type: 'add_waypoint', drone_id: d.id,
              waypoint: { lat, lon, alt, wp_type: 'WAYPOINT' } });
    Map3D.addWPMarker(lat, lon, alt, wpIdx, d.color);
    log(`WP${wpIdx} → ${lat.toFixed(4)}, ${lon.toFixed(4)} @ ${alt}m`);
  }

  function clearWPs() {
    const d = DroneState.getSelected();
    if (!d) return;
    WS.send({ type: 'plan_mission', drone_id: d.id, pattern: 'clear', waypoints: [] });
    document.getElementById('wp-list').innerHTML = '';
    _cancelMode();
  }

  function renderWPList(wps) {
    const el = document.getElementById('wp-list');
    if (!el) return;
    el.innerHTML = (wps || []).map((wp, i) =>
      `<div class="wp-item">
        <span class="wp-num">WP${i}</span>
        <span>${wp.lat?.toFixed(4)}, ${wp.lon?.toFixed(4)}</span>
        <span style="color:var(--text-dim)">@${wp.alt}m</span>
      </div>`
    ).join('');
  }

  // ── Modos individuales ────────────────────────────────────────────────────
  function setMode(mode) {
    const d = DroneState.getSelected();
    if (!d) return;
    WS.send({ type: 'set_mode', drone_id: d.id, mode, params: {} });
    refreshModeButtons(mode);
    log(`MODE → ${mode} [${d.name}]`);
  }

  function refreshModeButtons(active) {
    document.querySelectorAll('.btn-mode').forEach(b =>
      b.classList.toggle('active', b.dataset.mode === active));
  }

  function setSpeed(v) {
    const d = DroneState.getSelected();
    if (d) WS.send({ type: 'set_speed', drone_id: d.id, speed: parseFloat(v) });
  }

  function setAltHold(v) {
    const d = DroneState.getSelected();
    if (d) WS.send({ type: 'set_altitude_hold', drone_id: d.id, altitude: parseFloat(v) });
  }

  function setRTLAlt() {}
  function acroInput(axis, val) {
    document.getElementById(`acro-${axis}-v`).textContent = val;
  }
  function planMission() {}
  function startAddWP() { activateWaypoint(); }

  // ── Mapa ──────────────────────────────────────────────────────────────────
  function toggle3D()   { Map3D.toggle3D(); }
  function toggleSat()  { Map3D.toggleSat(); }
  function tiltView()   { Map3D.tiltView(); }
  function resetNorth() { Map3D.resetNorth(); }
  function flyHome() {
    const drones = DroneState.getAll();
    if (drones.length) Map3D.fitDrones(drones);
    else if (_tkPoint) Map3D.flyTo(_tkPoint.lat, _tkPoint.lon, 16);
  }
  function exportMission() {
    log('Export no implementado aún', 'warn');
  }

  // ── FPV ───────────────────────────────────────────────────────────────────
  function toggleFPV() {
    const d = DroneState.getSelected() || DroneState.getAll()[0];
    if (!d) { log('Sin dron para FPV', 'warn'); return; }
    Map3D.toggleFollow(d.id);
    const badge = document.getElementById('fpv-badge');
    const btn   = document.getElementById('btn-fpv');
    const on    = badge?.style.display !== 'none';
    btn.classList.toggle('active', on);
  }

  // ── Label flash ───────────────────────────────────────────────────────────
  function _showLabel(text, color) {
    const ml = document.getElementById('mode-label');
    if (!ml) return;
    ml.textContent = text;
    ml.style.color       = color || 'var(--amber)';
    ml.style.borderColor = color || 'var(--amber)';
    ml.style.display = 'block';
    clearTimeout(ml._t);
    ml._t = setTimeout(() => { ml.style.display = 'none'; }, 3000);
  }

  // ── Log ───────────────────────────────────────────────────────────────────
  function log(msg, level = '') {
    const el = document.getElementById('log-entries');
    if (!el) return;
    const ts  = new Date().toTimeString().slice(0,8);
    const div = document.createElement('div');
    div.className = 'log-line ' + level;
    div.innerHTML = `<span class="log-ts">${ts}</span>${msg}`;
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
    while (el.children.length > 150) el.removeChild(el.firstChild);
    const sb = document.getElementById('status-bar');
    if (sb) sb.textContent = msg.slice(0, 80);
  }

  // WS events
  WS.on('formation_ready', msg => {
    const n = msg.result?.n_drones || '?';
    log(`✓ ${n} drones desplegados en formación ${msg.result?.formation}`, 'info');
    // Auto-seleccionar primer dron para FPV
    const drones = DroneState.getAll();
    if (drones.length) DroneState.select(drones[0].id);
  });

  WS.on('abort_all_sent', msg => {
    log(`⚠ RTL enviado a ${msg.drone_count} drones`, 'err');
  });

  return {
    init, connect,
    activateTakeoff, activateLanding, selectFormation,
    startSim, stopSim, abortAll, clearAll,
    activateWaypoint, clearWPs, renderWPList,
    setMode, refreshModeButtons, acroInput,
    setSpeed, setAltHold, setRTLAlt,
    planMission, startAddWP, exportMission,
    toggle3D, toggleSat, tiltView, resetNorth, flyHome, toggleFPV,
    log,
  };
})();