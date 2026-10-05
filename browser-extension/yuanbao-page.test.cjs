const { test } = require('node:test');
const assert = require('node:assert/strict');
const { prepare, open, status } = require('./yuanbao-page.js');
const ORIGIN = 'https://yuanbao.tencent.com';
const tab = (extra = {}) => ({ id: 9, url: ORIGIN + '/chat', incognito: false, status: 'complete', ...extra });
const deadline = () => Date.now() + 2000;

test('missing page is created at the exact official origin in the background and awaited before use', async () => {
  const calls = [];
  let current = null;
  const api = { tabs: {
    query: async options => { assert.deepEqual(options, { url: ORIGIN + '/*' }); return current ? [current] : []; },
    create: async options => {
      calls.push(options);
      current = tab({ status: 'loading', url: ORIGIN + '/', pendingUrl: ORIGIN + '/chat' });
      return current;
    },
    get: async () => { current = tab(); return current; },
    update: () => assert.fail('automatic preparation must not activate or navigate tabs'),
  } };
  assert.deepEqual(await prepare(api, deadline()), tab());
  assert.deepEqual(calls, [{ url: ORIGIN + '/', active: false }]);
});

test('popup and task share one page creation while loading, even before a URL becomes queryable', async () => {
  let release, creates = 0, current = null;
  const pending = new Promise(resolve => { release = resolve; });
  const activated = [];
  const api = { tabs: {
    query: async () => current ? [current] : [],
    create: async options => { creates++; assert.deepEqual(options, { url: ORIGIN + '/', active: false }); return pending; },
    update: async (id, options) => { activated.push([id, options]); },
  } };
  const task = prepare(api, deadline());
  const popup = open(api, deadline(), true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(creates, 1);
  current = tab(); release(current);
  assert.deepEqual(await task, current);
  assert.deepEqual(await popup, current);
  assert.deepEqual(activated, [[9, { active: true }]]);
});

test('existing pages are reused; multiple pages remain an explicit conflict without side effects', async () => {
  const api = { tabs: { query: async () => [tab()],
    create: () => assert.fail('must reuse existing page'), update: () => assert.fail('must not change user page') } };
  assert.deepEqual(await prepare(api, deadline()), tab());
  api.tabs.query = async () => [tab(), tab({ id: 10 })];
  await assert.rejects(prepare(api, deadline()), /identity_tab_ambiguous/);
});

test('load timeout and a cross-origin redirect cannot supply a native execution target', async () => {
  let reads = 0;
  const api = { tabs: { query: async () => [],
    create: async () => tab({ status: 'loading' }),
    get: async () => { reads++; return tab({ url: 'https://evil.test/', status: 'complete' }); } } };
  await assert.rejects(prepare(api, Date.now() + 20), /extension_timeout/);
  assert.equal(reads, 0);
  await assert.rejects(prepare(api, deadline()), /identity_origin_invalid/);
  assert.equal(reads, 1);
});

test('incognito creation is rejected; unloaded user pages are never silently navigated', async () => {
  const api = { tabs: { query: async () => [], create: async () => tab({ incognito: true }) } };
  await assert.rejects(prepare(api, deadline()), /identity_page_unavailable/);
  api.tabs.query = async () => [tab({ discarded: true })];
  await assert.rejects(prepare(api, deadline()), /identity_page_unavailable/);
});

test('diagnostics do not read account material, create pages or execute native requests', async () => {
  let tabs = [];
  const api = { tabs: { query: async () => tabs,
    create: () => assert.fail('status cannot open a page') },
    scripting: { executeScript: () => assert.fail('status cannot read credentials') } };
  for (const [value, expected] of [
    [[], 'missing'], [[tab()], 'available'], [[tab({ status: 'loading' })], 'loading'],
    [[tab(), tab({ id: 10 })], 'ambiguous'], [[tab({ frozen: true })], 'inactive'],
    [[tab({ incognito: true })], 'missing'],
  ]) { tabs = value; assert.equal(await status(api), expected); }
});

test('expired creation results cannot continue loading or supply a native execution target', async () => {
  let release, reads = 0;
  const pending = new Promise(resolve => { release = resolve; });
  const api = { tabs: { query: async () => [], create: () => pending,
    get: () => { reads++; assert.fail('late creation must not continue loading'); } } };
  await assert.rejects(prepare(api, Date.now() + 20), /extension_timeout/);
  release(tab({ status: 'loading' }));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(reads, 0);
});
