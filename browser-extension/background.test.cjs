const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function fixture({allowed=true, cookies=[]} = {}) {
  const reads=[], replies=[], tabs=[];
  let receive, disconnect, message;
  const context = {
    chrome: {
      runtime: {
        id: 'extension', lastError: undefined,
        getURL: p => `chrome-extension://extension/${p}`,
        connectNative: name => {
          assert.equal(name, 'com.framefetch.chrome_source');
          return {onMessage: {addListener: f => receive=f}, onDisconnect: {addListener: f => disconnect=f}, postMessage: value => replies.push(value)};
        },
        onStartup: {addListener() {}}, onInstalled: {addListener() {}},
        onMessage: {addListener: f => message=f},
      },
      permissions: {contains: async () => allowed},
      cookies: {getAll: async value => {reads.push(value.domain); return cookies;}},
      tabs: {create: async value => tabs.push(value), query: async () => []},
    }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'background.js'),'utf8'), context);
  return {receive: r=>receive(r), disconnect: ()=>disconnect(), message: (...args)=>message(...args), reads, replies, tabs};
}
const request = {command: 'read', request_id: 'task', domains: ['youtube.com'], login_url: 'https://www.youtube.com/feed/you'};
test('reads only requested domain; preserves HttpOnly; skips partitioned cookies', async () => {
  const value={name:'SID', value:'synthetic', domain:'.youtube.com', path:'/', storeId:'0', httpOnly:true};
  const f=fixture({cookies: [value, value, {...value, name:'partitioned', partitionKey:{topLevelSite:'https://other.example'}}]});
  await f.receive(request);
  assert.deepEqual(f.reads,['youtube.com']);
  assert.equal(f.replies[0].cookies.length,1);
  assert.equal(f.replies[0].cookies[0].httpOnly,true);
});
test('missing permission never reads cookies', async () => {
  const f=fixture({allowed:false}); await f.receive(request);
  assert.equal(f.reads.length,0); assert.equal(f.replies[0].error,'provider_session_not_ready');
});
test('login action opens fixed request URL and never reads cookies', async () => {
  const f=fixture(); await f.receive({...request, command:'login'});
  assert.equal(f.tabs[0].url,request.login_url); assert.equal(f.reads.length,0);
});
test('unopened Yuanbao page returns a clear error and no partial cookie material', async () => {
  const f=fixture({cookies:[{name:'hy_token',value:'synthetic'}]});
  await f.receive({...request,header_plugin:'yuanbao'});
  assert.equal(f.replies[0].error,'credential_required'); assert.equal(f.replies[0].cookies.length,0);
});
test('ordinary webpages cannot request reconnection or get status', () => {
  const f=fixture(); let called=false;
  f.message({command:'connect'}, {id:'extension',url:'https://evil.example/'}, ()=>called=true);
  assert.equal(called,false);
});
