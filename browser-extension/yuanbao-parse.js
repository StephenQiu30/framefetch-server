/* Fixed native request after the declared Yuanbao page is ready. No credential export. */
(() => {
  const page = typeof module !== 'undefined' ? require('./yuanbao-page.js') : globalThis.FrameFetchYuanbaoPage;
  const MAX_CAPTURE_BYTES = 4 * 1024 * 1024;
  const CAUSES = new Set([
    'credential_missing', 'identity_material_invalid', 'identity_origin_invalid',
    'identity_navigation_changed', 'identity_account_conflict', 'identity_tab_ambiguous',
    'identity_page_unavailable', 'native_api_unavailable', 'parse_response_invalid',
    'parse_request_failed', 'extension_timeout',
  ]);

  // Chrome serializes this fixed function. It accepts no scripts, headers or API URL.
  async function nativeParse(canonicalUrl, deadlineMs, probeOnly) {
    const origin = 'https://yuanbao.tencent.com';
    const parseUrl = origin + '/api/weixin/get_parse_result';
    const encoder = new TextEncoder();
    const fail = cause => ({ cause });
    let timer, controller, oversized = false;
    const known = new Set([
      'credential_missing', 'identity_material_invalid', 'identity_origin_invalid',
      'identity_navigation_changed', 'identity_account_conflict', 'native_api_unavailable',
      'parse_response_invalid', 'parse_request_failed', 'extension_timeout',
    ]);
    const inScope = () => top === self && location.origin === origin;
    const checkDeadline = () => {
      if (!Number.isFinite(deadlineMs) || Date.now() >= deadlineMs) throw new Error('extension_timeout');
    };
    const validAccount = value => typeof value === 'string' && value.length > 0 &&
      value === value.trim() && !/[\x00-\x1f\x7f\ud800-\udfff]/u.test(value) &&
      encoder.encode(value).length <= 1024;
    try {
      checkDeadline();
      if (!inScope()) return fail('identity_origin_invalid');
      if (typeof canonicalUrl !== 'string' || !/^https:\/\/weixin\.qq\.com\/sph\/[A-Za-z0-9_-]{4,256}$/.test(canonicalUrl) ||
          typeof probeOnly !== 'boolean') return fail('identity_material_invalid');
      const pageUrl = location.href;
      const chunks = self.webpackChunk_N_E;
      if (!Array.isArray(chunks)) return fail('native_api_unavailable');
      let require;
      chunks.push([[`framefetch-native-${crypto.randomUUID()}`], {}, r => { require = r; }]);
      if (!require || !require.m || Object.keys(require.m).length > 20000) return fail('native_api_unavailable');
      const isNativeFactory = source => {
        // Match the factory's own export declaration, before its implementation.
        // A third-party factory may contain embedded bundles with the same
        // words, so searching its entire source cannot identify this client.
        const declaration = /^\s*(?:function(?:\s+[A-Za-z_$][\w$]*)?\s*)?\(\s*([A-Za-z_$][\w$]*)\s*,\s*([A-Za-z_$][\w$]*)\s*,\s*([A-Za-z_$][\w$]*)\s*\)\s*(?:=>\s*)?\{\s*(?:(?:"use strict"|'use strict')\s*;\s*)?\3\.r\(\s*\2\s*\)\s*,\s*\3\.d\(\s*\2\s*,\s*\{([^{}]*)\}\s*\)\s*;/.exec(source);
        if (!declaration) return false;
        const exports = declaration[4].split(',').map(entry =>
          /^\s*([A-Za-z_$][\w$]*)\s*:\s*\(\s*\)\s*=>\s*[A-Za-z_$][\w$]*\s*$/.exec(entry)?.[1]);
        return exports.length === 4 && exports.every(Boolean) &&
          exports.sort().join(',') === 'JPRXAxios,getNetworkErrorMsg,instance,request';
      };
      const candidates = [];
      for (const [id, factory] of Object.entries(require.m)) {
        checkDeadline();
        if (typeof factory !== 'function') continue;
        const source = Function.prototype.toString.call(factory);
        if (!isNativeFactory(source)) continue;
        candidates.push(id);
      }
      // Establish uniqueness before requiring a factory. A scan must not
      // initialize several possible modules and their unrelated side effects.
      if (candidates.length !== 1) return fail('native_api_unavailable');
      let native;
      try { native = require(candidates[0]); } catch { return fail('native_api_unavailable'); }
      if (!native || typeof native.request !== 'function' ||
          typeof native.instance?.request !== 'function' ||
          !native.instance?.interceptors?.request || !native.instance?.interceptors?.response) return fail('native_api_unavailable');
      const readAccountHeader = values => {
        if (!values) return undefined;
        if (typeof values.get === 'function') return values.get('X-ID');
        const names = Object.keys(values).filter(name => name.toLowerCase() === 'x-id');
        const value = names.length ? values[names[0]] : undefined;
        if (names.some(name => values[name] !== value)) throw new Error('identity_account_conflict');
        return value;
      };
      const account = () => {
        const headers = native.instance.defaults?.headers;
        const value = readAccountHeader(headers) ?? readAccountHeader(headers?.post) ?? readAccountHeader(headers?.common);
        if (value === undefined || value === null || value === '') throw new Error('credential_missing');
        if (!validAccount(value)) throw new Error('identity_material_invalid');
        return value;
      };
      const before = account();
      checkDeadline();
      if (!inScope() || location.href !== pageUrl) return fail('identity_navigation_changed');
      if (probeOnly) return { account_id: before };
      controller = new AbortController();
      const remaining = Math.min(30000, deadlineMs - Date.now());
      checkDeadline();
      let response;
      try {
        response = await Promise.race([
          native.instance.request({
            url: parseUrl, method: 'post',
            data: { type: 'video_channel_url', url: canonicalUrl, scene: 1 },
            returnResponse: true, hideTip: true, timeout: remaining, signal: controller.signal,
            onDownloadProgress: event => {
              if (event.loaded > 4 * 1024 * 1024 || event.total > 4 * 1024 * 1024) {
                oversized = true;
                controller.abort();
              }
            },
          }),
          new Promise((_, reject) => {
            timer = setTimeout(() => { controller.abort(); reject(new Error('extension_timeout')); }, remaining);
          }),
        ]);
      } catch (error) {
        checkDeadline();
        if (oversized) throw new Error('parse_response_invalid');
        if (controller.signal.aborted) throw new Error('extension_timeout');
        // An HTTP error may preserve an actual Axios response. Never export the error.
        response = error?.response;
        if (!response) throw new Error('parse_request_failed');
      }
      checkDeadline();
      if (oversized) throw new Error('parse_response_invalid');
      if (!inScope() || location.href !== pageUrl) return fail('identity_navigation_changed');
      if (account() !== before) return fail('identity_account_conflict');
      const config = response?.config;
      const xhr = response?.request;
      if (!config || typeof config.method !== 'string' || config.method.toUpperCase() !== 'POST' ||
          typeof config.url !== 'string' || typeof xhr?.responseURL !== 'string' ||
          !Number.isInteger(response.status) || response.status < 200 || response.status > 599 ||
          xhr.status !== response.status) return fail('parse_response_invalid');
      const checkRequestAccount = () => {
        // Interceptors may replace defaults. Bind the digest to the account
        // observed on this exact Axios request without exporting its headers.
        const observed = readAccountHeader(config.headers);
        if (!validAccount(observed)) throw new Error('identity_material_invalid');
        if (observed !== before) throw new Error('identity_account_conflict');
      };
      checkRequestAccount();
      let requestUrl, body;
      try {
        requestUrl = new URL(config.url, config.baseURL || origin).href;
        body = typeof config.data === 'string' ? JSON.parse(config.data) : config.data;
      } catch { return fail('parse_response_invalid'); }
      if (requestUrl !== parseUrl || xhr.responseURL !== parseUrl ||
          !body || typeof body !== 'object' || Array.isArray(body) ||
          Object.keys(body).sort().join(',') !== 'scene,type,url' ||
          body.type !== 'video_channel_url' || body.url !== canonicalUrl || body.scene !== 1 ||
          !response.data || typeof response.data !== 'object' || Array.isArray(response.data)) return fail('parse_response_invalid');
      const captured = {
        request_method: config.method.toUpperCase(), request_url: requestUrl,
        response_url: xhr.responseURL, http_status: xhr.status,
        request_body: body, payload: response.data,
      };
      // Axios has already read the response. This bounds returned JSON, not network streaming.
      const serialized = JSON.stringify(captured);
      if (encoder.encode(serialized).length > 4 * 1024 * 1024) return fail('parse_response_invalid');
      checkDeadline();
      if (!inScope() || location.href !== pageUrl) return fail('identity_navigation_changed');
      if (account() !== before) return fail('identity_account_conflict');
      checkRequestAccount();
      return { account_id: before, captured: JSON.parse(serialized) };
    } catch (error) {
      return fail(known.has(error?.message) ? error.message : 'parse_request_failed');
    } finally { clearTimeout(timer); }
  }

  function checkedResult(results, documentId, probeOnly) {
    if (!Array.isArray(results) || results.length !== 1 || results[0].frameId !== 0 ||
        typeof results[0].documentId !== 'string' || !results[0].documentId ||
        (documentId && results[0].documentId !== documentId)) throw new Error('identity_navigation_changed');
    const result = results[0].result;
    if (result && Object.keys(result).length === 1 && CAUSES.has(result.cause)) throw new Error(result.cause);
    const keys = probeOnly ? 'account_id' : 'account_id,captured';
    if (!result || Object.keys(result).sort().join(',') !== keys ||
        typeof result.account_id !== 'string' || !result.account_id ||
        result.account_id !== result.account_id.trim() || /[\x00-\x1f\x7f\ud800-\udfff]/u.test(result.account_id) ||
        new TextEncoder().encode(result.account_id).length > 1024 ||
        (!probeOnly && (!result.captured || new TextEncoder().encode(JSON.stringify(result.captured)).length > MAX_CAPTURE_BYTES))) {
      throw new Error('parse_response_invalid');
    }
    return result;
  }
  async function readShareParse(api, canonicalUrl, operationDeadlineMs) {
    const deadline = Number.isFinite(operationDeadlineMs) ? Math.min(Date.now() + 30000, operationDeadlineMs) : NaN;
    const checkDeadline = () => { if (!Number.isFinite(deadline) || Date.now() >= deadline) throw new Error('extension_timeout'); };
    const awaitChrome = action => page.beforeDeadline(deadline, action);
    try {
      if (typeof canonicalUrl !== 'string' || !/^https:\/\/weixin\.qq\.com\/sph\/[A-Za-z0-9_-]{4,256}$/.test(canonicalUrl)) throw new Error('identity_material_invalid');
      const tab = await page.prepare(api, deadline);
      const first = await awaitChrome(() => api.scripting.executeScript({
        target: { tabId: tab.id, frameIds: [0] }, world: 'MAIN', func: nativeParse,
        args: [canonicalUrl, deadline, true],
      }));
      checkDeadline();
      const initial = checkedResult(first, null, true);
      const current = await awaitChrome(() => api.tabs.get(tab.id));
      checkDeadline();
      if (!page.scopedTab(current) || current.pendingUrl || current.url !== tab.url) throw new Error('identity_navigation_changed');
      const parsed = await awaitChrome(() => api.scripting.executeScript({
        target: { tabId: tab.id, documentIds: [first[0].documentId] }, world: 'MAIN', func: nativeParse,
        args: [canonicalUrl, deadline, false],
      }));
      checkDeadline();
      const result = checkedResult(parsed, first[0].documentId, false);
      if (result.account_id !== initial.account_id) throw new Error('identity_account_conflict');
      const confirmed = await awaitChrome(() => api.scripting.executeScript({
        target: { tabId: tab.id, documentIds: [first[0].documentId] }, world: 'MAIN', func: nativeParse,
        args: [canonicalUrl, deadline, true],
      }));
      checkDeadline();
      if (checkedResult(confirmed, first[0].documentId, true).account_id !== initial.account_id) throw new Error('identity_account_conflict');
      const finalTab = await awaitChrome(() => api.tabs.get(tab.id));
      checkDeadline();
      if (!page.scopedTab(finalTab) || finalTab.pendingUrl || finalTab.url !== tab.url) throw new Error('identity_navigation_changed');
      return result;
    } catch (error) {
      return { cause: CAUSES.has(error?.message) ? error.message : 'identity_page_unavailable' };
    }
  }
  const api = { nativeParse, readShareParse, CAUSES, MAX_CAPTURE_BYTES };
  globalThis.FrameFetchYuanbaoParse = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
