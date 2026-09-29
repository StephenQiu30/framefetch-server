// Task requests arrive only from the registered native host. Web pages cannot
// call this extension: no content scripts or externally_connectable surface.
let port;
let connectionState = '未连接本机服务';
function connect() {
  if (port) return;
  port = chrome.runtime.connectNative('com.framefetch.chrome_source');
  port.onMessage.addListener(async (request) => {
    if (request.command === 'disconnected') {
      connectionState = '本机服务重连中';
      return;
    }
    if (request.command === 'connected') {
      connectionState = '已连接，按解析任务读取平台会话';
      return;
    }
    const response = {request_id: request.request_id, cookies: []};
    try {
      const origins = request.domains.map(domain => `https://*.${domain.replace(/^\./, '')}/*`);
      if (!await chrome.permissions.contains({origins})) throw new Error('permission');
      if (request.command === 'login') {
        await chrome.tabs.create({url: request.login_url});
      } else if (request.command === 'read') {
        const seen = new Set();
        for (const domain of request.domains) {
          const values = await chrome.cookies.getAll({domain: domain.replace(/^\./, '')});
          for (const value of values) {
            // Partitioned sessions cannot be transplanted into a regular jar.
            if (value.partitionKey) continue;
            const key = `${value.storeId}:${value.domain}:${value.path}:${value.name}`;
            if (!seen.has(key)) {seen.add(key); response.cookies.push(value);}
          }
        }
        if (response.cookies.length > 500) throw new Error('too_large');
        if (request.header_plugin === 'yuanbao') {
          const tabs = await chrome.tabs.query({url: 'https://yuanbao.tencent.com/*'});
          if (!tabs.length) throw new Error('credential_required');
          const results = await chrome.scripting.executeScript({
            target: {tabId: tabs[0].id}, world: 'MAIN',
            func: async () => {
              if (location.origin !== 'https://yuanbao.tencent.com') return {};
              let headers = await window.$webApi?.getYbCommonHeaders?.() || {};
              if (window.$webApi?.setContextualRequestHeaders) {
                const request = {url: '/api/weixin/get_parse_result', headers};
                await window.$webApi.setContextualRequestHeaders(request);
                headers = request.headers;
              }
              headers['User-Agent'] = navigator.userAgent;
              return {userId: localStorage.getItem('yb_user_id') || '', token: localStorage.getItem('yb_token') || '', headers};
            }
          });
          response.auth = results[0]?.result;
        }
      } else throw new Error('unsupported');
    } catch (error) {
      response.cookies = [];
      delete response.auth;
      response.error = error.message === 'credential_required' ? 'credential_required' : 'provider_session_not_ready';
    }
    try { port?.postMessage(response); } catch { /* Native host disconnected. */ }
  });
  port.onDisconnect.addListener(() => {
    void chrome.runtime.lastError; // Never log browser diagnostics or materials.
    port = undefined;
    connectionState = '未连接本机服务，请检查安装后点击重新连接';
  });
}
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL('popup.html')) return;
  if (message.command === 'connect') connect();
  reply({state: connectionState});
});
connect();
