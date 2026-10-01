const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createHmac } = require('node:crypto');
const { Protocol, Backoff, proof, filterCookies } = require('./protocol.js');
const KEY = 'synthetic-test-only-pairing-key-32-bytes';
const PEER = 'b'.repeat(64);
const ID = 'c'.repeat(32);
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
  await assert.rejects(protocol.receive({ type: 'cookies', request_id: ID, domains: ['instagram.com'] }), /unauthenticated/);
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
  await assert.rejects(protocol.receive({ type: 'cookies', request_id: ID, domains: ['instagram.com'] }));
  await assert.rejects(protocol.receive({ type: 'challenge', nonce: 'bad' }));
  assert.deepEqual(calls, []);
});
test('only declared requested domains and subdomains, never partitioned or unrelated cookies', async () => {
  const { protocol, sent, calls } = setup();
  await authenticate(protocol);
  await protocol.receive({ type: 'cookies', request_id: ID, domains: ['instagram.com'] });
  assert.deepEqual(calls, [{ domain: 'instagram.com' }]);
  assert.deepEqual(sent.at(-1).cookies.map(c => c.domain), ['.instagram.com', 'sub.instagram.com']);
  assert.equal(sent.at(-1).request_id, ID);
  await assert.rejects(protocol.receive({ type: 'cookies', request_id: ID, domains: ['evil.test'] }), /undeclared/);
  await assert.rejects(protocol.receive({ type: 'cookies', request_id: ID, domains: ['sub.instagram.com'] }), /undeclared/);
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
  await assert.rejects(protocol.receive({ type: 'cookies', request_id: ID, domains: ['instagram.com'] }));
  assert.deepEqual(calls, []);
  protocol.busy = false;
  protocol.getAll = async () => [cookie('.instagram.com', { value: 'x'.repeat(1024 * 1024) })];
  await assert.rejects(protocol.receive({ type: 'cookies', request_id: ID, domains: ['instagram.com'] }), /message_too_large/);
  assert.equal(protocol.busy, false);
});
test('immediate reconnect, exponential failures capped at 30 seconds, reset after authentication', () => {
  const backoff = new Backoff();
  assert.deepEqual(Array.from({ length: 9 }, () => backoff.next()), [0, 1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000]);
  backoff.reset();
  assert.equal(backoff.next(), 0);
});
