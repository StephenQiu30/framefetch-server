/* Listeners are registered synchronously before configuration/connection work. */
importScripts('protocol.js');
importScripts('yuanbao-account.js');
const ALARM = 'framefetch-identity-connect';
let socket = null;
let retryTimer = null;
let starting = false;
let retryAt = 0;
const backoff = new FrameFetchIdentity.Backoff();

chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === ALARM) void initialize(); });
chrome.runtime.onStartup.addListener(() => { void initialize(); });
chrome.runtime.onInstalled.addListener(() => { void initialize(); });

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
      deadlineMs => FrameFetchYuanbaoAccount.readExistingAccount(chrome, deadlineMs));
    const authTimer = setTimeout(() => ws.close(), 5000);
    let chain = Promise.resolve();
    ws.onmessage = event => {
      chain = chain.then(async () => {
        if (closed || typeof event.data !== 'string' || new TextEncoder().encode(event.data).length > FrameFetchIdentity.MAX_MESSAGE_BYTES) throw new Error('invalid_message');
        await protocol.receive(JSON.parse(event.data));
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
      if (socket === ws) { socket = null; scheduleRetry(); }
    };
  } catch { socket = null; scheduleRetry(); }
  finally { starting = false; }
}
void initialize();
