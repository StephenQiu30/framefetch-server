const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const { webcrypto } = require('node:crypto');
const { proof } = require('./protocol.js');
const KEY = 'synthetic-test-only-pairing-key-32-bytes';
function worker() {
  const listeners = {}, sockets = [], timers = [], intervals = [], alarms = new Map();
  let now = 0;
  const listener = key => ({ addListener: callback => { listeners[key] = callback; } });
  class WebSocket {
    static OPEN = 1;
    constructor(url) { this.url = url; this.readyState = 1; this.sent = []; sockets.push(this); }
    send(message) { this.sent.push(JSON.parse(message)); }
    close() { if (this.readyState !== 3) { this.readyState = 3; this.onclose?.(); } }
  }
  const context = vm.createContext({
    TextEncoder, crypto: webcrypto, WebSocket, Date: { now: () => now },
    FRAMEFETCH_CONFIG: { pairingKey: KEY, port: 19101, domains: ['instagram.com'] },
    chrome: { alarms: { onAlarm: listener('alarm'), get: async name => alarms.get(name), create: async (name, spec) => { alarms.set(name, spec); } },
      runtime: { onStartup: listener('startup'), onInstalled: listener('installed'), getManifest: () => ({ version: '1.0.0' }) },
      cookies: { getAll: async () => [] } },
    setTimeout: (fn, ms) => { const timer = { fn, ms, active: true }; timers.push(timer); return timer; },
    clearTimeout: timer => { if (timer) timer.active = false; },
    setInterval: (fn, ms) => { const timer = { fn, ms, active: true }; intervals.push(timer); return timer; },
    clearInterval: timer => { if (timer) timer.active = false; },
  });
  context.importScripts = name => { if (name === 'protocol.js') vm.runInContext(fs.readFileSync(__dirname + '/protocol.js', 'utf8'), context); };
  vm.runInContext(fs.readFileSync(__dirname + '/background.js', 'utf8'), context);
  const flush = async () => { await new Promise(resolve => setImmediate(resolve)); await new Promise(resolve => setImmediate(resolve)); };
  return { context, listeners, sockets, timers, intervals, alarms, flush, advance: ms => { now += ms; } };
}
test('listeners registered synchronously; every worker start rebuilds alarm; initialization idempotent', async () => {
  const w = worker();
  assert.deepEqual(Object.keys(w.listeners), ['alarm', 'startup', 'installed']);
  await w.flush();
  w.listeners.startup(); w.listeners.installed(); w.listeners.alarm({ name: 'framefetch-identity-connect' });
  await w.flush();
  assert.equal(w.sockets.length, 1);
  assert.equal(w.alarms.get('framefetch-identity-connect').periodInMinutes, 0.5);
  w.alarms.clear();
  w.listeners.startup(); await w.flush();
  assert.equal(w.alarms.size, 1);
  assert.equal(w.sockets[0].url, 'ws://127.0.0.1:19101/extension');
});
test('disconnect and failed startup reconnect immediately then back off; alarm respects retry deadline', async () => {
  const w = worker(); await w.flush();
  w.sockets[0].close();
  let retry = w.timers.at(-1);
  assert.equal(retry.ms, 0); retry.fn(); await w.flush();
  w.sockets[1].close(); retry = w.timers.at(-1);
  assert.equal(retry.ms, 1000);
  w.listeners.alarm({ name: 'framefetch-identity-connect' }); await w.flush();
  assert.equal(w.sockets.length, 2);
  w.advance(1000); retry.fn(); await w.flush();
  assert.equal(w.sockets.length, 3);
  w.sockets[2].close(); assert.equal(w.timers.at(-1).ms, 2000);
});
test('authentication times out after five seconds without Cookie access', async () => {
  const w = worker(); await w.flush();
  const timer = w.timers.find(t => t.ms === 5000);
  timer.fn();
  assert.equal(w.sockets[0].readyState, 3);
  assert.equal(w.sockets[0].sent.length, 0);
});
test('20-second heartbeat only after server authentication, stale connection closes after wake', async () => {
  const w = worker(); await w.flush();
  const ws = w.sockets[0];
  const server = 'd'.repeat(64);
  ws.onmessage({ data: JSON.stringify({ type: 'challenge', nonce: server }) }); await w.flush();
  const own = ws.sent[0].nonce;
  ws.onmessage({ data: JSON.stringify({ type: 'proof', proof: await proof(KEY, 'server', own, server) }) });
  for (let i = 0; i < 20 && !w.intervals.length; i++) await w.flush();
  assert.equal(w.intervals[0].ms, 20000);
  w.intervals[0].fn(); assert.equal(ws.sent.at(-1).type, 'ping');
  w.advance(46000); w.intervals[0].fn();
  assert.equal(ws.readyState, 3);
  assert.equal(w.intervals[0].active, false);
});
