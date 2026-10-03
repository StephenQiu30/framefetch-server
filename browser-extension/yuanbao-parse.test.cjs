const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const fs = require('node:fs');
const { nativeParse, readExistingParse, MAX_CAPTURE_BYTES } = require('./yuanbao-parse.js');
const { Protocol, proof } = require('./protocol.js');
const ORIGIN = 'https://yuanbao.tencent.com';
const API_URL = ORIGIN + '/api/weixin/get_parse_result';
const SHARE = 'https://weixin.qq.com/sph/Synthetic123';
const ACCOUNT = 'synthetic-native-account';
const ID = 'c'.repeat(32);
const KEY = 'synthetic-test-only-pairing-key-32-bytes';
const clone = value => JSON.parse(JSON.stringify(value));
const captured = (extra = {}) => ({
  request_method: 'POST', request_url: API_URL, response_url: API_URL, http_status: 200,
  request_body: { type: 'video_channel_url', url: SHARE, scene: 1 }, payload: { code: 0, data: {} }, ...extra,
});
const axiosResponse = config => ({
  config: { ...config, data: JSON.stringify(config.data), headers: { 'X-ID': ACCOUNT } },
  request: { responseURL: API_URL, status: 200 }, status: 200, data: { code: 0, data: {} },
});
function nativePage(overrides = {}) {
  const calls = [], required = [], location = { origin: ORIGIN, href: ORIGIN + '/chat' };
  const http = {
    defaults: { headers: { 'X-ID': ACCOUNT } }, interceptors: { request: {}, response: {} },
    request: async config => {
      calls.push(config);
      return { ...axiosResponse(config),
        headers: { 'X-Token': 'synthetic-never-returned', 'X-Uskey': 'synthetic-never-returned' } };
    },
  };
  if (overrides.request) http.request = config => { calls.push(config); return overrides.request(config, http, location); };
  if (overrides.headers !== undefined) http.defaults.headers = overrides.headers;
  const exported = { instance: http, request() {} };
  function nativeFactory() { return { instance: {}, request: function() {}, interceptors: {} }; }
  const require = id => { required.push(id); return exported; };
  require.m = { syntheticNativeModule: nativeFactory };
  const chunks = [];
  chunks.push = chunk => chunk[2](require);
  const window = { webpackChunk_N_E: chunks };
  const context = vm.createContext({
    TextEncoder, URL, AbortController, setTimeout, clearTimeout, Date, crypto: webcrypto,
    self: window, top: window, location, ...overrides.context,
  });
  return { calls, required, context, http, location, require,
    run: async (probeOnly = false, url = SHARE, deadline = Date.now() + 10000) => clone(await vm.runInContext(
      '(' + nativeParse.toString() + ')(' + JSON.stringify(url) + ',' + deadline + ',' + probeOnly + ')', context)),
  };
}
function chromePage(overrides = {}) {
  const calls = [], tab = { id: 9, url: ORIGIN + '/chat', incognito: false };
  let executions = 0;
  const api = {
    tabs: {
      query: async details => { calls.push(['query', details]); return [tab]; },
      get: async id => { calls.push(['get', id]); return tab; },
    },
    scripting: { executeScript: async details => {
      calls.push(['execute', details]); executions++;
      assert.equal(details.func, nativeParse);
      assert.equal(details.world, 'MAIN');
      assert.deepEqual(details.args.slice(0, 1), [SHARE]);
      return [{ frameId: 0, documentId: 'document-one', result: details.args[2] ?
        { account_id: ACCOUNT } : { account_id: ACCOUNT, captured: captured() } }];
    } },
    ...overrides,
  };
  return { api, calls, tab, executions: () => executions };
}
function timedBridge() {
  let now = 0;
  const timers = new Set();
  const context = vm.createContext({
    URL, TextEncoder, Date: { now: () => now },
    setTimeout: (fn, delay) => { const timer = { fn, at: now + delay }; timers.add(timer); return timer; },
    clearTimeout: timer => timers.delete(timer),
  });
  vm.runInContext(fs.readFileSync(__dirname + '/yuanbao-parse.js', 'utf8'), context);
  return { read: context.FrameFetchYuanbaoParse.readExistingParse, timers, advance: ms => {
    now += ms;
    for (const timer of [...timers]) if (timer.at <= now) { timers.delete(timer); timer.fn(); }
  } };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const request = extra => ({ type: 'yuanbao_parse', request_id: ID, site: 'wechat_channels',
  canonical_share_url: SHARE, deadline: new Date(Date.now() + 60000).toISOString(), ...extra });
async function authenticated(readParse, config = {}) {
  const sent = [];
  const protocol = new Protocol({ pairingKey: KEY, domains: ['instagram.com'], yuanbaoParse: true, ...config },
    async () => [], value => sent.push(value), '1.1.0', readParse);
  const peer = 'd'.repeat(64);
  await protocol.receive({ type: 'challenge', nonce: peer });
  await protocol.receive({ type: 'proof', proof: await proof(KEY, 'server', protocol.own, peer) });
  return { protocol, sent };
}

test('fixed native request observes Axios metadata and exports no headers, token or browser material', async () => {
  const p = nativePage();
  assert.deepEqual(await p.run(true), { account_id: ACCOUNT });
  assert.equal(p.calls.length, 0);
  assert.deepEqual(await p.run(), { account_id: ACCOUNT, captured: captured() });
  assert.equal(p.calls.length, 1);
  const call = p.calls[0];
  assert.equal(call.url, API_URL);
  assert.equal(call.method, 'post');
  assert.deepEqual(clone(call.data), captured().request_body);
  assert.equal(call.returnResponse, true);
  assert.equal(call.hideTip, true);
  assert.ok(call.timeout > 0 && call.timeout <= 30000);
  assert.ok(call.signal instanceof AbortSignal);
  assert.equal('headers' in call, false);
});
test('native X-ID alone is the preflight account and no Storage or Cookie is accessed', async () => {
  const denied = new Proxy({}, { get() { throw new Error('synthetic-private-secret'); } });
  const p = nativePage({ headers: { common: { 'x-id': ACCOUNT } }, context: { localStorage: denied, sessionStorage: denied, document: denied } });
  assert.deepEqual(await p.run(), { account_id: ACCOUNT, captured: captured() });
  for (const headers of [{}, { 'X-ID': '' }, { 'X-ID': ' unsafe ' }, { 'X-ID': 'x\nsecret' }, { 'X-ID': 'x'.repeat(1025) }]) {
    const page = nativePage({ headers });
    const result = await page.run();
    assert.ok(['credential_missing', 'identity_material_invalid'].includes(result.cause));
    assert.equal(page.calls.length, 0);
  }
});
test('only a unique native exports shape in the precise top frame can execute', async () => {
  for (const mutate of [p => { p.context.top = {}; }, p => { p.location.origin = 'https://evil.test'; },
    p => { p.require.m = {}; }, p => { p.require.m.other = p.require.m.syntheticNativeModule; }]) {
    const p = nativePage(); mutate(p);
    const result = await p.run();
    assert.ok(['identity_origin_invalid', 'native_api_unavailable'].includes(result.cause));
    assert.equal(p.calls.length, 0);
    assert.deepEqual(p.required, [], 'ambiguous or unavailable native factories are never initialized');
  }
  for (const url of ['https://evil.test/sph/Synthetic123', SHARE + '?headers=secret', SHARE + '#x', 'https://weixin.qq.com/sph/a']) {
    const p = nativePage();
    assert.deepEqual(await p.run(false, url), { cause: 'identity_material_invalid' });
    assert.equal(p.calls.length, 0);
  }
});
test('observed method, URL, redirect, body, status and payload are checked, rather than replaced by constants', async () => {
  const mutations = [
    r => { r.config.method = 'get'; }, r => { r.config.url = 'https://evil.test/api/weixin/get_parse_result'; },
    r => { r.request.responseURL = API_URL + '?redirect=1'; }, r => { r.request.responseURL = 'https://evil.test/api'; },
    r => { r.config.data = '{"type":"video_channel_url","url":"other","scene":1}'; },
    r => { r.config.data = JSON.stringify({ ...captured().request_body, headers: {} }); },
    r => { r.config.data = '{broken'; }, r => { r.request.status = 204; },
    r => { r.data = ['unexpected']; }, r => { r.data = null; }, r => { r.status = 0; r.request.status = 0; },
  ];
  for (const mutate of mutations) {
    const p = nativePage({ request: async config => {
      const r = axiosResponse(config);
      mutate(r); return r;
    } });
    assert.deepEqual(await p.run(), { cause: 'parse_response_invalid' });
  }
});
test('real HTTP error response is captured; arbitrary native exceptions stay sanitized', async () => {
  const p = nativePage({ request: config => {
    const response = { ...axiosResponse(config), request: { responseURL: API_URL, status: 401 }, status: 401, data: { error: { code: '20000' } } };
    throw Object.assign(new Error('synthetic-private-error'), { response });
  } });
  assert.deepEqual(await p.run(), { account_id: ACCOUNT, captured: captured({ http_status: 401, payload: { error: { code: '20000' } } }) });
  assert.deepEqual(await nativePage({ request: () => { throw new Error('synthetic-private-secret'); } }).run(), { cause: 'parse_request_failed' });
});
test('actual Axios account header must match defaults after native interceptors, without exporting headers', async () => {
  for (const headers of [{ 'x-id': ACCOUNT }, { get: name => name === 'X-ID' ? ACCOUNT : undefined }]) {
    const p = nativePage({ request: async config => {
      const response = axiosResponse(config);
      response.config.headers = headers;
      return response;
    } });
    assert.deepEqual(await p.run(), { account_id: ACCOUNT, captured: captured() });
  }
  for (const [headers, cause] of [
    [undefined, 'identity_material_invalid'], [{}, 'identity_material_invalid'],
    [{ 'X-ID': '' }, 'identity_material_invalid'], [{ 'X-ID': ' unsafe ' }, 'identity_material_invalid'],
    [{ 'X-ID': 'synthetic-other-account' }, 'identity_account_conflict'],
    [{ get: () => 'synthetic-other-account' }, 'identity_account_conflict'],
    [{ 'X-ID': ACCOUNT, 'x-id': 'synthetic-other-account' }, 'identity_account_conflict'],
  ]) {
    const p = nativePage({ request: async config => {
      const response = axiosResponse(config);
      response.config.headers = headers;
      return response;
    } });
    const result = await p.run();
    assert.deepEqual(result, { cause });
    assert.equal(p.http.defaults.headers['X-ID'], ACCOUNT, 'unchanged defaults cannot hide a request interceptor account change');
    assert.equal('headers' in result, false);
  }
});
test('account or page navigation during a native request rejects the result', async () => {
  for (const navigation of [false, true]) {
    const p = nativePage({ request: async (config, http, location) => {
      if (navigation) location.href = ORIGIN + '/other'; else http.defaults.headers['X-ID'] = 'synthetic-other-account';
      return axiosResponse(config);
    } });
    assert.deepEqual(await p.run(), { cause: navigation ? 'identity_navigation_changed' : 'identity_account_conflict' });
  }
});
test('MAIN limits returned JSON and aborts large download progress', async () => {
  const big = nativePage({ request: async config => ({ ...axiosResponse(config), data: { value: 'x'.repeat(MAX_CAPTURE_BYTES) } }) });
  assert.deepEqual(await big.run(), { cause: 'parse_response_invalid' });
  const progress = nativePage({ request: async config => {
    config.onDownloadProgress({ loaded: MAX_CAPTURE_BYTES + 1 });
    assert.equal(config.signal.aborted, true);
    throw new Error('synthetic-aborted');
  } });
  assert.deepEqual(await progress.run(), { cause: 'parse_response_invalid' });
});
test('MAIN operation deadline aborts a stalled native request and ignores its eventual response', async () => {
  let release;
  const pending = new Promise(done => { release = done; });
  const p = nativePage({ request: () => pending });
  const result = await p.run(false, SHARE, Date.now() + 30);
  assert.deepEqual(result, { cause: 'extension_timeout' });
  assert.equal(p.calls[0].signal.aborted, true);
  release({ data: { late: true } });
  await flush();
  assert.deepEqual(result, { cause: 'extension_timeout' });
  const expired = nativePage();
  assert.deepEqual(await expired.run(false, SHARE, Date.now() - 1), { cause: 'extension_timeout' });
  assert.equal(expired.calls.length, 0);
});
test('existing non-incognito tab and same document are checked before and after the one native request', async () => {
  const b = chromePage();
  assert.deepEqual(await readExistingParse(b.api, SHARE, Date.now() + 60000), { account_id: ACCOUNT, captured: captured() });
  assert.deepEqual(b.calls.map(c => c[0]), ['query', 'execute', 'get', 'execute', 'execute', 'get']);
  assert.deepEqual(b.calls[0][1], { url: ORIGIN + '/*' });
  const scripts = b.calls.filter(c => c[0] === 'execute').map(c => c[1]);
  assert.deepEqual(scripts[0].target, { tabId: 9, frameIds: [0] });
  assert.deepEqual(scripts[1].target, { tabId: 9, documentIds: ['document-one'] });
  assert.deepEqual(scripts.map(s => s.args[2]), [true, false, true]);
});
test('ambiguous, pending, wrong-origin or incognito tabs never run the native request', async () => {
  for (const [tabs, cause] of [
    [[], 'identity_page_unavailable'],
    [[{ id: 1, url: ORIGIN, incognito: true }], 'identity_page_unavailable'],
    [[{ id: 1, url: ORIGIN + '.evil.test', incognito: false }], 'identity_page_unavailable'],
    [[{ id: 1, url: 'https://user@yuanbao.tencent.com', incognito: false }], 'identity_page_unavailable'],
    [[{ id: 1, url: ORIGIN, incognito: false }, { id: 2, url: ORIGIN + '/chat', incognito: false }], 'identity_tab_ambiguous'],
    [[{ id: 1, url: ORIGIN, incognito: false, pendingUrl: ORIGIN }], 'identity_navigation_changed'],
  ]) {
    let executions = 0;
    const b = chromePage({ tabs: { query: async () => tabs }, scripting: { executeScript: async () => { executions++; } } });
    assert.deepEqual(await readExistingParse(b.api, SHARE, Date.now() + 1000), { cause });
    assert.equal(executions, 0);
  }
});
test('same-URL document replacement and account switching reject captured material', async () => {
  for (const mode of ['document', 'account', 'navigation']) {
    let count = 0;
    const b = chromePage();
    b.api.scripting.executeScript = async details => [{ frameId: 0,
      documentId: ++count === 2 && mode === 'document' ? 'document-two' : 'document-one',
      result: details.args[2] ? { account_id: count === 3 && mode === 'account' ? 'other' : ACCOUNT } : { account_id: ACCOUNT, captured: captured() } }];
    if (mode === 'navigation') b.api.tabs.get = async () => ({ ...b.tab, url: ORIGIN + '/other' });
    assert.deepEqual(await readExistingParse(b.api, SHARE, Date.now() + 1000),
      { cause: mode === 'account' ? 'identity_account_conflict' : 'identity_navigation_changed' });
  }
});
test('stalled Chrome APIs release the operation without performing late work or returning late material', async () => {
  for (const phase of ['query', 'script']) {
    let release, executions = 0;
    const pending = new Promise(done => { release = done; });
    const b = chromePage();
    if (phase === 'query') b.api.tabs.query = () => pending;
    b.api.scripting.executeScript = () => { executions++; return pending; };
    const clock = timedBridge();
    const operation = clock.read(b.api, SHARE, 10);
    await flush(); clock.advance(10);
    assert.deepEqual(clone(await operation), { cause: 'extension_timeout' });
    assert.equal(clock.timers.size, 0);
    release(phase === 'query' ? [b.tab] : [{ frameId: 0, documentId: 'one', result: { account_id: ACCOUNT } }]);
    await flush();
    assert.equal(executions, phase === 'query' ? 0 : 1);
  }
});
test('authenticated fixed protocol alone may call native parse and normal Cookie requests still work', async () => {
  let calls = 0;
  const reader = async (url, deadline) => {
    calls++; assert.equal(url, SHARE); assert.ok(deadline <= Date.now() + 30000);
    return { account_id: ACCOUNT, captured: captured() };
  };
  const unauthenticated = new Protocol({ yuanbaoParse: true }, async () => [], () => {}, '1.1.0', reader);
  await assert.rejects(unauthenticated.receive(request()), /unauthenticated/);
  assert.equal(calls, 0);
  const { protocol, sent } = await authenticated(reader);
  await protocol.receive(request());
  assert.deepEqual(sent.at(-1), { type: 'yuanbao_parse', request_id: ID, account_id: ACCOUNT, captured: captured() });
  await protocol.receive({ type: 'cookies', request_id: 'e'.repeat(32), domains: ['instagram.com'], deadline: new Date(Date.now() + 60000).toISOString() });
  assert.deepEqual(sent.at(-1), { type: 'cookies', request_id: 'e'.repeat(32), cookies: [] });
  protocol.config.yuanbaoParse = false;
  await assert.rejects(protocol.receive(request()), /undeclared_source/);
  assert.equal(calls, 1);
});
test('protocol rejects arbitrary URL, script, fields, site and malformed deadlines before calling Chrome', async () => {
  let calls = 0;
  const { protocol } = await authenticated(async () => { calls++; return {}; });
  for (const extra of [{ canonical_share_url: 'https://evil.test' }, { script: 'evil' }, { headers: {} },
    { site: 'youtube' }, { deadline: 'bad' }, { deadline: undefined }, { request_id: [ID] },
    { canonical_share_url: [SHARE] }]) await assert.rejects(protocol.receive(request(extra)));
  assert.equal(calls, 0);
});
test('protocol prevents unexpected returned material or mismatched captured requests from crossing the socket', async () => {
  const bad = [
    { account_id: ACCOUNT, auth_token: 'synthetic-private', captured: captured() }, { cause: 'synthetic-private' },
    { account_id: ACCOUNT, captured: captured({ response_url: 'https://evil.test' }) },
    { account_id: ACCOUNT, captured: captured({ request_body: { ...captured().request_body, scene: true } }) },
    { account_id: ACCOUNT, captured: captured({ payload: { value: 'x'.repeat(MAX_CAPTURE_BYTES) } }) },
  ];
  for (const result of bad) {
    const { protocol, sent } = await authenticated(async () => result);
    await assert.rejects(protocol.receive(request()), /invalid_parse_response/);
    assert.equal(sent.length, 2);
    assert.equal(protocol.busy, false);
  }
});
test('protocol reports only safe failures and times out a stalled callback without late sends', async () => {
  const failure = await authenticated(async () => ({ cause: 'native_api_unavailable' }));
  await failure.protocol.receive(request());
  assert.deepEqual(failure.sent.at(-1), { type: 'yuanbao_parse', request_id: ID, cause: 'native_api_unavailable' });
  let release;
  const pending = new Promise(done => { release = done; });
  const { protocol, sent } = await authenticated(() => pending);
  await protocol.receive(request({ deadline: new Date(Date.now() + 20).toISOString() }));
  assert.deepEqual(sent.at(-1), { type: 'yuanbao_parse', request_id: ID, cause: 'extension_timeout' });
  assert.equal(protocol.busy, false);
  const count = sent.length;
  release({ account_id: ACCOUNT, captured: captured() }); await flush();
  assert.equal(sent.length, count);
  await protocol.receive({ type: 'ping' });
  assert.deepEqual(sent.at(-1), { type: 'pong' });
});
