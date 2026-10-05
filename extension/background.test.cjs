const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const { webcrypto } = require('node:crypto');
const { proof } = require('./protocol.js');
const KEY = 'synthetic-test-only-pairing-key-32-bytes';
function worker(chromeApi = {}, transport) {
  const listeners = {}, sockets = [], timers = [], intervals = [], alarms = new Map();
  let now = 0;
  const listener = key => ({ addListener: callback => { listeners[key] = callback; }, removeListener: callback => { if (listeners[key] === callback) delete listeners[key]; } });
  class WebSocket {
    static OPEN = 1;
    constructor(url) { this.url = url; this.readyState = 1; this.sent = []; sockets.push(this); }
    send(message) { this.sent.push(JSON.parse(message)); }
    close() { if (this.readyState !== 3) { this.readyState = 3; this.onclose?.(); } }
  }
  const context = vm.createContext({
    TextEncoder, TextDecoder, Request, AbortController, URL, crypto: webcrypto, WebSocket, Date: { now: () => now, parse: Date.parse },
    fetch: async url => { if (typeof url !== 'string') return transport(url); assert.equal(url, 'chrome-extension://test/config.local.json'); return { ok: true, json: async () => ({ pairingKey: KEY, port: 19101, domains: ['instagram.com'], yuanbaoParse: true }) }; },
    chrome: { alarms: { onAlarm: listener('alarm'), get: async name => alarms.get(name), create: async (name, spec) => { alarms.set(name, spec); } },
      declarativeNetRequest: { getEnabledRulesets: async () => ['yuanbao-http'] },
      runtime: { id: 'test', onMessage: listener('message'), onStartup: listener('startup'), onInstalled: listener('installed'), getManifest: () => ({ version: '1.0.0' }), getURL: name => 'chrome-extension://test/' + name },
      ...chromeApi, cookies: { getAll: async () => [], get: async () => null, onChanged: listener('cookieChanged'), ...chromeApi.cookies } },
    setTimeout: (fn, ms) => { const timer = { fn, ms, active: true }; timers.push(timer); return timer; },
    clearTimeout: timer => { if (timer) timer.active = false; },
    setInterval: (fn, ms) => { const timer = { fn, ms, active: true }; intervals.push(timer); return timer; },
    clearInterval: timer => { if (timer) timer.active = false; },
  });
  context.importScripts = name => {
    assert.ok(['protocol.js', 'yuanbao-http.js'].includes(name));
    vm.runInContext(fs.readFileSync(__dirname + '/' + name, 'utf8'), context);
  };
  vm.runInContext(fs.readFileSync(__dirname + '/background.js', 'utf8'), context);
  const flush = async () => { await new Promise(resolve => setImmediate(resolve)); await new Promise(resolve => setImmediate(resolve)); };
  return { context, listeners, sockets, timers, intervals, alarms, flush, advance: ms => { now += ms; } };
}
test('listeners registered synchronously; every worker start rebuilds alarm; initialization idempotent', async () => {
  const w = worker();
  assert.deepEqual(Object.keys(w.listeners), ['alarm', 'startup', 'installed', 'message']);
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
test('pairing JSON is local only and never declared web accessible', () => {
  const template = JSON.parse(fs.readFileSync(__dirname + '/manifest.template.json', 'utf8'));
  assert.equal('web_accessible_resources' in template, false);
  assert.equal('host_permissions' in template, false);
  const { execFileSync, spawnSync } = require('node:child_process');
  const tracked = execFileSync('git', ['ls-files', '--', 'extension/config.local.json', 'extension/manifest.json'], { cwd: __dirname + '/..', encoding: 'utf8' });
  assert.equal(tracked, '');
  for (const name of ['config.local.json', 'manifest.json']) {
    assert.equal(spawnSync('git', ['check-ignore', '--quiet', '--', name], { cwd: __dirname }).status, 0);
  }
});
test('stalled Cookie APIs return a bounded failure and keep the worker chain usable without late exports', async () => {
  for (const limit of [10, 5000]) {
    for (const lateFailure of [false, true]) {
      let release, reject, reads = 0;
      const pending = new Promise((done, fail) => { release = done; reject = fail; });
      const w = worker({ cookies: { getAll: () => ++reads === 1 ? pending : Promise.resolve([]) } });
      await w.flush();
      const ws = w.sockets[0], server = 'd'.repeat(64);
      ws.onmessage({ data: JSON.stringify({ type: 'challenge', nonce: server }) }); await w.flush();
      ws.onmessage({ data: JSON.stringify({ type: 'proof', proof: await proof(KEY, 'server', ws.sent[0].nonce, server) }) });
      for (let i = 0; i < 20 && !w.intervals.length; i++) await w.flush();
      ws.onmessage({ data: JSON.stringify({
        type: 'cookies', request_id: 'c'.repeat(32), domains: ['instagram.com'],
        deadline: new Date(limit === 5000 ? 60000 : limit).toISOString(),
      }) });
      ws.onmessage({ data: JSON.stringify({ type: 'cookies', request_id: 'e'.repeat(32), domains: ['instagram.com'], deadline: new Date(60000).toISOString() }) });
      ws.onmessage({ data: JSON.stringify({ type: 'ping' }) });
      await w.flush();
      const timer = w.timers.find(item => item.active && item.ms === limit);
      assert.ok(timer, 'Cookie API calls must have a shared deadline timer');
      w.advance(limit); timer.fn(); await w.flush();
      assert.deepEqual(ws.sent.slice(-3), [
        { type: 'pong' },
        { type: 'cookies', request_id: 'c'.repeat(32), cause: 'extension_timeout' },
        { type: 'cookies', request_id: 'e'.repeat(32), cookies: [] },
      ]);
      assert.equal(ws.readyState, 1);
      assert.equal(timer.active, false);
      assert.equal(reads, 2);
      const count = ws.sent.length;
      if (lateFailure) reject(new Error('synthetic-private-error'));
      else release([{ domain: 'instagram.com', name: 'sessionid', value: 'synthetic-late-cookie', path: '/' }]);
      await w.flush();
      assert.equal(ws.sent.length, count);
    }
  }
});

test('authenticated heartbeats remain responsive during a stalled HTTP identity read, with no late request', async () => {
  let release, reads = 0;
  const pending = new Promise(done => { release = done; });
  const w = worker({ cookies: {
    get: async () => { reads++; return pending; },
    getAll: async () => { reads++; return []; },
  } }, () => assert.fail('late HTTP must not start'));
  await w.flush();
  const ws = w.sockets[0], server = 'd'.repeat(64);
  ws.onmessage({ data: JSON.stringify({ type: 'challenge', nonce: server }) }); await w.flush();
  ws.onmessage({ data: JSON.stringify({ type: 'proof', proof: await proof(KEY, 'server', ws.sent[0].nonce, server) }) });
  for (let i = 0; i < 20 && !w.intervals.length; i++) await w.flush();
  const request = { type: 'yuanbao_parse', request_id: 'c'.repeat(32), site: 'wechat_channels',
    canonical_share_url: 'https://weixin.qq.com/sph/Synthetic123', deadline: new Date(10).toISOString() };
  ws.onmessage({ data: JSON.stringify(request) });
  ws.onmessage({ data: JSON.stringify({ type: 'cookies', request_id: 'e'.repeat(32), domains: ['instagram.com'], deadline: new Date(60000).toISOString() }) });
  ws.onmessage({ data: JSON.stringify({ type: 'ping' }) });
  await w.flush();
  const timer = w.timers.find(t => t.active && t.ms === 10);
  assert.ok(timer);
  w.advance(10); timer.fn(); await w.flush();
  assert.deepEqual(ws.sent.slice(-3), [ { type: 'pong' },
    { type: 'yuanbao_parse', request_id: request.request_id, cause: 'extension_timeout' },
    { type: 'cookies', request_id: 'e'.repeat(32), cookies: [] } ]);
  assert.equal(ws.readyState, 1);
  assert.equal(reads, 2);
  const count = ws.sent.length;
  release([]); await w.flush();
  assert.equal(ws.sent.length, count);
});

test('popup exposes only credential availability, admits only its own sender, and opens login only on explicit action', async () => {
  const pages = [], reads = [];
  const w = worker({ tabs: { create: async details => { pages.push(details); } },
    cookies: { get: async details => {
      reads.push(details);
      assert.equal(details.url, 'https://yuanbao.tencent.com/api/weixin/get_parse_result');
      assert.ok(['hy_user', 'hy_token'].includes(details.name));
      return { name: details.name, value: 'synthetic-secret', domain: '.tencent.com', path: '/', session: true };
    } } }, () => assert.fail('status must not make HTTP calls'));
  await w.flush();
  const listener = w.listeners.message;
  const sender = { id: 'test', url: 'chrome-extension://test/popup.html' };
  for (const other of [{ ...sender, id: 'other' }, { ...sender, url: 'https://evil.test/' }]) {
    assert.equal(listener({ type: 'login_yuanbao' }, other, () => assert.fail('untrusted sender')), false);
  }
  assert.equal(listener({ type: 'status', script: 'evil' }, sender, () => assert.fail('unexpected fields')), false);
  let reply;
  listener({ type: 'status' }, sender, value => { reply = value; }); await w.flush();
  assert.deepEqual(JSON.parse(JSON.stringify(reply)), { connected: false, version: '1.0.0', session: 'available', busy: false, cause: null });
  assert.equal(JSON.stringify(reply).includes('synthetic-secret'), false);
  assert.deepEqual(pages, []);
  assert.equal(reads.length, 3);
  listener({ type: 'login_yuanbao' }, sender, value => { reply = value; }); await w.flush();
  assert.deepEqual(JSON.parse(JSON.stringify(pages)), [{ url: 'https://yuanbao.tencent.com/', active: true }]);
});
