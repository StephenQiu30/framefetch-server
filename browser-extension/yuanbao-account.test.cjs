const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const { readAccount, readExistingAccount: readExistingAccountWithDeadline } = require('./yuanbao-account.js');
const { Protocol, proof } = require('./protocol.js');
const ORIGIN = 'https://yuanbao.tencent.com';
const ACCOUNT = { origin: ORIGIN, account_id: 'synthetic-account', auth_token: 'synthetic-token' };
const KEY = 'synthetic-test-only-pairing-key-32-bytes';
const ID = 'c'.repeat(32);
const futureDeadline = () => new Date(Date.now() + 60000).toISOString();
const readExistingAccount = (api, deadlineMs = Date.now() + 60000) => readExistingAccountWithDeadline(api, deadlineMs);
function page(values = {}, changes = {}) {
  const data = new Map(Object.entries(values));
  const window = {};
  const context = vm.createContext({
    TextEncoder, self: window, top: window, location: { origin: ORIGIN },
    localStorage: { getItem: key => data.get(key) ?? null, key: index => [...data.keys()][index] ?? null, get length() { return data.size; } },
    ...changes,
  });
  return { context, data, read: () => JSON.parse(JSON.stringify(vm.runInContext('(' + readAccount.toString() + ')()', context))) };
}
function browser(overrides = {}) {
  const tab = { id: 9, url: ORIGIN + '/chat', incognito: false };
  const calls = [];
  const p = page({ yb_user_id: ACCOUNT.account_id, yb_token: ACCOUNT.auth_token });
  const api = {
    tabs: {
      query: async details => { calls.push(['query', details]); return [tab]; },
      get: async id => { calls.push(['get', id]); return tab; },
    },
    scripting: {
      executeScript: async details => {
        calls.push(['execute', details]);
        assert.equal(details.func, readAccount);
        return [{ frameId: 0, documentId: 'document-one', result: p.read() }];
      },
    },
    ...overrides,
  };
  return { api, calls, tab, p };
}
function timedReader() {
  let now = 0;
  const timers = new Set();
  const context = vm.createContext({
    URL, TextEncoder, Date: { now: () => now },
    setTimeout: (fn, delay) => { const timer = { fn, at: now + delay }; timers.add(timer); return timer; },
    clearTimeout: timer => timers.delete(timer),
  });
  vm.runInContext(fs.readFileSync(__dirname + '/yuanbao-account.js', 'utf8'), context);
  return {
    read: context.FrameFetchYuanbaoAccount.readExistingAccount,
    timers,
    advance: ms => { now += ms; for (const timer of [...timers]) if (timer.at <= now) { timers.delete(timer); timer.fn(); } },
  };
}
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); };
test('fixed function exports only bounded primary account fields and no signatures or DOM', () => {
  const p = page({ yb_user_id: ACCOUNT.account_id, yb_token: ACCOUNT.auth_token, arbitrary_secret: 'must-not-read', 'LOCAL_OTHER': 'ignored' });
  const get = p.context.localStorage.getItem;
  const read = [];
  p.context.localStorage.getItem = key => { read.push(key); return get(key); };
  Object.defineProperty(p.context, 'document', { get() { throw new Error('DOM must not be read'); } });
  assert.deepEqual(p.read(), ACCOUNT);
  assert.deepEqual([...new Set(read)], ['yb_user_id', 'yb_token']);
});
test('fallback uses one matching bounded record; fields are never assembled across records', () => {
  assert.deepEqual(page({ LOCAL_AUTH_INFO_KEY_one: JSON.stringify({ userId: ACCOUNT.account_id, token: ACCOUNT.auth_token, ignored_signature: 'not-exported' }) }).read(), ACCOUNT);
  assert.equal(page({ LOCAL_AUTH_INFO_KEY_one: JSON.stringify({ userId: ACCOUNT.account_id }), LOCAL_AUTH_INFO_KEY_two: JSON.stringify({ token: ACCOUNT.auth_token }) }).read().cause, 'identity_material_invalid');
  assert.equal(page({ yb_user_id: ACCOUNT.account_id, LOCAL_AUTH_INFO_KEY_one: JSON.stringify({ userId: ACCOUNT.account_id, token: ACCOUNT.auth_token }) }).read().cause, 'credential_missing');
  assert.equal(page({ yb_user_id: ACCOUNT.account_id, yb_token: ACCOUNT.auth_token, LOCAL_AUTH_INFO_KEY_other: JSON.stringify({ userId: 'different', token: ACCOUNT.auth_token }) }).read().cause, 'identity_account_conflict');
});
test('missing, invalid UTF8/control and oversized account material is refused', () => {
  assert.deepEqual(page().read(), { cause: 'credential_missing' });
  for (const [account, token] of [['x'.repeat(1025), 't'], ['界'.repeat(342), 't'], ['a', 'x'.repeat(8193)], ['a', 'bad\ntoken'], [' a', 't'], ['a', '\ud800']]) {
    assert.deepEqual(page({ yb_user_id: account, yb_token: token }).read(), { cause: 'identity_material_invalid' });
  }
  assert.deepEqual(page({ LOCAL_AUTH_INFO_KEY_one: 'x'.repeat(16385) }).read(), { cause: 'identity_material_invalid' });
  assert.deepEqual(page(Object.fromEntries(Array.from({ length: 129 }, (_, i) => ['unrelated_' + i, 'not-read']))).read(), { cause: 'identity_material_invalid' });
  assert.deepEqual(page(Object.fromEntries(Array.from({ length: 9 }, (_, i) => ['LOCAL_AUTH_INFO_KEY_' + i, JSON.stringify({ userId: 'a', token: 't' })]))).read(), { cause: 'identity_material_invalid' });
});
test('exact origin and top frame are checked before any Storage read', () => {
  for (const changes of [{ location: { origin: 'https://yuanbao.tencent.com.evil.test' } }, { top: {} }]) {
    changes.localStorage = { getItem: () => { throw new Error('must not read'); } };
    assert.deepEqual(page({}, changes).read(), { cause: 'identity_origin_invalid' });
  }
});
test('navigation, account rotation, Storage exception and read bounds return fixed safe causes', () => {
  const navigating = page({ yb_user_id: 'a', yb_token: 't' });
  const get = navigating.context.localStorage.getItem;
  navigating.context.localStorage.getItem = key => { const value = get(key); navigating.context.location.origin = 'https://forbidden.invalid'; return value; };
  assert.deepEqual(navigating.read(), { cause: 'identity_navigation_changed' });
  const rotating = page({ yb_user_id: 'a', yb_token: 't' });
  let reads = 0;
  rotating.context.localStorage.getItem = key => key === 'yb_user_id' ? (++reads === 1 ? 'a' : 'b') : 't';
  assert.deepEqual(rotating.read(), { cause: 'identity_account_conflict' });
  assert.deepEqual(page({}, { localStorage: { getItem() { throw new Error('synthetic-private-secret'); } } }).read(), { cause: 'identity_storage_unavailable' });
});
test('only an existing non-incognito exact-origin top document is read in ISOLATED world', async () => {
  const b = browser();
  assert.deepEqual(await readExistingAccount(b.api), ACCOUNT);
  assert.deepEqual(b.calls[0], ['query', { url: ORIGIN + '/*' }]);
  const executes = b.calls.filter(c => c[0] === 'execute').map(c => c[1]);
  assert.equal(executes.length, 2);
  assert.deepEqual(executes[0].target, { tabId: 9, frameIds: [0] });
  assert.deepEqual(executes[1].target, { tabId: 9, documentIds: ['document-one'] });
  assert.ok(executes.every(c => c.world === 'ISOLATED' && Object.keys(c).sort().join(',') === 'func,target,world'));
});
test('absent, incognito, lookalike, ambiguous or navigating tabs are refused without script access', async () => {
  for (const [tabs, cause] of [
    [[], 'identity_page_unavailable'],
    [[{ id: 9, url: ORIGIN, incognito: true }], 'identity_page_unavailable'],
    [[{ id: 9, url: ORIGIN + '.evil.test', incognito: false }], 'identity_page_unavailable'],
    [[{ id: 9, url: ORIGIN, incognito: false }, { id: 10, url: ORIGIN, incognito: false }], 'identity_tab_ambiguous'],
    [[{ id: 9, url: ORIGIN, incognito: false, pendingUrl: ORIGIN + '/new' }], 'identity_navigation_changed'],
  ]) {
    const b = browser();
    b.api.tabs.query = async () => tabs;
    assert.deepEqual(await readExistingAccount(b.api), { cause });
    assert.equal(b.calls.length, 0);
  }
});
test('same-URL document replacement, child-frame result, account rotation and post-read navigation fail closed', async () => {
  for (const mode of ['document', 'child', 'account', 'navigation']) {
    const b = browser();
    let scripts = 0;
    b.api.scripting.executeScript = async () => {
      scripts++;
      return [{ frameId: mode === 'child' ? 1 : 0, documentId: mode === 'document' && scripts === 2 ? 'new-document' : 'document-one', result: { ...ACCOUNT, account_id: mode === 'account' && scripts === 2 ? 'different' : ACCOUNT.account_id } }];
    };
    if (mode === 'navigation') b.api.tabs.get = async () => ({ ...b.tab, url: ORIGIN + '/new' });
    const result = await readExistingAccount(b.api);
    assert.equal(result.cause, mode === 'account' ? 'identity_account_conflict' : 'identity_navigation_changed');
    assert.equal('auth_token' in result, false);
  }
  const b = browser();
  b.api.tabs.query = async () => { throw new Error('https://secret.invalid/?synthetic-private-secret'); };
  assert.deepEqual(await readExistingAccount(b.api), { cause: 'identity_page_unavailable' });
});
async function authenticated(protocol) {
  const peer = 'a'.repeat(64);
  await protocol.receive({ type: 'challenge', nonce: peer });
  await protocol.receive({ type: 'proof', proof: await proof(KEY, 'server', protocol.own, peer) });
}
test('page source requires authenticated server, explicit declaration and fixed site; Cookie reader is unused', async () => {
  const b = browser(), sent = [];
  const protocol = new Protocol({ pairingKey: KEY, domains: ['instagram.com'], yuanbaoAccount: true }, () => { throw new Error('Cookie route forbidden'); }, m => sent.push(m), '1.0.0', deadlineMs => readExistingAccount(b.api, deadlineMs));
  const request = { type: 'yuanbao_account', request_id: ID, site: 'wechat_channels', deadline: futureDeadline() };
  await assert.rejects(protocol.receive(request), /unauthenticated/);
  await protocol.receive({ type: 'challenge', nonce: 'a'.repeat(64) });
  await assert.rejects(protocol.receive({ type: 'proof', proof: '0'.repeat(64) }), /authentication_failed/);
  assert.deepEqual(b.calls, []);
  // A new Protocol models a separate successful authenticated connection.
  const valid = new Protocol(protocol.config, protocol.getAll, protocol.send, protocol.version, protocol.readAccount);
  await authenticated(valid);
  valid.readAccount = deadlineMs => {
    assert.equal(deadlineMs, Date.parse(request.deadline));
    return readExistingAccount(b.api, deadlineMs);
  };
  await valid.receive(request);
  assert.deepEqual(sent.at(-1), { type: 'yuanbao_account', request_id: ID, ...ACCOUNT });
});
test('page requests reject other sites, undeclared source, arbitrary code/URL and parallel reads before touching Chrome', async () => {
  const b = browser(), sent = [];
  const p = new Protocol({ pairingKey: KEY, domains: [], yuanbaoAccount: true }, async () => [], m => sent.push(m), '1.0.0', deadlineMs => readExistingAccount(b.api, deadlineMs));
  await authenticated(p);
  const request = { type: 'yuanbao_account', request_id: ID, site: 'wechat_channels', deadline: futureDeadline() };
  for (const message of [{ ...request, site: 'instagram' }, { ...request, origin: ORIGIN }, { ...request, code: 'arbitrary' }, { ...request, request_id: 'bad' }]) await assert.rejects(p.receive(message));
  for (const deadline of [undefined, null, 42, 'not-a-date', '2026-99-99T12:00:00Z', '2027-01-01T12:00:00+08:00']) await assert.rejects(p.receive({ ...request, deadline }), /invalid_deadline/);
  await p.receive({ ...request, deadline: new Date(Date.now() - 1000).toISOString() });
  assert.deepEqual(sent.at(-1), { type: 'yuanbao_account', request_id: ID, cause: 'extension_timeout' });
  assert.deepEqual(b.calls, []);
  p.config.yuanbaoAccount = false;
  await assert.rejects(p.receive(request), /undeclared/);
  p.config.yuanbaoAccount = true; p.busy = true;
  await assert.rejects(p.receive(request), /invalid_request/);
  assert.deepEqual(b.calls, []);
  p.busy = false;
  p.readAccount = async () => ({ cause: 'credential_missing' });
  await p.receive(request);
  assert.deepEqual(sent.at(-1), { type: 'yuanbao_account', request_id: ID, cause: 'credential_missing' });
  assert.equal(p.busy, false);
});
test('earlier operation deadline and five-second boundary stop after every Chrome await', async () => {
  for (const limit of [500, 5000]) {
  for (let expireAt = 1; expireAt <= 5; expireAt++) {
    let now = 0, calls = 0;
    const step = value => { if (++calls === expireAt) now = limit; return value; };
    const context = vm.createContext({ URL, TextEncoder, Date: { now: () => now }, setTimeout: () => 0, clearTimeout: () => {} });
    vm.runInContext(fs.readFileSync(__dirname + '/yuanbao-account.js', 'utf8'), context);
    const tab = { id: 9, url: ORIGIN + '/chat', incognito: false };
    const api = {
      tabs: { query: async () => step([tab]), get: async () => step(tab) },
      scripting: { executeScript: async () => step([{ frameId: 0, documentId: 'document-one', result: ACCOUNT }]) },
    };
    const result = await context.FrameFetchYuanbaoAccount.readExistingAccount(api, limit === 500 ? 500 : 60000);
    assert.equal(result.cause, 'extension_timeout');
    assert.equal('auth_token' in result, false);
    assert.equal(calls, expireAt);
  }
  }
});
test('a stalled Chrome API finishes at the shared deadline and late results cannot continue reading', async () => {
  for (const limit of [10, 5000]) {
  for (let blockAt = 1; blockAt <= 5; blockAt++) {
    const clock = timedReader();
    let calls = 0, release;
    const pending = new Promise(resolve => { release = resolve; });
    const tab = { id: 9, url: ORIGIN + '/chat', incognito: false };
    const step = value => ++calls === blockAt ? pending : Promise.resolve(value);
    const api = {
      tabs: { query: () => step([tab]), get: () => step(tab) },
      scripting: { executeScript: () => step([{ frameId: 0, documentId: 'document-one', result: ACCOUNT }]) },
    };
    let result;
    const read = clock.read(api, limit === 5000 ? 60000 : limit).then(value => { result = value; });
    await flush();
    assert.equal(calls, blockAt);
    clock.advance(limit);
    await flush();
    try {
      assert.ok(result, 'Chrome read must finish without releasing the stalled API');
      assert.deepEqual(JSON.parse(JSON.stringify(result)), { cause: 'extension_timeout' });
      assert.equal(clock.timers.size, 0);
    } finally {
      release(blockAt === 1 ? [tab] : blockAt === 3 || blockAt === 5 ? tab : [{ frameId: 0, documentId: 'document-one', result: ACCOUNT }]);
      await read;
    }
    await flush();
    assert.equal(calls, blockAt);
  }
  }
});
test('Chrome failures and successful reads clear their deadline timers', async () => {
  for (const broken of [false, true]) {
    const clock = timedReader();
    const b = browser();
    b.api.scripting.executeScript = async () => [{ frameId: 0, documentId: 'document-one', result: ACCOUNT }];
    if (broken) b.api.tabs.query = () => Promise.reject(new Error('synthetic-private-error'));
    const result = await clock.read(b.api, 100);
    assert.deepEqual(JSON.parse(JSON.stringify(result)), broken ? { cause: 'identity_page_unavailable' } : ACCOUNT);
    assert.equal(clock.timers.size, 0);
    clock.advance(100);
    await flush();
  }
});
test('an earlier Chrome call does not restart the operation timeout', async () => {
  const clock = timedReader();
  const tab = { id: 9, url: ORIGIN + '/chat', incognito: false };
  let result;
  const read = clock.read({
    tabs: { query: async () => { clock.advance(6); return [tab]; } },
    scripting: { executeScript: () => new Promise(() => {}) },
  }, 10).then(value => { result = value; });
  await flush();
  clock.advance(3);
  await flush();
  assert.equal(result, undefined);
  clock.advance(1);
  await read;
  assert.deepEqual(JSON.parse(JSON.stringify(result)), { cause: 'extension_timeout' });
  assert.equal(clock.timers.size, 0);
});
test('expiry before the scheduled Chrome call prevents all browser access', async () => {
  const clock = timedReader();
  let calls = 0;
  const read = clock.read({ tabs: { query: async () => { calls++; return []; } } }, 10);
  clock.advance(10);
  const result = await read;
  assert.deepEqual(JSON.parse(JSON.stringify(result)), { cause: 'extension_timeout' });
  assert.equal(calls, 0);
  assert.equal(clock.timers.size, 0);
});
test('real timer releases protocol busy and late script rejection sends no material', { timeout: 1000 }, async () => {
  const b = browser(), sent = [];
  let reject;
  const stalled = new Promise((_, fail) => { reject = fail; });
  b.api.scripting.executeScript = () => stalled;
  const p = new Protocol({ pairingKey: KEY, domains: ['instagram.com'], yuanbaoAccount: true }, async () => [], m => sent.push(m), '1.0.0', deadline => readExistingAccount(b.api, deadline));
  await authenticated(p);
  const request = p.receive({ type: 'yuanbao_account', request_id: ID, site: 'wechat_channels', deadline: new Date(Date.now() + 20).toISOString() });
  await flush();
  assert.equal(p.busy, true);
  await request;
  assert.equal(p.busy, false);
  assert.deepEqual(sent.at(-1), { type: 'yuanbao_account', request_id: ID, cause: 'extension_timeout' });
  await p.receive({ type: 'cookies', request_id: 'e'.repeat(32), domains: ['instagram.com'], deadline: futureDeadline() });
  assert.deepEqual(sent.at(-1), { type: 'cookies', request_id: 'e'.repeat(32), cookies: [] });
  const count = sent.length;
  reject(new Error('synthetic-private-error'));
  await flush();
  assert.equal(sent.length, count);
});
