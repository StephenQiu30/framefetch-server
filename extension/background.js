/* Listeners are registered synchronously before configuration/connection work. */
importScripts('protocol.js');
importScripts('yuanbao-http.js');
const ALARM = 'framefetch-identity-connect';
let socket = null;
let retryTimer = null;
let starting = false;
let retryAt = 0;
let activeProtocol = null;
let lastParseCause = null;
const backoff = new FrameFetchIdentity.Backoff();

chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === ALARM) void initialize(); });
chrome.runtime.onStartup.addListener(() => { void initialize(); });
chrome.runtime.onInstalled.addListener(() => { void initialize(); });
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL('popup.html') ||
      !message || Object.keys(message).join(',') !== 'type' ||
      !['status', 'login_yuanbao', 'reconnect'].includes(message.type)) return false;
  void popupRequest(message.type).then(respond).catch(() => respond({ error: 'status_unavailable' }));
  return true;
});

async function popupRequest(type) {
  if (type === 'login_yuanbao') {
    await chrome.tabs.create({ url: 'https://yuanbao.tencent.com/', active: true });
  }
  if (type === 'reconnect') {
    if (!activeProtocol?.authenticated) {
      socket?.close();
      clearTimeout(retryTimer);
      retryTimer = null;
      retryAt = 0;
      backoff.reset();
      await initialize();
    }
  }
  const session = await FrameFetchYuanbaoHTTP.status(chrome);
  return { connected: activeProtocol?.authenticated === true, version: chrome.runtime.getManifest().version,
    session, busy: activeProtocol?.busy === true, cause: lastParseCause };
}

async function ensureAlarm() {
  const alarm = await chrome.alarms.get(ALARM);
  if (!alarm || alarm.periodInMinutes !== 0.5) await chrome.alarms.create(ALARM, { periodInMinutes: 0.5 });
}
function scheduleRetry() {
  const delay = backoff.next();
  retryAt = Date.now() + delay;
  clearTimeout(retryTimer);
  retryTimer = setTimeout(() => { retryTimer = null; void initialize(); }, delay);
}
async function initialize() {
  await ensureAlarm();
  if (starting || socket || Date.now() < retryAt) return;
  starting = true;
  try {
    const response = await fetch(chrome.runtime.getURL('config.local.json'));
    if (!response.ok) throw new Error('configuration_unavailable');
    const config = await response.json();
    const ws = new WebSocket(`ws://127.0.0.1:${config.port}/extension`);
    socket = ws;
    let closed = false;
    let heartbeat = null;
    let lastSeen = Date.now();
    const send = message => { if (!closed && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message)); };
    const protocol = new FrameFetchIdentity.Protocol(config, details => chrome.cookies.getAll(details), send, chrome.runtime.getManifest().version,
      async (canonicalUrl, deadlineMs) => {
        lastParseCause = null;
        const result = await FrameFetchYuanbaoHTTP.parseShare(chrome, canonicalUrl, deadlineMs);
        lastParseCause = result.cause ?? null;
        return result;
      });
    activeProtocol = protocol;
    const authTimer = setTimeout(() => ws.close(), 5000);
    let chain = Promise.resolve();
    ws.onmessage = event => {
      let message;
      try {
        if (closed || typeof event.data !== 'string' || new TextEncoder().encode(event.data).length > FrameFetchIdentity.MAX_MESSAGE_BYTES) throw new Error('invalid_message');
        message = JSON.parse(event.data);
        if (!message || typeof message !== 'object' || Array.isArray(message)) throw new Error('invalid_message');
      } catch { ws.close(); return; }
      // A parse may occupy the serial request chain for 30 seconds.
      // Authenticated heartbeat frames must still refresh the connection.
      if (protocol.authenticated && Object.keys(message).join(',') === 'type' && ['ping', 'pong', 'ready'].includes(message.type)) {
        lastSeen = Date.now();
        void protocol.receive(message).catch(() => ws.close());
        return;
      }
      chain = chain.then(async () => {
        if (closed) return;
        await protocol.receive(message);
        lastSeen = Date.now();
        if (protocol.authenticated && !heartbeat) {
          clearTimeout(authTimer);
          backoff.reset();
          heartbeat = setInterval(() => {
            if (Date.now() - lastSeen > 45000) ws.close();
            else send({ type: 'ping' });
          }, 20000);
        }
      }).catch(() => ws.close());
    };
    ws.onerror = () => ws.close();
    ws.onclose = () => {
      closed = true;
      clearTimeout(authTimer);
      clearInterval(heartbeat);
      if (socket === ws) { socket = null; activeProtocol = null; scheduleRetry(); }
    };
  } catch { socket = null; scheduleRetry(); }
  finally { starting = false; }
}
void initialize();
