/* Fixed first-party HTTP client. Credentials never leave this Chrome worker. */
(() => {
  const ORIGIN = 'https://yuanbao.tencent.com';
  const PARSE_URL = ORIGIN + '/api/weixin/get_parse_result';
  const MAX_CAPTURE_BYTES = 4 * 1024 * 1024;
  const CAUSES = new Set(['credential_missing', 'identity_material_invalid',
    'identity_account_conflict', 'parse_response_invalid', 'parse_request_failed', 'extension_timeout',
    'yuanbao_response_source_invalid', 'yuanbao_response_size_invalid', 'yuanbao_response_utf8_invalid',
    'yuanbao_response_json_invalid', 'yuanbao_response_credential_echo', 'yuanbao_request_rule_unavailable']);
  const validHeader = (value, limit) => typeof value === 'string' && value.length > 0 &&
    value === value.trim() && !/[^\x21-\x7e]/u.test(value) && value.length <= limit;

  async function beforeDeadline(deadline, action) {
    const check = () => { if (!Number.isFinite(deadline) || Date.now() >= deadline) throw new Error('extension_timeout'); };
    check();
    let timer;
    try {
      const result = await Promise.race([
        Promise.resolve().then(() => { check(); return action(); }),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('extension_timeout')), deadline - Date.now()); }),
      ]);
      check();
      return result;
    } finally { clearTimeout(timer); }
  }
  function checkedCookie(c, name) {
    if (!c) throw new Error('credential_missing');
    if (typeof c !== 'object' || c.partitionKey || c.name !== name ||
        !['.tencent.com', 'tencent.com', '.yuanbao.tencent.com', 'yuanbao.tencent.com'].includes(c.domain) ||
        typeof c.path !== 'string' || !(new URL(PARSE_URL).pathname === c.path ||
          new URL(PARSE_URL).pathname.startsWith(c.path.endsWith('/') ? c.path : c.path + '/')) ||
        typeof c.session !== 'boolean' || (!c.session && (!Number.isFinite(c.expirationDate) || c.expirationDate * 1000 <= Date.now())) ||
        !validHeader(c.value, name === 'hy_user' ? 1024 : 65536)) throw new Error('identity_material_invalid');
    return c.value;
  }
  async function auth(api, deadline) {
    const end = Math.min(deadline, Date.now() + 5000);
    // get() checks the authorized request URL and follows Chrome's Cookie
    // precedence. getAll() instead filters by each Cookie's owning domain,
    // hiding Yuanbao's parent-domain authentication Cookies.
    const read = name => beforeDeadline(end, async () => {
      let cookie;
      try { cookie = await api.cookies.get({ url: PARSE_URL, name }); }
      catch { throw new Error('identity_material_invalid'); }
      return checkedCookie(cookie, name);
    });
    const account = await read('hy_user');
    const token = await read('hy_token');
    if (await read('hy_user') !== account) throw new Error('identity_account_conflict');
    return { account, token };
  }
  async function status(api) {
    try { await auth(api, Date.now() + 2000); return 'available'; }
    catch (error) { return error.message === 'credential_missing' ? 'missing' : 'unavailable'; }
  }
  async function responsePayload(response, deadline) {
    const length = response.headers.get('content-length');
    if (length !== null && (!/^\d+$/.test(length) || Number(length) > MAX_CAPTURE_BYTES)) throw new Error('yuanbao_response_size_invalid');
    if (!response.body) throw new Error('yuanbao_response_json_invalid');
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8', { fatal: true });
    let size = 0, text = '', complete = false;
    try {
      while (true) {
        const chunk = await beforeDeadline(deadline, () => reader.read());
        if (chunk.done) break;
        size += chunk.value.byteLength;
        if (size > MAX_CAPTURE_BYTES) throw new Error('yuanbao_response_size_invalid');
        try { text += decoder.decode(chunk.value, { stream: true }); }
        catch { throw new Error('yuanbao_response_utf8_invalid'); }
      }
      try { text += decoder.decode(); }
      catch { throw new Error('yuanbao_response_utf8_invalid'); }
      let payload;
      try { payload = JSON.parse(text); } catch { throw new Error('yuanbao_response_json_invalid'); }
      if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('yuanbao_response_json_invalid');
      complete = true;
      return payload;
    } finally {
      if (!complete) void reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }
  async function parseShare(api, canonicalUrl, operationDeadlineMs, transport = globalThis.fetch) {
    const deadline = Number.isFinite(operationDeadlineMs) ? Math.min(Date.now() + 30000, operationDeadlineMs) : NaN;
    let timer, controller, accountChanged = false;
    const changed = details => {
      const c = details.cookie;
      if (c?.name === 'hy_user' && !c.partitionKey &&
          ['.tencent.com', 'tencent.com', '.yuanbao.tencent.com', 'yuanbao.tencent.com'].includes(c.domain)) {
        accountChanged = true;
        controller?.abort();
      }
    };
    api.cookies.onChanged.addListener(changed);
    try {
      if (!Number.isFinite(deadline) || Date.now() >= deadline) throw new Error('extension_timeout');
      if (typeof canonicalUrl !== 'string' || !/^https:\/\/weixin\.qq\.com\/sph\/[A-Za-z0-9_-]{4,256}$/.test(canonicalUrl)) throw new Error('identity_material_invalid');
      let rulesets;
      try { rulesets = await beforeDeadline(deadline, () => api.declarativeNetRequest.getEnabledRulesets()); }
      catch (error) { throw new Error(error?.message === 'extension_timeout' ? 'extension_timeout' : 'yuanbao_request_rule_unavailable'); }
      if (!Array.isArray(rulesets) || !rulesets.includes('yuanbao-http')) throw new Error('yuanbao_request_rule_unavailable');
      const initial = await auth(api, deadline);
      if (accountChanged) throw new Error('identity_account_conflict');
      controller = new AbortController();
      timer = setTimeout(() => controller.abort(), Math.max(0, deadline - Date.now()));
      const request = new Request(PARSE_URL, {
        method: 'POST', credentials: 'include', redirect: 'error', cache: 'no-store', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json, text/plain, */*',
          'X-WebVersion': '2.87.2', 'X-Requested-With': 'XMLHttpRequest',
          'X-ID': initial.account, 'X-Token': initial.token, 'X-Source': 'web', 'X-Instance-ID': '5' },
        body: JSON.stringify({ type: 'video_channel_url', url: canonicalUrl, scene: 1 }),
      });
      const requestBody = JSON.parse(await beforeDeadline(deadline, () => request.clone().text()));
      if (accountChanged) throw new Error('identity_account_conflict');
      const response = await beforeDeadline(deadline, () => transport(request));
      if (response.url !== request.url || response.redirected || !Number.isInteger(response.status) ||
          response.status < 200 || response.status > 599) throw new Error('yuanbao_response_source_invalid');
      const payload = await responsePayload(response, deadline);
      const current = await auth(api, deadline);
      if (accountChanged || current.account !== initial.account) throw new Error('identity_account_conflict');
      const captured = { request_method: request.method, request_url: request.url,
        response_url: response.url, http_status: response.status,
        request_body: requestBody, payload };
      const serialized = JSON.stringify(captured);
      if (new TextEncoder().encode(serialized).length > MAX_CAPTURE_BYTES) throw new Error('yuanbao_response_size_invalid');
      if (serialized.includes(JSON.stringify(initial.token).slice(1, -1))) throw new Error('yuanbao_response_credential_echo');
      return { account_id: initial.account, captured };
    } catch (error) {
      const cause = accountChanged ? 'identity_account_conflict' :
        controller?.signal.aborted || Date.now() >= deadline ? 'extension_timeout' :
        CAUSES.has(error?.message) ? error.message : 'parse_request_failed';
      return { cause };
    } finally { clearTimeout(timer); controller?.abort(); api.cookies.onChanged.removeListener(changed); }
  }
  const api = { parseShare, status, CAUSES, MAX_CAPTURE_BYTES, PARSE_URL };
  globalThis.FrameFetchYuanbaoHTTP = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
