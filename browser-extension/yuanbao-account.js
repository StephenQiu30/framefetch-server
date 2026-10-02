/* Fixed ISOLATED top-frame read. No page scripts, signatures, DOM or storage export. */
(() => {
  const ORIGIN = 'https://yuanbao.tencent.com';
  const CAUSES = new Set([
    'credential_missing', 'identity_material_invalid', 'identity_origin_invalid',
    'identity_navigation_changed', 'identity_account_conflict', 'identity_tab_ambiguous',
    'identity_page_unavailable', 'identity_storage_unavailable', 'extension_timeout',
  ]);

  // Chrome serializes this function, so all bounds and checks live in its body.
  function readAccount() {
    const origin = 'https://yuanbao.tencent.com';
    const encoder = new TextEncoder();
    const fail = cause => ({ cause });
    const valid = (value, bound) => typeof value === 'string' && value.length > 0 &&
      value === value.trim() && !/[\x00-\x1f\x7f\ud800-\udfff]/u.test(value) && encoder.encode(value).length <= bound;
    const inScope = () => top === self && location.origin === origin;
    try {
      if (!inScope()) return fail('identity_origin_invalid');
      const snapshot = () => {
        const account = localStorage.getItem('yb_user_id');
        const token = localStorage.getItem('yb_token');
        const pairs = [];
        if (account !== null || token !== null) {
          if (account === null || token === null) throw new Error('credential_missing');
          if (!valid(account, 1024) || !valid(token, 8192)) throw new Error('identity_material_invalid');
          pairs.push([account, token]);
        }
        // Only bounded key names and matching, bounded records are inspected.
        const count = localStorage.length;
        if (!Number.isSafeInteger(count) || count < 0 || count > 128) throw new Error('identity_material_invalid');
        let records = 0;
        for (let i = 0; i < count; i++) {
          const key = localStorage.key(i);
          if (typeof key !== 'string' || !key.startsWith('LOCAL_AUTH_INFO_KEY_')) continue;
          if (++records > 8 || encoder.encode(key).length > 256) throw new Error('identity_material_invalid');
          const raw = localStorage.getItem(key);
          if (typeof raw !== 'string' || encoder.encode(raw).length > 16384) throw new Error('identity_material_invalid');
          let record;
          try { record = JSON.parse(raw); } catch { throw new Error('identity_material_invalid'); }
          if (!record || typeof record !== 'object' || Array.isArray(record) ||
              !valid(record.userId, 1024) || !valid(record.token, 8192)) throw new Error('identity_material_invalid');
          pairs.push([record.userId, record.token]);
        }
        if (!pairs.length) throw new Error('credential_missing');
        if (pairs.some(pair => pair[0] !== pairs[0][0] || pair[1] !== pairs[0][1])) throw new Error('identity_account_conflict');
        return pairs[0];
      };
      const before = snapshot();
      if (!inScope()) return fail('identity_navigation_changed');
      const after = snapshot();
      if (!inScope()) return fail('identity_navigation_changed');
      if (before[0] !== after[0] || before[1] !== after[1]) return fail('identity_account_conflict');
      return { origin, account_id: after[0], auth_token: after[1] };
    } catch (error) {
      // Storage may throw arbitrary secret-bearing errors: never export them.
      const known = ['credential_missing', 'identity_material_invalid', 'identity_account_conflict'];
      return fail(known.includes(error?.message) ? error.message : 'identity_storage_unavailable');
    }
  }

  function scopedTab(tab) {
    if (!tab || tab.incognito !== false || !Number.isSafeInteger(tab.id) || typeof tab.url !== 'string') return false;
    try { return new URL(tab.url).origin === ORIGIN; } catch { return false; }
  }
  function checkedResult(results, documentId) {
    if (!Array.isArray(results) || results.length !== 1 || results[0].frameId !== 0 ||
        typeof results[0].documentId !== 'string' || !results[0].documentId ||
        (documentId && results[0].documentId !== documentId)) throw new Error('identity_navigation_changed');
    const result = results[0].result;
    if (result && Object.keys(result).length === 1 && CAUSES.has(result.cause)) throw new Error(result.cause);
    if (!result || Object.keys(result).sort().join(',') !== 'account_id,auth_token,origin' ||
        result.origin !== ORIGIN || typeof result.account_id !== 'string' || typeof result.auth_token !== 'string') throw new Error('identity_material_invalid');
    return result;
  }
  async function readExistingAccount(api, operationDeadlineMs) {
    const deadline = Math.min(Date.now() + 5000, operationDeadlineMs);
    const checkDeadline = () => { if (!Number.isFinite(deadline) || Date.now() >= deadline) throw new Error('extension_timeout'); };
    // A stalled Chrome promise must release the worker's serial message chain.
    // Every call shares the same deadline; late results remain race-consumed.
    const awaitChrome = async action => {
      checkDeadline();
      let timer;
      try {
        return await Promise.race([
          Promise.resolve().then(() => { checkDeadline(); return action(); }),
          new Promise((_, reject) => {
            timer = setTimeout(() => reject(new Error('extension_timeout')), deadline - Date.now());
          }),
        ]);
      } finally { clearTimeout(timer); }
    };
    try {
      checkDeadline();
      const queried = await awaitChrome(() => api.tabs.query({ url: ORIGIN + '/*' }));
      checkDeadline();
      const tabs = queried.filter(scopedTab);
      if (!tabs.length) throw new Error('identity_page_unavailable');
      if (tabs.length !== 1) throw new Error('identity_tab_ambiguous');
      const tab = tabs[0];
      if (tab.pendingUrl) throw new Error('identity_navigation_changed');
      const first = await awaitChrome(() => api.scripting.executeScript({
        target: { tabId: tab.id, frameIds: [0] }, world: 'ISOLATED', func: readAccount,
      }));
      checkDeadline();
      const account = checkedResult(first);
      const current = await awaitChrome(() => api.tabs.get(tab.id));
      checkDeadline();
      if (!scopedTab(current) || current.pendingUrl || current.url !== tab.url) throw new Error('identity_navigation_changed');
      // Target the same document, so even a same-URL reload is rejected.
      const second = await awaitChrome(() => api.scripting.executeScript({
        target: { tabId: tab.id, documentIds: [first[0].documentId] }, world: 'ISOLATED', func: readAccount,
      }));
      checkDeadline();
      const confirmed = checkedResult(second, first[0].documentId);
      if (account.account_id !== confirmed.account_id || account.auth_token !== confirmed.auth_token) throw new Error('identity_account_conflict');
      const finalTab = await awaitChrome(() => api.tabs.get(tab.id));
      checkDeadline();
      if (!scopedTab(finalTab) || finalTab.pendingUrl || finalTab.url !== tab.url) throw new Error('identity_navigation_changed');
      return confirmed;
    } catch (error) {
      return { cause: CAUSES.has(error?.message) ? error.message : 'identity_page_unavailable' };
    }
  }
  const api = { readAccount, readExistingAccount };
  globalThis.FrameFetchYuanbaoAccount = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
