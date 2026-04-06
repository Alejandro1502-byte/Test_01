/**
 * js/ws.js – WebSocket client, reconnect logic, message dispatcher
 */
const WS = (() => {
  let _socket = null;
  let _reconnectTimer = null;
  let _handlers = {};
  let _queue = [];   // messages queued while disconnected
  let _url = 'ws://localhost:8765/ws';

  function connect(url) {
    if (url) _url = url;
    if (_socket && _socket.readyState < 2) _socket.close();

    _socket = new WebSocket(_url);

    _socket.onopen = () => {
      clearTimeout(_reconnectTimer);
      UI.log('WebSocket conectado a ' + _url, 'info');
      document.getElementById('conn-badge').textContent  = '● CONNECTED';
      document.getElementById('conn-badge').className    = 'badge-connected';
      // Flush queue
      _queue.forEach(m => _socket.send(JSON.stringify(m)));
      _queue = [];
      emit('connected');
    };

    _socket.onclose = () => {
      document.getElementById('conn-badge').textContent = '● DISCONNECTED';
      document.getElementById('conn-badge').className  = 'badge-disconnected';
      UI.log('WS desconectado – reintentando en 3s…', 'warn');
      emit('disconnected');
      _reconnectTimer = setTimeout(() => connect(), 3000);
    };

    _socket.onerror = () => {
      UI.log('WS error de conexión', 'err');
    };

    _socket.onmessage = ev => {
      try {
        const msg = JSON.parse(ev.data);
        emit(msg.type, msg);
      } catch(e) {
        console.warn('[WS] parse error', e);
      }
    };
  }

  function send(payload) {
    if (_socket && _socket.readyState === WebSocket.OPEN) {
      _socket.send(JSON.stringify(payload));
    } else {
      _queue.push(payload);
    }
  }

  function on(type, fn) {
    if (!_handlers[type]) _handlers[type] = [];
    _handlers[type].push(fn);
  }

  function off(type, fn) {
    if (!_handlers[type]) return;
    _handlers[type] = _handlers[type].filter(h => h !== fn);
  }

  function emit(type, msg) {
    (_handlers[type] || []).forEach(fn => fn(msg));
  }

  return { connect, send, on, off };
})();