/**
 * js/map3d.js – MapLibre GL 3D map: terrain, satellite imagery, drone markers + trails
 */

// ← PON AQUI TU API KEY DE MAPTILER (https://cloud.maptiler.com)
const MAPTILER_KEY = 'smrUp2s58gPXRrDhFAB3';

const Map3D = (() => {
  let map = null;
  let is3D    = true;
  let isSat   = true;
  let addWpMode = false;
  let addWpCallback = null;

  // Per-drone objects
  const markers  = {};   // droneId → maplibregl.Marker
  const trailSrc = {};   // droneId → source id
  const wpSrc    = {};   // droneId → source id
  const homeSrc  = {};   // droneId → Marker (home pin)

  // FPV / camera follow state
  let _fpvDroneId  = null;   // id del dron que se está siguiendo
  let _fpvMode     = null;   // 'follow' | 'fpv' | null
  let _fpvRaf      = null;
  let _lastDronePosForCam = null;

  // Colours for sequential drones
  const PALETTE = [
    '#00ff88','#00ccff','#ffaa00','#ff3344',
    '#aa88ff','#ff88cc','#88ffcc','#ffff44',
  ];

  let droneCount = 0;

  // ── Init ──────────────────────────────────────────────────────────────────
  function init() {
    // Use OpenFreeMap LibreTiles (no API key needed for demo)
    // For production replace with MapTiler or Mapbox
    const key = MAPTILER_KEY;
    const styleUrl = `https://api.maptiler.com/maps/satellite/style.json?key=${key}`;

    map = new maplibregl.Map({
      container: 'map',
      style: styleUrl,
      center: [-3.7038, 40.4168],
      zoom: 12,
      pitch: 45,
      bearing: -10,
      antialias: true,
    });

    map.addControl(new maplibregl.NavigationControl(), 'bottom-right');
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 120 }), 'bottom-left');

    map.on('load', () => {
      // Terreno DEM 3D
      if (!map.getSource('terrain-dem')) {
        map.addSource('terrain-dem', {
          type: 'raster-dem',
          url: `https://api.maptiler.com/tiles/terrain-rgb-v2/tiles.json?key=${key}`,
          tileSize: 256,
        });
      }
      map.setTerrain({ source: 'terrain-dem', exaggeration: 1.5 });

      // Edificios 3D desde MapTiler (incluidos en el estilo satellite)
      // Si el estilo ya los incluye, los activamos; si no, los añadimos
      try {
        if (!map.getSource('openmaptiles')) {
          map.addSource('openmaptiles', {
            type: 'vector',
            url: `https://api.maptiler.com/tiles/v3/tiles.json?key=${key}`,
          });
        }
        // Capa de edificios 3D extruidos
        if (!map.getLayer('3d-buildings')) {
          map.addLayer({
            id: '3d-buildings',
            source: 'openmaptiles',
            'source-layer': 'building',
            type: 'fill-extrusion',
            minzoom: 14,
            paint: {
              'fill-extrusion-color': [
                'interpolate', ['linear'], ['get', 'render_height'],
                0,   '#1a2e1a',
                10,  '#1e3a1e',
                50,  '#233a23',
                200, '#2a4a2a',
              ],
              'fill-extrusion-height': [
                'interpolate', ['linear'], ['zoom'],
                14, 0,
                14.05, ['coalesce', ['get', 'render_height'], 5],
              ],
              'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
              'fill-extrusion-opacity': 0.85,
            },
          });
        }
      } catch(e) {
        console.warn('Edificios 3D no disponibles:', e.message);
      }

      UI.log('Mapa satelital 3D + edificios cargado', 'info');
    });

    map.on('error', (e) => {
      // Si falla MapTiler, cargar Esri de fallback
      if (e.error && e.error.status === 401) {
        UI.log('MapTiler key error – cargando mapa alternativo', 'warn');
        map.setStyle({
          version: 8,
          sources: {
            'esri-sat': {
              type: 'raster',
              tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
              tileSize: 256,
              attribution: '© Esri',
              maxzoom: 19,
            }
          },
          layers: [
            { id: 'bg',  type: 'background', paint: { 'background-color': '#050a07' } },
            { id: 'sat', type: 'raster',     source: 'esri-sat', paint: { 'raster-opacity': 0.95 } },
          ]
        });
      }
    });

    // Click handler for WP placement
    map.on('click', e => {
      if (addWpMode && addWpCallback) {
        addWpCallback(e.lngLat.lat, e.lngLat.lng);
        // Stay in WP mode for multiple WPs; ESC to exit
      }
    });

    // ESC to cancel WP mode
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') exitWpMode();
    });
  }

  // ── Style builder ─────────────────────────────────────────────────────────
  function _buildStyle() {
    const key = MAPTILER_KEY;
    const hasKey = key && key !== 'TU_API_KEY_AQUI';

    return {
      version: 8,
      sources: {
        // Satelite MapTiler (con key) o Esri (sin key)
        'sat-tiles': {
          type: 'raster',
          tiles: hasKey
            ? [`https://api.maptiler.com/tiles/satellite-v2/{z}/{x}/{y}.jpg?key=${key}`]
            : ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
          tileSize: 256,
          attribution: hasKey ? '© MapTiler © OpenStreetMap' : '© Esri World Imagery',
          maxzoom: 19,
        },
        // Terreno DEM 3D — MapTiler con key, demo sin key
        'terrain-dem': {
          type: 'raster-dem',
          tiles: hasKey
            ? [`https://api.maptiler.com/tiles/terrain-rgb-v2/{z}/{x}/{y}.webp?key=${key}`]
            : ['https://demotiles.maplibre.org/terrain-tiles/{z}/{x}/{y}.png'],
          tileSize: 256,
          maxzoom: hasKey ? 14 : 12,
          encoding: hasKey ? 'mapbox' : 'mapbox',
        },
      },
      layers: [
        { id: 'background', type: 'background', paint: { 'background-color': '#050a07' } },
        { id: 'satellite',  type: 'raster', source: 'sat-tiles', paint: { 'raster-opacity': 0.95 } },
      ],
      terrain: { source: 'terrain-dem', exaggeration: 1.5 },
      sky: {
        'sky-color':         '#0a1a12',
        'sky-horizon-blend': 0.4,
        'horizon-color':     '#003322',
        'fog-color':         '#0a1a12',
        'fog-ground-blend':  0.9,
      },
    };
  }

  function _addTerrainAndSky() {
    if (!map.getSource('terrain-dem')) return;
    if (!map.getTerrain()) {
      map.setTerrain({ source: 'terrain-dem', exaggeration: 1.5 });
    }
  }

  // ── Drone markers ─────────────────────────────────────────────────────────
  function addDroneMarker(drone) {
    if (markers[drone.id]) return;

    const el = _makeDroneEl(drone.color || PALETTE[droneCount % PALETTE.length]);
    droneCount++;

    const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
      .setLngLat([drone.lon, drone.lat])
      .addTo(map);

    el.addEventListener('click', () => {
      DroneState.select(drone.id);
    });

    markers[drone.id] = { marker, el };

    // Trail source
    const tsId = `trail-${drone.id}`;
    map.addSource(tsId, {
      type: 'geojson',
      data: { type: 'Feature', geometry: { type: 'LineString', coordinates: [] } }
    });
    map.addLayer({
      id: tsId,
      type: 'line',
      source: tsId,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': drone.color || '#00ff88',
        'line-width': 2.5,
        'line-opacity': 0.85,
        'line-blur': 0.5,
      }
    });
    trailSrc[drone.id] = tsId;

    // WP route source
    const wpId = `wps-${drone.id}`;
    map.addSource(wpId, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    });
    map.addLayer({
      id: `${wpId}-line`,
      type: 'line',
      source: wpId,
      paint: { 'line-color': drone.color || '#00ff88', 'line-width': 1, 'line-dasharray': [4,3] }
    });
    map.addLayer({
      id: `${wpId}-pts`,
      type: 'circle',
      source: wpId,
      filter: ['==', '$type', 'Point'],
      paint: { 'circle-radius': 4, 'circle-color': drone.color || '#00ff88', 'circle-opacity': 0.8 }
    });
    wpSrc[drone.id] = wpId;
  }

  function updateDroneMarker(drone) {
    const obj = markers[drone.id];
    if (!obj) { addDroneMarker(drone); return; }

    // Position
    obj.marker.setLngLat([drone.lon, drone.lat]);

    // Update 3D attitude and re-render
    const el = obj.el;
    el._yaw   = drone.yaw   || 0;
    el._roll  = drone.roll  || 0;
    el._pitch = drone.pitch || 0;
    _renderDrone3D(el);

    // Alt glow on ring
    const dot = el.querySelector('.drone-dot');
    if (dot) {
      const altPct = Math.min(drone.alt / 300, 1);
      dot.style.opacity = 0.4 + 0.6 * altPct;
    }

    // Trail 3D con altitud real
    const tsId = trailSrc[drone.id];
    if (tsId && map.getSource(tsId) && drone.trail && drone.trail.length > 1) {
      const coords = drone.trail.map(p => [p.lon, p.lat, Math.max(p.alt, 0)]);
      map.getSource(tsId).setData({
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: coords }
      });
    }
  }

  function removeDroneMarker(droneId) {
    const obj = markers[droneId];
    if (obj) { obj.marker.remove(); delete markers[droneId]; }

    [trailSrc, wpSrc].forEach(dict => {
      const id = dict[droneId];
      if (!id) return;
      [`${id}-line`, `${id}-pts`, id].forEach(lid => {
        if (map.getLayer(lid)) map.removeLayer(lid);
      });
      if (map.getSource(id)) map.removeSource(id);
      delete dict[droneId];
    });
  }

  function updateWaypointLayer(droneId, waypoints, color) {
    const wpId = wpSrc[droneId];
    if (!wpId || !map.getSource(wpId)) return;

    const coords = waypoints.map(w => [w.lon, w.lat, w.alt]);
    const features = [
      {
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: coords },
        properties: {}
      },
      ...waypoints.map((w, i) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [w.lon, w.lat, w.alt] },
        properties: { idx: i }
      }))
    ];
    map.getSource(wpId).setData({ type: 'FeatureCollection', features });
  }

  // ── Drone 3D element (canvas con Three.js mini-renderer) ─────────────────
  function _makeDroneEl(color) {
    const SIZE = 64;
    const wrap = document.createElement('div');
    wrap.style.cssText = `position:relative;width:${SIZE}px;height:${SIZE}px;cursor:pointer;`;

    // Pulse ring
    const ring = document.createElement('div');
    ring.className = 'drone-dot';
    ring.style.cssText = `
      position:absolute;inset:0;border-radius:50%;
      border:1px solid ${color};background:${color}18;
      animation:drone-pulse 2s ease infinite;pointer-events:none;`;
    wrap.appendChild(ring);

    // Canvas for 3D render
    const canvas = document.createElement('canvas');
    canvas.width  = SIZE;
    canvas.height = SIZE;
    canvas.className = 'drone-canvas';
    canvas.style.cssText = 'position:absolute;inset:0;';
    wrap.appendChild(canvas);

    // Build Three.js mini-scene
    const scene    = _buildDroneScene(color);
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setSize(SIZE, SIZE);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setClearColor(0x000000, 0);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    camera.position.set(0, 2.2, 2.2);
    camera.lookAt(0, 0, 0);

    wrap._scene    = scene;
    wrap._renderer = renderer;
    wrap._camera   = camera;
    wrap._yaw      = 0;
    wrap._roll     = 0;
    wrap._pitch    = 0;
    wrap._rotors   = scene.userData.rotors || [];
    wrap._color    = color;

    // First render
    _renderDrone3D(wrap);

    return wrap;
  }

  // ── Build a realistic quadcopter Three.js scene ───────────────────────────
  function _buildDroneScene(color) {
    const scene = new THREE.Scene();
    const c = new THREE.Color(color);

    // Lighting
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.2);
    sun.position.set(2, 4, 3);
    scene.add(sun);
    const fill = new THREE.DirectionalLight(0x8888ff, 0.3);
    fill.position.set(-2, -1, -2);
    scene.add(fill);

    const mat = new THREE.MeshPhongMaterial({
      color: c, emissive: c, emissiveIntensity: 0.15,
      shininess: 80, specular: new THREE.Color(0xffffff),
    });
    const darkMat = new THREE.MeshPhongMaterial({
      color: 0x111111, shininess: 60,
    });
    const rotorMat = new THREE.MeshPhongMaterial({
      color: 0x333333, transparent: true, opacity: 0.7, side: THREE.DoubleSide,
    });

    // ── Central body (flattened box) ──────────────────────────────────────
    const bodyGeo = new THREE.BoxGeometry(0.45, 0.12, 0.45);
    const body    = new THREE.Mesh(bodyGeo, mat);
    body.position.y = 0.06;
    scene.add(body);

    // Top dome
    const domeGeo = new THREE.SphereGeometry(0.16, 12, 8, 0, Math.PI*2, 0, Math.PI/2);
    const dome    = new THREE.Mesh(domeGeo, mat);
    dome.position.y = 0.12;
    scene.add(dome);

    // Battery pack (underside)
    const battGeo = new THREE.BoxGeometry(0.3, 0.07, 0.14);
    const batt    = new THREE.Mesh(battGeo, darkMat);
    batt.position.set(0, -0.01, 0);
    scene.add(batt);

    // ── 4 Arms ────────────────────────────────────────────────────────────
    const armAngles = [45, 135, 225, 315];
    const rotors    = [];
    const ARM_LEN   = 0.55;

    armAngles.forEach((deg, i) => {
      const rad = (deg * Math.PI) / 180;
      const ax  = Math.cos(rad) * ARM_LEN * 0.5;
      const az  = Math.sin(rad) * ARM_LEN * 0.5;

      // Arm tube
      const armGeo  = new THREE.CylinderGeometry(0.025, 0.025, ARM_LEN, 6);
      const arm     = new THREE.Mesh(armGeo, darkMat);
      arm.position.set(ax, 0.06, az);
      arm.rotation.z = Math.PI / 2;
      arm.rotation.y = -rad;
      scene.add(arm);

      // Motor housing
      const motorGeo = new THREE.CylinderGeometry(0.065, 0.055, 0.07, 10);
      const motor    = new THREE.Mesh(motorGeo, darkMat);
      motor.position.set(Math.cos(rad)*ARM_LEN, 0.08, Math.sin(rad)*ARM_LEN);
      scene.add(motor);

      // Rotor disc (spinning blade simulation)
      const rotorGeo  = new THREE.CircleGeometry(0.22, 16);
      const rotor     = new THREE.Mesh(rotorGeo, rotorMat);
      rotor.rotation.x = -Math.PI / 2;
      rotor.position.set(Math.cos(rad)*ARM_LEN, 0.12, Math.sin(rad)*ARM_LEN);
      scene.add(rotor);
      rotors.push(rotor);

      // Blade cross (static geometry inside rotor for realism)
      [-1,1].forEach(sign => {
        const bladeGeo = new THREE.BoxGeometry(0.38, 0.003, 0.04);
        const blade    = new THREE.Mesh(bladeGeo, mat);
        blade.rotation.x = -Math.PI / 2;
        blade.rotation.z = sign * Math.PI / 6;
        blade.position.set(Math.cos(rad)*ARM_LEN, 0.125, Math.sin(rad)*ARM_LEN);
        scene.add(blade);
        rotors.push(blade);
      });

      // LED (green front, red rear)
      const ledColor = (i < 2) ? 0x00ff88 : 0xff3333;
      const ledGeo   = new THREE.SphereGeometry(0.025, 6, 6);
      const ledMat   = new THREE.MeshBasicMaterial({ color: ledColor });
      const led      = new THREE.Mesh(ledGeo, ledMat);
      led.position.set(Math.cos(rad)*ARM_LEN, 0.04, Math.sin(rad)*ARM_LEN);
      scene.add(led);
    });

    // Landing gear (4 legs)
    [45,135,225,315].forEach(deg => {
      const rad = (deg * Math.PI) / 180;
      const lgGeo = new THREE.CylinderGeometry(0.012, 0.012, 0.18, 5);
      const lg    = new THREE.Mesh(lgGeo, darkMat);
      lg.position.set(Math.cos(rad)*0.22, -0.09, Math.sin(rad)*0.22);
      lg.rotation.z = Math.PI * 0.08;
      lg.rotation.x = Math.PI * 0.08 * Math.sign(Math.sin(rad));
      scene.add(lg);
    });

    scene.userData.rotors = rotors;
    return scene;
  }

  // ── Render one frame of 3D drone ─────────────────────────────────────────
  function _renderDrone3D(wrap) {
    if (!wrap._scene) return;
    // Rotate rotor discs
    wrap._rotors.forEach((r, i) => { r.rotation.z += 0.18 * (i % 2 === 0 ? 1 : -1); });
    // Apply drone attitude
    wrap._scene.rotation.y = -wrap._yaw   * Math.PI / 180;
    wrap._scene.rotation.z =  wrap._roll  * Math.PI / 180;
    wrap._scene.rotation.x =  wrap._pitch * Math.PI / 180;
    wrap._renderer.render(wrap._scene, wrap._camera);
  }

  // ── WP add mode ───────────────────────────────────────────────────────────
  function enterWpMode(callback) {
    addWpMode = true;
    addWpCallback = callback;
    document.getElementById('click-mode').style.display = 'block';
    map.getCanvas().style.cursor = 'crosshair';
  }

  function exitWpMode() {
    addWpMode = false;
    addWpCallback = null;
    document.getElementById('click-mode').style.display = 'none';
    map.getCanvas().style.cursor = '';
    document.getElementById('btn-add-wp').classList.remove('active');
  }

  // ── Camera helpers ────────────────────────────────────────────────────────
  function toggle3D() {
    is3D = !is3D;
    map.easeTo({ pitch: is3D ? 50 : 0, duration: 600 });
    map.setTerrain(is3D ? { source: 'terrain-dem', exaggeration: 1.5 } : null);
    document.getElementById('btn-3d').classList.toggle('active', is3D);
  }

  function toggleSat() {
    isSat = !isSat;
    const opacity = isSat ? 0.92 : 0.2;
    if (map.getLayer('satellite')) map.setPaintProperty('satellite', 'raster-opacity', opacity);
    document.getElementById('btn-sat').classList.toggle('active', isSat);
  }

  function tiltView() {
    const p = (map.getPitch() > 30) ? 0 : 60;
    map.easeTo({ pitch: p, duration: 600 });
  }

  function resetNorth() {
    map.easeTo({ bearing: 0, pitch: 45, duration: 600 });
  }

  function flyTo(lat, lon, zoom = 14) {
    map.flyTo({ center: [lon, lat], zoom, pitch: 45, duration: 1200 });
  }

  function fitDrones(drones) {
    if (!drones.length) return;
    const lngs = drones.map(d => d.lon);
    const lats = drones.map(d => d.lat);
    map.fitBounds(
      [[Math.min(...lngs)-0.01, Math.min(...lats)-0.01],
       [Math.max(...lngs)+0.01, Math.max(...lats)+0.01]],
      { padding: 80, pitch: 45, duration: 1000 }
    );
  }

  function getMap() { return map; }

  // ── Área de vuelo ────────────────────────────────────────────────────────
  function drawArea(bounds) {
    const id = 'flight-area';
    const coords = [
      [bounds.w, bounds.n],
      [bounds.e, bounds.n],
      [bounds.e, bounds.s],
      [bounds.w, bounds.s],
      [bounds.w, bounds.n],
    ];
    if (map.getLayer(id + '-fill')) map.removeLayer(id + '-fill');
    if (map.getLayer(id + '-line')) map.removeLayer(id + '-line');
    if (map.getSource(id)) map.removeSource(id);

    map.addSource(id, {
      type: 'geojson',
      data: { type: 'Feature', geometry: { type: 'Polygon', coordinates: [coords] } }
    });
    map.addLayer({
      id: id + '-fill', type: 'fill', source: id,
      paint: { 'fill-color': '#ffaa00', 'fill-opacity': 0.08 }
    });
    map.addLayer({
      id: id + '-line', type: 'line', source: id,
      paint: { 'line-color': '#ffaa00', 'line-width': 1.5,
               'line-dasharray': [6, 3] }
    });
  }

  function clearArea() {
    ['flight-area-fill','flight-area-line'].forEach(id => {
      if (map.getLayer(id)) map.removeLayer(id);
    });
    if (map.getSource('flight-area')) map.removeSource('flight-area');
  }

  // ── Takeoff / Landing markers ────────────────────────────────────────────
  let _tkMarker  = null;
  let _ldMarker  = null;
  let _wpMarkers = [];

  function setTakeoffMarker(lat, lon) {
    if (_tkMarker) _tkMarker.remove();
    const el = document.createElement('div');
    el.style.cssText = 'display:flex;flex-direction:column;align-items:center;pointer-events:none;';
    el.innerHTML = `
      <div style="font-family:Orbitron,monospace;font-size:8px;color:#00ff88;
        background:rgba(0,0,0,0.8);padding:2px 6px;border:1px solid #00ff88;
        letter-spacing:1px;white-space:nowrap;">✦ TAKEOFF</div>
      <div style="width:0;height:0;border-left:8px solid transparent;
        border-right:8px solid transparent;border-top:14px solid #00ff88;"></div>`;
    _tkMarker = new maplibregl.Marker({ element: el, anchor: 'top' })
      .setLngLat([lon, lat]).addTo(map);
  }

  function setLandingMarker(lat, lon) {
    if (_ldMarker) _ldMarker.remove();
    const el = document.createElement('div');
    el.style.cssText = 'display:flex;flex-direction:column;align-items:center;pointer-events:none;';
    el.innerHTML = `
      <div style="font-family:Orbitron,monospace;font-size:8px;color:#ff3344;
        background:rgba(0,0,0,0.8);padding:2px 6px;border:1px solid #ff3344;
        letter-spacing:1px;white-space:nowrap;">✦ LANDING</div>
      <div style="width:0;height:0;border-left:8px solid transparent;
        border-right:8px solid transparent;border-top:14px solid #ff3344;"></div>`;
    _ldMarker = new maplibregl.Marker({ element: el, anchor: 'top' })
      .setLngLat([lon, lat]).addTo(map);
  }

  function clearMissionMarkers() {
    if (_tkMarker) { _tkMarker.remove(); _tkMarker = null; }
    if (_ldMarker) { _ldMarker.remove(); _ldMarker = null; }
    if (_rallyMarker) { _rallyMarker.remove(); _rallyMarker = null; }
    _wpMarkers.forEach(m => m.remove());
    _wpMarkers = [];
  }

  // ── Rally point marker ───────────────────────────────────────────────────
  let _rallyMarker = null;

  function setRallyMarker(lat, lon, color) {
    if (_rallyMarker) _rallyMarker.remove();
    const el = document.createElement('div');
    el.style.cssText = `
      width:24px;height:24px;border-radius:50%;
      background:transparent;
      border:2px solid ${color || '#ffaa00'};
      box-shadow:0 0 8px ${color || '#ffaa00'};
      position:relative;`;
    el.innerHTML = `<div style="
      position:absolute;top:50%;left:50%;
      transform:translate(-50%,-50%);
      width:6px;height:6px;border-radius:50%;
      background:${color || '#ffaa00'};"></div>
      <div style="
      position:absolute;top:-14px;left:50%;transform:translateX(-50%);
      font-family:Orbitron,monospace;font-size:7px;color:${color || '#ffaa00'};
      white-space:nowrap;letter-spacing:1px;">RALLY</div>`;
    _rallyMarker = new maplibregl.Marker({ element: el, anchor: 'center' })
      .setLngLat([lon, lat])
      .addTo(map);
  }

  function clearRallyMarker() {
    if (_rallyMarker) { _rallyMarker.remove(); _rallyMarker = null; }
  }

  // ── FPV / Camera follow ──────────────────────────────────────────────────
  // Cámara suave con inercia — valores actuales interpolados
  let _camState = { bearing: 0, pitch: 60, zoom: 19, lon: 0, lat: 0 };

  function startFollow(droneId, mode) {
    _fpvDroneId = droneId;
    _fpvMode    = mode || 'chase';
    const badge = document.getElementById('fpv-badge');
    const btn   = document.getElementById('btn-fpv');
    const labels = { chase: '🎥 CHASE CAM', fpv: '📡 FPV FRONTAL' };
    if (badge) { badge.textContent = labels[mode] || labels.chase; badge.style.display = 'block'; }
    if (btn)   { btn.classList.add('active'); btn.textContent = mode === 'fpv' ? 'FPV' : 'CAM'; }
    if (_fpvRaf) cancelAnimationFrame(_fpvRaf);
    // Inicializar camState con posición actual del dron
    const drone = DroneState.get(droneId);
    if (drone) {
      _camState = { bearing: drone.yaw||0, pitch: 70, zoom: 19.5, lon: drone.lon, lat: drone.lat };
    }
    _fpvLoop();
  }

  function stopFollow() {
    _fpvDroneId = null; _fpvMode = null;
    if (_fpvRaf) { cancelAnimationFrame(_fpvRaf); _fpvRaf = null; }
    const badge = document.getElementById('fpv-badge');
    const btn   = document.getElementById('btn-fpv');
    if (badge) badge.style.display = 'none';
    if (btn)   { btn.classList.remove('active'); btn.textContent = 'FPV'; }
  }

  function toggleFollow(droneId) {
    if (_fpvDroneId === droneId && _fpvMode === 'chase') {
      startFollow(droneId, 'fpv');
    } else if (_fpvDroneId === droneId && _fpvMode === 'fpv') {
      stopFollow();
    } else {
      startFollow(droneId, 'chase');
    }
  }

  function _lerp(a, b, t) { return a + (b - a) * t; }
  function _lerpAngle(a, b, t) {
    let d = ((b - a + 540) % 360) - 180;
    return a + d * t;
  }

  function _fpvLoop() {
    if (!_fpvDroneId || !_fpvMode) return;
    const drone = DroneState.get(_fpvDroneId);
    if (!drone) { stopFollow(); return; }

    const yaw    = drone.yaw   || 0;
    const altAGL = Math.max(drone.alt, 0);
    const speed  = drone.speed || 0;

    if (_fpvMode === 'chase') {
      // ── CHASE CAM ─────────────────────────────────────────────────────────
      // Zoom fijo muy cercano — equivale a estar a ~5-10m del dron
      // zoom 20 ≈ resolución de 0.15m/px → muy cerca
      // zoom 19 ≈ 0.3m/px, zoom 18 ≈ 0.6m/px
      // Para ver el dron "a un metro" necesitamos zoom ~20-21 con pitch ~75°

      // Distancia de cámara depende de la altitud
      // En el suelo: muy cerca (zoom 20). A 100m: algo más lejos (zoom 18)
      const targetZoom  = 20.2 - altAGL * 0.018;
      const clampedZoom = Math.max(16, Math.min(21, targetZoom));

      // Pitch: 75° = casi horizontal pero se ve el suelo delante
      // Cuando va rápido se inclina más (más inmersivo)
      const targetPitch = Math.min(80, 72 + speed * 0.3);

      // Suavizado con inercia ligera para movimiento fluido
      _camState.bearing = _lerpAngle(_camState.bearing, yaw,         0.18);
      _camState.pitch   = _lerp(_camState.pitch,         targetPitch, 0.10);
      _camState.zoom    = _lerp(_camState.zoom,           clampedZoom, 0.12);

      map.jumpTo({
        center:  [drone.lon, drone.lat],
        bearing: _camState.bearing,
        pitch:   _camState.pitch,
        zoom:    _camState.zoom,
      });

    } else if (_fpvMode === 'fpv') {
      // ── FPV FRONTAL ───────────────────────────────────────────────────────
      // Pitch 85° = completamente horizontal, como gafas FPV reales
      // Zoom muy alto para sensación de velocidad
      const targetZoom  = Math.max(17, 21.5 - altAGL * 0.03);
      _camState.bearing = _lerpAngle(_camState.bearing, yaw,        0.20);
      _camState.pitch   = _lerp(_camState.pitch,         85,         0.08);
      _camState.zoom    = _lerp(_camState.zoom,           targetZoom, 0.12);

      map.jumpTo({
        center:  [drone.lon, drone.lat],
        bearing: _camState.bearing,
        pitch:   _camState.pitch,
        zoom:    _camState.zoom,
      });
    }

    _fpvRaf = requestAnimationFrame(_fpvLoop);
  }

  // ── WP marker con altitud visual ─────────────────────────────────────────
  function addWPMarker(lat, lon, alt, idx, color) {
    const el = document.createElement('div');
    el.style.cssText = `
      display:flex;flex-direction:column;align-items:center;
      cursor:pointer;pointer-events:none;`;
    el.innerHTML = `
      <div style="
        font-family:Orbitron,monospace;font-size:8px;
        color:${color};background:rgba(0,0,0,0.7);
        padding:1px 4px;border:1px solid ${color};
        white-space:nowrap;letter-spacing:1px;">
        WP${idx} · ${alt}m
      </div>
      <div style="width:10px;height:10px;border-radius:50%;
        background:${color};border:2px solid #000;
        box-shadow:0 0 6px ${color};"></div>`;
    return new maplibregl.Marker({ element: el, anchor: 'bottom' })
      .setLngLat([lon, lat])
      .addTo(map);
  }

  return {
    init, addDroneMarker, updateDroneMarker, removeDroneMarker,
    updateWaypointLayer, enterWpMode, exitWpMode,
    drawArea, clearArea,
    setTakeoffMarker, setLandingMarker, clearMissionMarkers,
    setRallyMarker, clearRallyMarker,
    startFollow, stopFollow, toggleFollow,
    addWPMarker,
    toggle3D, toggleSat, tiltView, resetNorth, flyTo, fitDrones,
    getMap,
  };
})();

// Pulse animation (injected once)
const _style = document.createElement('style');
_style.textContent = `
@keyframes drone-pulse {
  0%,100% { transform: scale(1);   opacity: 0.6; }
  50%      { transform: scale(1.4); opacity: 1;   }
}`;
document.head.appendChild(_style);