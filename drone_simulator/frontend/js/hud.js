/**
 * js/hud.js – Simulation HUD, elapsed time counter, flight stats overlay
 */
const HUD = (() => {
  let _startTime = null;
  let _rafId     = null;
  let _flying    = 0;
  let _total     = 0;
  let _phase     = '—';

  function start() {
    _loop();
  }

  function _loop() {
    _rafId = requestAnimationFrame(_loop);
    _tick();
  }

  function _tick() {
    // Update sim elapsed time
    if (_startTime) {
      const elapsed = (Date.now() - _startTime) / 1000;
      const m = Math.floor(elapsed / 60);
      const s = Math.floor(elapsed % 60);
      document.getElementById('hud-time').textContent =
        String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
    }
    document.getElementById('hud-flying').textContent = _flying;
    document.getElementById('hud-total').textContent  = _total;
    document.getElementById('hud-phase').textContent  = _phase;
  }

  function updateBatch(msg) {
    const drones = msg.drones || [];
    _total   = drones.length;
    _flying  = drones.filter(d => d.phase !== 'IDLE' && d.phase !== 'LAND').length;
    _phase   = drones.length ? drones[0].phase : '—';
    if (!_startTime && _flying > 0) _startTime = Date.now();
  }

  WS.on('sim_started', () => { _startTime = Date.now(); });
  WS.on('sim_stopped', () => { _startTime = null; });
  WS.on('reset',       () => { _startTime = null; _flying = 0; _total = 0; });

  return { start, updateBatch };
})();