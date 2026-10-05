/* Only the declared first-party page may be opened; user tabs are never navigated. */
(() => {
  const ORIGIN = 'https://yuanbao.tencent.com';
  let opening = null;
  function scopedTab(tab) {
    if (!tab || tab.incognito !== false || !Number.isSafeInteger(tab.id) || typeof tab.url !== 'string') return false;
    try {
      const url = new URL(tab.url);
      return url.origin === ORIGIN && !url.username && !url.password;
    } catch { return false; }
  }
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
  async function findTabs(api) {
    return (await api.tabs.query({ url: ORIGIN + '/*' })).filter(scopedTab);
  }
  async function loaded(api, tab, deadline) {
    while (tab.status === 'loading' || tab.pendingUrl) {
      await beforeDeadline(deadline, () => new Promise(resolve => setTimeout(resolve, 200)));
      tab = await beforeDeadline(deadline, () => api.tabs.get(tab.id));
      if (tab.url && !scopedTab(tab)) throw new Error('identity_origin_invalid');
    }
    if (!scopedTab(tab)) throw new Error('identity_origin_invalid');
    return tab;
  }
  async function status(api) {
    const tabs = await beforeDeadline(Date.now() + 2000, () => findTabs(api));
    if (!tabs.length) return 'missing';
    if (tabs.length !== 1) return 'ambiguous';
    const tab = tabs[0];
    if (tab.discarded || tab.frozen) return 'inactive';
    return tab.pendingUrl || tab.status === 'loading' ? 'loading' : 'available';
  }
  async function open(api, deadline, active) {
    const tabs = await beforeDeadline(deadline, () => findTabs(api));
    if (tabs.length > 1) throw new Error('identity_tab_ambiguous');
    if (tabs.length === 1) {
      if (active) await beforeDeadline(deadline, () => api.tabs.update(tabs[0].id, { active: true }));
      return tabs[0];
    }
    // Popup and authenticated task can arrive together. Share only the opening
    // operation, never account material, and never create duplicate pages.
    if (!opening) {
      opening = beforeDeadline(deadline, async () => {
        const created = await api.tabs.create({ url: ORIGIN + '/', active: false });
        if (!Number.isSafeInteger(created?.id) || created.incognito !== false) throw new Error('identity_page_unavailable');
        return loaded(api, created, deadline);
      });
      const pending = opening;
      void pending.finally(() => { if (opening === pending) opening = null; }).catch(() => {});
    }
    const pending = opening;
    const tab = await beforeDeadline(deadline, () => pending);
    if (!Number.isSafeInteger(tab?.id) || tab.incognito !== false) throw new Error('identity_page_unavailable');
    if (active) await beforeDeadline(deadline, () => api.tabs.update(tab.id, { active: true }));
    return tab;
  }
  async function prepare(api, deadline) {
    const tab = await loaded(api, await open(api, deadline, false), deadline);
    if (tab.discarded || tab.frozen) throw new Error('identity_page_unavailable');
    const current = await beforeDeadline(deadline, () => findTabs(api));
    if (current.length > 1) throw new Error('identity_tab_ambiguous');
    if (current.length !== 1 || current[0].id !== tab.id || current[0].url !== tab.url || current[0].pendingUrl) throw new Error('identity_navigation_changed');
    return tab;
  }
  const api = { beforeDeadline, scopedTab, status, open, prepare };
  globalThis.FrameFetchYuanbaoPage = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
