/**
 * js/attitude_indicator.js
 * Indicador de actitud (artificial horizon) dibujado en Canvas.
 * Se actualiza con cada paquete de telemetría del dron seleccionado.
 */
const AttitudeIndicator = (() => {
  let _canvas = null;
  let _ctx    = null;
  let _raf    = null;
  let _roll   = 0;
  let _pitch  = 0;
  let _yaw    = 0;
  let _visible = false;

  // ── Build widget ─────────────────────────────────────────────────────────
  function init() {
    // Create floating widget
    const wrap = document.createElement('div');
    wrap.id = 'attitude-wrap';
    wrap.innerHTML = `
      <div class="aw-header">
        <span>ADI</span>
        <button onclick="AttitudeIndicator.toggle()" title="Cerrar">✕</button>
      </div>
      <canvas id="adi-canvas" width="160" height="160"></canvas>
      <div class="aw-footer">
        <span>R: <span id="adi-roll">0°</span></span>
        <span>P: <span id="adi-pitch">0°</span></span>
        <span>Y: <span id="adi-yaw">0°</span></span>
      </div>`;
    document.getElementById('map-wrap').appendChild(wrap);

    _canvas = document.getElementById('adi-canvas');
    _ctx    = _canvas.getContext('2d');

    // Styles
    const style = document.createElement('style');
    style.textContent = `
      #attitude-wrap {
        position:absolute; bottom:60px; left:14px; z-index:50;
        background:rgba(5,10,7,0.92); border:1px solid var(--border);
        width:160px; user-select:none;
        display:none;
      }
      #attitude-wrap.visible { display:block; }
      .aw-header {
        display:flex; justify-content:space-between; align-items:center;
        padding:3px 8px; border-bottom:1px solid var(--border);
        font-family:'Orbitron',monospace; font-size:8px; letter-spacing:2px;
        color:var(--green-dim);
      }
      .aw-header button {
        background:none; border:none; color:var(--text-dim); cursor:pointer; font-size:10px;
      }
      .aw-header button:hover { color:var(--red); }
      .aw-footer {
        display:flex; justify-content:space-around;
        padding:3px 4px; border-top:1px solid var(--border);
        font-size:8px; color:var(--text-dim);
      }
      .aw-footer span span { color:var(--green); }
    `;
    document.head.appendChild(style);

    // Hook telemetry
    WS.on('telemetry_batch', msg => {
      const sel = DroneState.getSelected();
      if (!sel) return;
      const d = (msg.drones || []).find(x => x.id === sel.id);
      if (d) update(d.roll, d.pitch, d.yaw);
    });

    _startLoop();
  }

  function show()   { document.getElementById('attitude-wrap').classList.add('visible');    _visible = true; }
  function hide()   { document.getElementById('attitude-wrap').classList.remove('visible'); _visible = false; }
  function toggle() { _visible ? hide() : show(); }

  function update(roll, pitch, yaw) {
    _roll  = roll  || 0;
    _pitch = pitch || 0;
    _yaw   = yaw   || 0;
    // Update text
    const r = document.getElementById('adi-roll');
    const p = document.getElementById('adi-pitch');
    const y = document.getElementById('adi-yaw');
    if (r) r.textContent = _roll.toFixed(1)  + '°';
    if (p) p.textContent = _pitch.toFixed(1) + '°';
    if (y) y.textContent = _yaw.toFixed(0)   + '°';
  }

  // ── Render loop ──────────────────────────────────────────────────────────
  function _startLoop() {
    function loop() {
      _raf = requestAnimationFrame(loop);
      if (_visible) _draw();
    }
    loop();
  }

  function _draw() {
    const W = _canvas.width;
    const H = _canvas.height;
    const cx = W / 2;
    const cy = H / 2;
    const R  = W / 2 - 2;

    const ctx = _ctx;
    ctx.clearRect(0, 0, W, H);

    // ── Clip circle ────────────────────────────────────────────────────────
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.clip();

    const rollR  = _roll  * Math.PI / 180;
    const pitchPx = _pitch * (R / 45);  // 45° = R pixels

    // Rotate entire horizon
    ctx.translate(cx, cy);
    ctx.rotate(-rollR);
    ctx.translate(0, pitchPx);

    // ── Sky ────────────────────────────────────────────────────────────────
    ctx.fillStyle = '#003366';
    ctx.fillRect(-W, -H * 2, W * 2, H * 2);

    // ── Ground ─────────────────────────────────────────────────────────────
    ctx.fillStyle = '#4a2800';
    ctx.fillRect(-W, 0, W * 2, H * 2);

    // ── Horizon line ───────────────────────────────────────────────────────
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth   = 1.5;
    ctx.beginPath();
    ctx.moveTo(-W, 0);
    ctx.lineTo(W, 0);
    ctx.stroke();

    // ── Pitch ladder ───────────────────────────────────────────────────────
    ctx.fillStyle = '#ffffff';
    ctx.font = '8px Share Tech Mono';
    ctx.textAlign = 'center';
    for (let deg = -40; deg <= 40; deg += 10) {
      if (deg === 0) continue;
      const y = -(deg * R / 45);
      const len = deg % 20 === 0 ? 28 : 14;
      ctx.strokeStyle = deg > 0 ? '#aaddff' : '#ffaa88';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(-len, y); ctx.lineTo(len, y);
      ctx.stroke();
      if (deg % 20 === 0) {
        ctx.fillStyle = '#ccc';
        ctx.fillText(Math.abs(deg), len + 12, y + 3);
        ctx.fillText(Math.abs(deg), -len - 12, y + 3);
      }
    }

    ctx.restore();

    // ── Fixed aircraft reference (outside clip) ────────────────────────────
    ctx.save();
    ctx.translate(cx, cy);

    // Wings
    ctx.strokeStyle = '#ffcc00';
    ctx.lineWidth = 2.5;
    // Left wing
    ctx.beginPath(); ctx.moveTo(-30, 0); ctx.lineTo(-10, 0); ctx.lineTo(-8, 6); ctx.stroke();
    // Right wing
    ctx.beginPath(); ctx.moveTo(30, 0); ctx.lineTo(10, 0); ctx.lineTo(8, 6); ctx.stroke();
    // Center dot
    ctx.fillStyle = '#ffcc00';
    ctx.beginPath(); ctx.arc(0, 0, 3, 0, Math.PI * 2); ctx.fill();

    ctx.restore();

    // ── Roll indicator arc ─────────────────────────────────────────────────
    ctx.save();
    ctx.translate(cx, cy);
    ctx.strokeStyle = '#00ff88';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(0, 0, R - 4, -Math.PI * 1.1, -Math.PI * 0.1);
    ctx.stroke();

    // Roll marker
    ctx.save();
    ctx.rotate(-_roll * Math.PI / 180);
    ctx.fillStyle = '#00ff88';
    ctx.beginPath();
    ctx.moveTo(0, -(R - 4));
    ctx.lineTo(-5, -(R - 14));
    ctx.lineTo(5, -(R - 14));
    ctx.closePath();
    ctx.fill();
    ctx.restore();

    // Tick marks at 0, ±10, ±20, ±30, ±45, ±60
    [0, 10, -10, 20, -20, 30, -30, 45, -45, 60, -60].forEach(angle => {
      ctx.save();
      ctx.rotate(angle * Math.PI / 180);
      const len = (angle === 0 || angle % 30 === 0) ? 8 : 5;
      ctx.strokeStyle = '#00aa55';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, -(R - 4));
      ctx.lineTo(0, -(R - 4 - len));
      ctx.stroke();
      ctx.restore();
    });

    ctx.restore();

    // ── Border ─────────────────────────────────────────────────────────────
    ctx.strokeStyle = '#1a3a25';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.stroke();

    // ── Heading bug (top) ──────────────────────────────────────────────────
    ctx.save();
    ctx.translate(cx, cy);
    ctx.fillStyle = '#00ccff';
    ctx.font = 'bold 9px Orbitron';
    ctx.textAlign = 'center';
    ctx.fillText(_yaw.toFixed(0) + '°', 0, -R + 16);
    ctx.restore();
  }

  return { init, show, hide, toggle, update };
})();