const { test } = require('node:test');
const assert = require('node:assert/strict');
const { parseShare, status, PARSE_URL, MAX_CAPTURE_BYTES } = require('./yuanbao-http.js');
const { Protocol, proof } = require('./protocol.js');
const SHARE = 'https://weixin.qq.com/sph/Synthetic123';
const ACCOUNT = 'synthetic-account';
const TOKEN = 'synthetic-private-token-never-exported';
const KEY = 'synthetic-test-only-pairing-key-32-bytes';
const ID = 'c'.repeat(32);
const captured = (extra = {}) => ({ request_method: 'POST', request_url: PARSE_URL,
  response_url: PARSE_URL, http_status: 200,
  request_body: { type: 'video_channel_url', url: SHARE, scene: 1 }, payload: { code: 0, data: {} }, ...extra });
const cookie = (name, value) => ({ name, value, domain: '.tencent.com', path: '/', session: true });
function response(payload = { code: 0, data: {} }, options = {}) {
  const r = new Response(typeof payload === 'string' ? payload : JSON.stringify(payload), options);
  Object.defineProperty(r, 'url', { value: options.url ?? PARSE_URL });
  Object.defineProperty(r, 'redirected', { value: options.redirected ?? false });
  return r;
}
function client() {
  const calls = [], listeners = new Set();
  let account = ACCOUNT, token = TOKEN;
  const api = { declarativeNetRequest: { getEnabledRulesets: async () => ['yuanbao-http'] }, cookies: {
    get: async details => {
      calls.push(details);
      return cookie(details.name, details.name === 'hy_user' ? account : token);
    },
    getAll: () => assert.fail('HTTP auth must use named URL-scoped get(), not domain-filtered getAll()'),
    onChanged: { addListener: fn => listeners.add(fn), removeListener: fn => listeners.delete(fn) },
  } };
  return { api, calls, listeners, change: value => { account = value; },
    token: value => { token = value; },
    run: (transport = async () => response(), deadline = Date.now() + 1000, url = SHARE) => parseShare(api, url, deadline, transport) };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const request = extra => ({ type: 'yuanbao_parse', request_id: ID, site: 'wechat_channels',
  canonical_share_url: SHARE, deadline: new Date(Date.now() + 60000).toISOString(), ...extra });
async function authenticated(readParse, config = {}) {
  const sent = [];
  const protocol = new Protocol({ pairingKey: KEY, domains: ['instagram.com'], yuanbaoParse: true, ...config },
    async () => [], value => sent.push(value), '1.3.3', readParse);
  const peer = 'd'.repeat(64);
  await protocol.receive({ type: 'challenge', nonce: peer });
  await protocol.receive({ type: 'proof', proof: await proof(KEY, 'server', protocol.own, peer) });
  return { protocol, sent };
}

test('account-bound HTTP works without tabs, scripting, DOM or storage and exports no credentials', async () => {
  const c = client();
  let requests = 0;
  const result = await c.run(async request => {
    requests++;
    assert.equal(request.url, PARSE_URL);
    assert.equal(request.method, 'POST');
    assert.equal(request.credentials, 'include');
    assert.equal(request.redirect, 'error');
    assert.equal(request.cache, 'no-store');
    assert.equal(request.headers.get('x-id'), ACCOUNT);
    assert.equal(request.headers.get('x-token'), TOKEN);
    assert.equal(request.headers.get('x-webversion'), '2.87.2');
    assert.equal(request.headers.get('accept'), 'application/json, text/plain, */*');
    assert.deepEqual(await request.json(), captured().request_body);
    return response();
  });
  assert.deepEqual(result, { account_id: ACCOUNT, captured: captured() });
  assert.equal(requests, 1);
  assert.equal(JSON.stringify(result).includes(TOKEN), false);
  assert.equal(c.calls.length, 6);
  assert.ok(c.calls.every(c => c.url === PARSE_URL && ['hy_user', 'hy_token'].includes(c.name)));
  assert.deepEqual(c.calls.map(c => c.name), ['hy_user', 'hy_token', 'hy_user', 'hy_user', 'hy_token', 'hy_user']);
  assert.equal(c.listeners.size, 0);
});
test('missing or disabled origin rules stop before Cookie access and HTTP', async () => {
  for (const getEnabledRulesets of [async () => [], async () => ['unrelated'],
    async () => { throw new Error(TOKEN); }]) {
    const c = client();
    c.api.declarativeNetRequest.getEnabledRulesets = getEnabledRulesets;
    assert.deepEqual(await c.run(() => assert.fail('must not request')),
      { cause: 'yuanbao_request_rule_unavailable' });
    assert.equal(c.calls.length, 0);
    assert.equal(c.listeners.size, 0);
  }
  const c = client();
  delete c.api.declarativeNetRequest;
  assert.deepEqual(await c.run(() => assert.fail('must not request')),
    { cause: 'yuanbao_request_rule_unavailable' });
  assert.equal(c.calls.length, 0);
});
test('a stalled ruleset check shares the deadline and never starts late Cookie or HTTP work', async () => {
  const c = client();
  let release;
  c.api.declarativeNetRequest.getEnabledRulesets = () => new Promise(resolve => { release = resolve; });
  assert.deepEqual(await c.run(() => assert.fail('must not request'), Date.now() + 10),
    { cause: 'extension_timeout' });
  release(['yuanbao-http']); await flush();
  assert.equal(c.calls.length, 0);
  assert.equal(c.listeners.size, 0);
});
test('missing, partitioned, expired or wrong-scope credentials stop before HTTP', async () => {
  const invalid = [
    [null, 'credential_missing'],
    [{ ...cookie('hy_user', ACCOUNT), partitionKey: { topLevelSite: 'https://evil.test' } }, 'identity_material_invalid'],
    [{ ...cookie('hy_user', ACCOUNT), domain: '.evil.test' }, 'identity_material_invalid'],
    [{ ...cookie('hy_user', ACCOUNT), path: '/unrelated' }, 'identity_material_invalid'],
    [{ ...cookie('hy_user', ACCOUNT), session: false, expirationDate: 1 }, 'identity_material_invalid'],
    [cookie('hy_user', ' unsafe '), 'identity_material_invalid'],
    [cookie('hy_user', 'bad\r\nheader'), 'identity_material_invalid'],
    [cookie('hy_user', 'x'.repeat(1025)), 'identity_material_invalid'],
  ];
  for (const [value, cause] of invalid) {
    const c = client();
    c.api.cookies.get = async details => details.name === 'hy_user' ? value : cookie('hy_token', TOKEN);
    assert.deepEqual(await c.run(() => assert.fail('must not request')), { cause });
    assert.equal(c.listeners.size, 0);
  }
});
test('an account switch between named Cookie reads stops before HTTP', async () => {
  const c = client();
  let reads = 0;
  c.api.cookies.get = async details => cookie(details.name,
    details.name === 'hy_token' ? TOKEN : ++reads === 1 ? ACCOUNT : 'other-account');
  assert.deepEqual(await c.run(() => assert.fail('must not request')), { cause: 'identity_account_conflict' });
  assert.equal(c.listeners.size, 0);
});
test('canonical URL and deadline validation never acquire credentials or send HTTP', async () => {
  for (const url of ['https://evil.test', SHARE + '?x=1', SHARE + '#x', SHARE + '/x']) {
    const c = client();
    assert.deepEqual(await c.run(() => assert.fail('must not request'), Date.now() + 1000, url), { cause: 'identity_material_invalid' });
    assert.equal(c.calls.length, 0);
  }
  for (const deadline of [NaN, undefined, Infinity, Date.now() - 1]) {
    const c = client();
    assert.deepEqual(await parseShare(c.api, SHARE, deadline, () => assert.fail('must not request')), { cause: 'extension_timeout' });
    assert.equal(c.calls.length, 0);
  }
});
test('only an exact final HTTP response is accepted, including real authentication errors', async () => {
  for (const options of [{ url: 'https://evil.test/' }, { url: PARSE_URL + '?x=1' }, { redirected: true }]) {
    assert.deepEqual(await client().run(async () => response({}, options)), { cause: 'yuanbao_response_source_invalid' });
  }
  assert.deepEqual(await client().run(async () => response({ error: { code: '20000' } }, { status: 401 })),
    { account_id: ACCOUNT, captured: captured({ http_status: 401, payload: { error: { code: '20000' } } }) });
  assert.deepEqual(await client().run(() => { throw new Error(TOKEN); }), { cause: 'parse_request_failed' });
});
test('response streaming has a byte limit and rejects malformed JSON, UTF-8 and token echoes', async () => {
  for (const [body,cause] of [['{broken', 'yuanbao_response_json_invalid'], ['null', 'yuanbao_response_json_invalid'],
    ['[]', 'yuanbao_response_json_invalid'], [{ echo: TOKEN }, 'yuanbao_response_credential_echo'],
    [{ value: 'x'.repeat(MAX_CAPTURE_BYTES) }, 'yuanbao_response_size_invalid']]) {
    assert.deepEqual(await client().run(async () => response(body)), { cause });
  }
  assert.deepEqual(await client().run(async () => response({}, { headers: { 'content-length': String(MAX_CAPTURE_BYTES + 1) } })), { cause: 'yuanbao_response_size_invalid' });
  const invalid = new Response(new Uint8Array([0xff]));
  Object.defineProperty(invalid, 'url', { value: PARSE_URL });
  assert.deepEqual(await client().run(async () => invalid), { cause: 'yuanbao_response_utf8_invalid' });
});
test('cookie account changes reject the response; token rotation for the same account is allowed', async () => {
  const c = client();
  assert.deepEqual(await c.run(async () => { c.change('other-account'); return response(); }), { cause: 'identity_account_conflict' });
  const refresh = client();
  assert.deepEqual(await refresh.run(async () => { refresh.token('synthetic-refreshed-token'); return response(); }), { account_id: ACCOUNT, captured: captured() });
});
test('a change event aborts the HTTP request even when the account later returns to its original value', async () => {
  const c = client();
  const result = await c.run(async request => {
    for (const listener of c.listeners) listener({ cookie: cookie('hy_user', 'other-account'), removed: false });
    assert.equal(request.signal.aborted, true);
    return response();
  });
  assert.deepEqual(result, { cause: 'identity_account_conflict' });
  assert.equal(c.listeners.size, 0);
});
test('expired and stalled transport is aborted and late completion cannot publish credentials', async () => {
  let release, signal;
  const pending = new Promise(done => { release = done; });
  const c = client();
  const result = await c.run(request => { signal = request.signal; return pending; }, Date.now() + 40);
  assert.deepEqual(result, { cause: 'extension_timeout' });
  assert.equal(signal.aborted, true);
  assert.equal(c.listeners.size, 0);
  release(response({ late: true })); await flush();
  assert.deepEqual(result, { cause: 'extension_timeout' });
});
test('stalled Cookie and body reads share the deadline and never start late HTTP', async () => {
  const c = client();
  let release;
  c.api.cookies.get = () => new Promise(done => { release = done; });
  assert.deepEqual(await c.run(() => assert.fail('late HTTP'), Date.now() + 30), { cause: 'extension_timeout' });
  release(cookie('hy_user', ACCOUNT)); await flush();
  const stream = new ReadableStream({ start() {} });
  const r = new Response(stream); Object.defineProperty(r, 'url', { value: PARSE_URL });
  assert.deepEqual(await client().run(async () => r, Date.now() + 30), { cause: 'extension_timeout' });
});
test('popup status exposes only availability and performs no HTTP or page operation', async () => {
  const c = client();
  assert.equal(await status(c.api), 'available');
  c.api.cookies.get = async () => null;
  assert.equal(await status(c.api), 'missing');
  c.api.cookies.get = async () => { throw new Error(TOKEN); };
  assert.equal(await status(c.api), 'unavailable');
});

test('authenticated fixed protocol alone may call HTTP parse and normal Cookie requests still work', async () => {
  let calls = 0;
  const reader = async (url, deadline) => {
    calls++; assert.equal(url, SHARE); assert.ok(deadline <= Date.now() + 30000);
    return { account_id: ACCOUNT, captured: captured() };
  };
  const unauthenticated = new Protocol({ yuanbaoParse: true }, async () => [], () => {}, '1.3.3', reader);
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
  const failure = await authenticated(async () => ({ cause: 'parse_response_invalid' }));
  await failure.protocol.receive(request());
  assert.deepEqual(failure.sent.at(-1), { type: 'yuanbao_parse', request_id: ID, cause: 'parse_response_invalid' });
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
