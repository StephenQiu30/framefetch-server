const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createHmac, webcrypto } = require('node:crypto');
const vm = require('node:vm');
const fs = require('node:fs');
const { Protocol, Backoff, proof, filterCookies } = require('./protocol.js');
const KEY = 'synthetic-test-only-pairing-key-32-bytes';
const PEER = 'b'.repeat(64);
const ID = 'c'.repeat(32);
const futureDeadline = () => new Date(Date.now() + 60000).toISOString();
const cookie = (domain, extra = {}) => ({ domain, name: 'sessionid', value: 'synthetic', path: '/', secure: true, httpOnly: true, hostOnly: false, ...extra });
function setup() {
  const sent = [], calls = [];
  const protocol = new Protocol({ pairingKey: KEY, domains: ['instagram.com', 'v.qq.com'] }, async details => {
    calls.push(details);
    return [cookie('.instagram.com'), cookie('sub.instagram.com'), cookie('evilinstagram.com'), cookie('.instagram.com', { partitionKey: { topLevelSite: 'https://evil.test' } })];
  }, message => sent.push(message), '1.0.0');
  return { protocol, sent, calls };
}
async function authenticate(protocol) {
  await protocol.receive({ type: 'challenge', nonce: PEER });
  await protocol.receive({ type: 'proof', proof: await proof(KEY, 'server', protocol.own, PEER) });
}
function timedProtocol(getAll, observeCompletion) {
  let now = 0;
  const timers = new Set(), sent = [];
  class ObservedPromise extends Promise {
    static all(values) {
      const pending = [...values];
      for (const value of pending) Promise.resolve(value).then(observeCompletion, () => {});
      return super.all(pending);
    }
  }
  const context = vm.createContext({
    TextEncoder, crypto: webcrypto, Date: { now: () => now, parse: Date.parse },
    Promise: observeCompletion ? ObservedPromise : Promise,
    setTimeout: (fn, delay) => { const timer = { fn, at: now + delay }; timers.add(timer); return timer; },
    clearTimeout: timer => timers.delete(timer),
  });
  vm.runInContext(fs.readFileSync(__dirname + '/protocol.js', 'utf8'), context);
  const protocol = new context.FrameFetchIdentity.Protocol({ domains: ['instagram.com', 'v.qq.com'] }, getAll,
    message => sent.push(JSON.parse(JSON.stringify(message))), '1.0.0');
  protocol.authenticated = true;
  return { protocol, timers, sent, advance: ms => {
    now += ms;
    for (const timer of [...timers]) if (timer.at <= now) { timers.delete(timer); timer.fn(); }
  } };
}
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); };
test('mutual HMAC succeeds with role-separated independent nonces', async () => {
  const { protocol, sent } = setup();
  await authenticate(protocol);
  assert.equal(protocol.authenticated, true);
  assert.equal(sent[1].proof, await proof(KEY, 'extension', PEER, protocol.own));
  assert.equal(sent[1].version, '1.0.0');
  const expected = createHmac('sha256', KEY).update('server' + protocol.own + PEER).digest('hex');
  assert.equal(expected, await proof(KEY, 'server', protocol.own, PEER));
});
test('fake port owner with invalid server response never reads or returns Cookie', async () => {
  const { protocol, sent, calls } = setup();
  await protocol.receive({ type: 'challenge', nonce: PEER });
  await assert.rejects(protocol.receive({ type: 'proof', proof: '0'.repeat(64) }), /server_authentication_failed/);
  await assert.rejects(protocol.receive({ type: 'cookies', deadline: futureDeadline(), request_id: ID, domains: ['instagram.com'] }), /unauthenticated/);
  assert.deepEqual(calls, []);
  assert.equal(sent.some(m => m.type === 'cookies'), false);
});
test('wrong key, reflection and replay from another connection fail', async () => {
  for (const signature of [await proof(KEY + 'wrong', 'server', 'a'.repeat(64), PEER), await proof(KEY, 'extension', PEER, 'a'.repeat(64)), await proof(KEY, 'server', 'a'.repeat(64), PEER)]) {
    const { protocol, calls } = setup();
    await protocol.receive({ type: 'challenge', nonce: PEER });
    await assert.rejects(protocol.receive({ type: 'proof', proof: signature }));
    assert.deepEqual(calls, []);
  }
});
test('premature request and malformed challenge fail closed', async () => {
  const { protocol, calls } = setup();
  await assert.rejects(protocol.receive({ type: 'cookies', deadline: futureDeadline(), request_id: ID, domains: ['instagram.com'] }));
  await assert.rejects(protocol.receive({ type: 'challenge', nonce: 'bad' }));
  assert.deepEqual(calls, []);
});
test('only declared requested domains and subdomains, never partitioned or unrelated cookies', async () => {
  const { protocol, sent, calls } = setup();
  await authenticate(protocol);
  await protocol.receive({ type: 'cookies', deadline: futureDeadline(), request_id: ID, domains: ['instagram.com'] });
  assert.deepEqual(calls, [{ domain: 'instagram.com' }]);
  assert.deepEqual(sent.at(-1).cookies.map(c => c.domain), ['.instagram.com', 'sub.instagram.com']);
  assert.equal(sent.at(-1).request_id, ID);
  await assert.rejects(protocol.receive({ type: 'cookies', deadline: futureDeadline(), request_id: ID, domains: ['evil.test'] }), /undeclared/);
  await assert.rejects(protocol.receive({ type: 'cookies', deadline: futureDeadline(), request_id: ID, domains: ['sub.instagram.com'] }), /undeclared/);
  assert.equal(calls.length, 1);
});
test('Cookie subdomain matching does not allow suffix lookalikes', () => {
  const selected = filterCookies(['.instagram.com', 'x.instagram.com', 'instagram.com.evil.test', 'evilinstagram.com'].map(d => cookie(d)), ['instagram.com']);
  assert.deepEqual(selected.map(c => c.domain), ['.instagram.com', 'x.instagram.com']);
});
test('Cookie response size and concurrent reads are bounded', async () => {
  const { protocol, calls } = setup();
  await authenticate(protocol);
  protocol.busy = true;
  await assert.rejects(protocol.receive({ type: 'cookies', deadline: futureDeadline(), request_id: ID, domains: ['instagram.com'] }));
  assert.deepEqual(calls, []);
  protocol.busy = false;
  protocol.getAll = async () => [cookie('.instagram.com', { value: 'x'.repeat(1024 * 1024) })];
  await assert.rejects(protocol.receive({ type: 'cookies', deadline: futureDeadline(), request_id: ID, domains: ['instagram.com'] }), /message_too_large/);
  assert.equal(protocol.busy, false);
});
test('immediate reconnect, exponential failures capped at 30 seconds, reset after authentication', () => {
  const backoff = new Backoff();
  assert.deepEqual(Array.from({ length: 9 }, () => backoff.next()), [0, 1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000]);
  backoff.reset();
  assert.equal(backoff.next(), 0);
});
test('prefer platform request cannot return another declared platform identity', async () => {
  const sent = [];
  const protocol = new Protocol({ pairingKey: KEY, domains: ['bilibili.com', 'youtube.com', 'weibo.com'] }, async () => [
    cookie('.bilibili.com', { name: 'SESSDATA' }), cookie('api.bilibili.com', { name: 'SESSDATA' }),
    cookie('.youtube.com', { name: 'SAPISID' }), cookie('evilbilibili.com'),
  ], message => sent.push(message), '1.0.0');
  await authenticate(protocol);
  await protocol.receive({ type: 'cookies', deadline: futureDeadline(), request_id: ID, domains: ['bilibili.com'] });
  assert.deepEqual(sent.at(-1).cookies.map(c => c.domain), ['.bilibili.com', 'api.bilibili.com']);
});
test('stalled Cookie reads share the operation deadline and five-second cap without exporting partial or late material', async () => {
  for (const limit of [10, 5000]) {
    for (const lateFailure of [false, true]) {
      let release, reject;
      const pending = new Promise((done, fail) => { release = done; reject = fail; });
      const clock = timedProtocol(({ domain }) => domain === 'instagram.com' ? pending : [cookie('v.qq.com')]);
      let completed = false;
      const read = clock.protocol.receive({
        type: 'cookies', request_id: ID, domains: ['instagram.com', 'v.qq.com'],
        deadline: new Date(limit === 5000 ? 60000 : limit).toISOString(),
      }).then(() => { completed = true; });
      await flush();
      assert.equal(clock.protocol.busy, true);
      clock.advance(limit); await flush();
      try {
        assert.equal(completed, true, 'read must finish without releasing the stalled API');
        assert.deepEqual(clock.sent, [{ type: 'cookies', request_id: ID, cause: 'extension_timeout' }]);
        assert.equal(clock.protocol.busy, false);
        assert.equal(clock.timers.size, 0);
      } finally {
        if (lateFailure) reject(new Error('synthetic-private-error'));
        else release([cookie('instagram.com')]);
        await read;
      }
      await flush();
      assert.equal(clock.sent.length, 1);
      await clock.protocol.receive({ type: 'ping' });
      assert.deepEqual(clock.sent.at(-1), { type: 'pong' });
      clock.protocol.getAll = () => [];
      await clock.protocol.receive({ type: 'cookies', request_id: ID, domains: ['instagram.com'], deadline: new Date(60000).toISOString() });
      assert.deepEqual(clock.sent.at(-1), { type: 'cookies', request_id: ID, cookies: [] });
      assert.equal(clock.timers.size, 0);
    }
  }
});
test('Cookie deadlines are mandatory and validated before any browser read', async () => {
  let calls = 0;
  const clock = timedProtocol(() => { calls++; return []; });
  const request = { type: 'cookies', request_id: ID, domains: ['instagram.com'] };
  for (const deadline of [undefined, null, 42, 'not-a-date', '2026-99-99T12:00:00Z', '2027-01-01T12:00:00+08:00']) {
    await assert.rejects(clock.protocol.receive({ ...request, deadline }), /invalid_deadline/);
  }
  await clock.protocol.receive({ ...request, deadline: new Date(-1).toISOString() });
  assert.deepEqual(clock.sent, [{ type: 'cookies', request_id: ID, cause: 'extension_timeout' }]);
  assert.equal(calls, 0);
  assert.equal(clock.protocol.busy, false);
  assert.equal(clock.timers.size, 0);
});
test('Cookie aggregation retains only completion markers while a sibling is stalled, including late delivery', async () => {
  let release;
  const pending = new Promise(done => { release = done; });
  const completions = [];
  const clock = timedProtocol(({ domain }) => domain === 'instagram.com' ? [cookie(domain)] : pending,
    value => completions.push(value));
  const read = clock.protocol.receive({
    type: 'cookies', request_id: ID, domains: ['instagram.com', 'v.qq.com'], deadline: new Date(10).toISOString(),
  });
  await flush();
  clock.advance(10);
  await read;
  try {
    assert.equal(completions.length, 1);
    assert.equal(completions[0], undefined, 'a pending aggregate must not retain a completed domain Cookie array');
    assert.deepEqual(clock.sent, [{ type: 'cookies', request_id: ID, cause: 'extension_timeout' }]);
    assert.equal(clock.protocol.busy, false);
  } finally { release([cookie('v.qq.com')]); }
  await flush();
  assert.equal(completions.length, 2);
  assert.ok(completions.every(value => value === undefined), 'late API completion must not retain material in the aggregate');
  assert.equal(clock.sent.length, 1);
  assert.equal(clock.timers.size, 0);
});
test('Cookie expiry before a queued API call or during response filtering never exports material', async () => {
  for (const expireDuringFilter of [false, true]) {
    let calls = 0;
    let clock;
    const material = cookie('instagram.com');
    if (expireDuringFilter) Object.defineProperty(material, 'domain', { get: () => { clock.advance(10); return 'instagram.com'; } });
    clock = timedProtocol(() => { calls++; return [material]; });
    const read = clock.protocol.receive({ type: 'cookies', request_id: ID, domains: ['instagram.com'], deadline: new Date(10).toISOString() });
    if (!expireDuringFilter) clock.advance(10);
    await read;
    assert.deepEqual(clock.sent, [{ type: 'cookies', request_id: ID, cause: 'extension_timeout' }]);
    assert.equal(calls, expireDuringFilter ? 1 : 0);
    assert.equal(clock.protocol.busy, false);
    assert.equal(clock.timers.size, 0);
  }
});
test('successful and failed Cookie APIs release the shared timer and busy state', async () => {
  for (const fails of [false, true]) {
    const clock = timedProtocol(() => { if (fails) throw new Error('synthetic-api-failure'); return []; });
    const read = clock.protocol.receive({ type: 'cookies', request_id: ID, domains: ['instagram.com'], deadline: new Date(60000).toISOString() });
    if (fails) await assert.rejects(read, /synthetic-api-failure/);
    else await read;
    assert.equal(clock.protocol.busy, false);
    assert.equal(clock.timers.size, 0);
  }
});
