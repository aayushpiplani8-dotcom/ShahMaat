// The one WebSocket connection per tab.
//
// * Authenticates with the first message (token never appears in a URL).
// * Reconnects by itself with exponential backoff + jitter, re-authenticates
//   with a fresh token, and re-subscribes to every game being watched, so a
//   wifi blip mid-game just shows "reconnecting" for a moment.
// * Answers the server's pings; the server uses the round-trip time for lag
//   compensation on your clock.
import { refreshSession, useAuth } from './auth';

class GameSocket {
  constructor() {
    this.ws = null;
    this.listeners = new Map(); // type -> Set<fn>
    this.watching = new Set();
    this.status = 'idle'; // idle | connecting | open | closed
    this.attempt = 0;
    this.ref = 1;
    this.hello = null;
    this.timer = null;
    this.wanted = false;
  }

  on(type, fn) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(fn);
    return () => this.listeners.get(type)?.delete(fn);
  }

  emit(type, msg) {
    for (const fn of this.listeners.get(type) ?? []) fn(msg);
    for (const fn of this.listeners.get('*') ?? []) fn(msg);
  }

  setStatus(status) {
    this.status = status;
    this.emit('status', { type: 'status', status });
  }

  start() {
    this.wanted = true;
    if (this.ws && this.ws.readyState <= 1) return;
    this.open();
  }

  restart() {
    // Called when the signed-in user changes: reconnect with the new identity.
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.hello = null;
    if (this.wanted) this.open();
  }

  async open() {
    clearTimeout(this.timer);
    this.setStatus('connecting');
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${scheme}://${location.host}/ws`);
    this.ws = ws;

    ws.onopen = async () => {
      let token = useAuth.getState().token;
      if (token && isExpiringSoon(token)) {
        const session = await refreshSession();
        token = session?.access_token ?? null;
      }
      ws.send(JSON.stringify({ type: 'auth', token }));
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      if (msg.type === 'ping') {
        ws.send(JSON.stringify({ type: 'pong', t: msg.t }));
        return;
      }
      if (msg.type === 'hello') {
        this.attempt = 0;
        this.hello = msg;
        this.setStatus('open');
        for (const id of this.watching) ws.send(JSON.stringify({ type: 'game.watch', game_id: id }));
      }
      this.emit(msg.type, msg);
    };

    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.setStatus('closed');
      if (!this.wanted) return;
      // 0.5s, 1s, 2s, 4s ... capped at 15s, with jitter so a server restart isn't stampeded.
      const delay = Math.min(15000, 500 * 2 ** this.attempt++) * (0.75 + Math.random() * 0.5);
      this.timer = setTimeout(() => this.open(), delay);
    };
  }

  send(msg) {
    const withRef = { ...msg, ref: this.ref++ };
    if (this.ws?.readyState === WebSocket.OPEN && this.status === 'open') {
      this.ws.send(JSON.stringify(withRef));
      return withRef.ref;
    }
    return null;
  }

  watch(gameId) {
    this.watching.add(gameId);
    this.send({ type: 'game.watch', game_id: gameId });
  }

  unwatch(gameId) {
    this.watching.delete(gameId);
    this.send({ type: 'game.unwatch', game_id: gameId });
  }
}

function isExpiringSoon(token) {
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return payload.exp * 1000 - Date.now() < 30_000;
  } catch {
    return true;
  }
}

export const socket = new GameSocket();
