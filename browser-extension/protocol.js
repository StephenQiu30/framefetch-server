/* Shared by the MV3 worker and Node protocol tests. No browser state is stored. */
(() => {
  const encoder = new TextEncoder();
  const NONCE = /^[a-f0-9]{64}$/;
  const MAX_MESSAGE_BYTES = 1024 * 1024;
  function nonce() {
    return Array.from(crypto.getRandomValues(new Uint8Array(32)), b => b.toString(16).padStart(2, '0')).join('');
  }
  async function proof(key, role, peer, own) {
    if (!NONCE.test(peer) || !NONCE.test(own) || !['server', 'extension'].includes(role)) throw new Error('invalid_challenge');
    const secret = await crypto.subtle.importKey('raw', encoder.encode(key), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    const signature = await crypto.subtle.sign('HMAC', secret, encoder.encode(role + peer + own));
    return Array.from(new Uint8Array(signature), b => b.toString(16).padStart(2, '0')).join('');
  }
  function equal(a, b) {
    if (typeof b !== 'string' || a.length !== b.length) return false;
    let difference = 0;
    for (let i = 0; i < a.length; i++) difference |= a.charCodeAt(i) ^ b.charCodeAt(i);
    return difference === 0;
  }
  function allowed(domain, domains) {
    const host = domain.replace(/^\./, '').toLowerCase();
    return domains.some(d => host === d || host.endsWith('.' + d));
  }
  function filterCookies(cookies, domains) {
    return cookies.filter(c => !c.partitionKey && allowed(c.domain, domains)).map(c => ({
      domain: c.domain, path: c.path, name: c.name, value: c.value,
      secure: c.secure, httpOnly: c.httpOnly, hostOnly: c.hostOnly,
      expirationDate: c.expirationDate,
    }));
  }
  class Protocol {
    constructor(config, getAll, send, version, readAccount) {
      this.config = config;
      this.getAll = getAll;
      this.send = send;
      this.version = version;
      this.readAccount = readAccount;
      this.own = nonce();
      this.peer = null;
      this.authenticated = false;
      this.busy = false;
    }
    async receive(message) {
      if (message.type === 'challenge' && !this.peer) {
        if (!NONCE.test(message.nonce)) throw new Error('invalid_challenge');
        this.peer = message.nonce;
        this.send({ type: 'challenge', nonce: this.own });
        return;
      }
      if (message.type === 'proof' && this.peer && !this.authenticated) {
        const expected = await proof(this.config.pairingKey, 'server', this.own, this.peer);
        if (!equal(expected, message.proof)) throw new Error('server_authentication_failed');
        this.authenticated = true;
        this.send({ type: 'proof', proof: await proof(this.config.pairingKey, 'extension', this.peer, this.own), version: this.version });
        return;
      }
      if (!this.authenticated) throw new Error('unauthenticated_request');
      if (message.type === 'ping') { this.send({ type: 'pong' }); return; }
      if (message.type === 'pong' || message.type === 'ready') return;
      if (this.busy || !/^[a-f0-9]{32}$/.test(message.request_id)) throw new Error('invalid_request');
      if (message.type === 'yuanbao_account') {
        if (Object.keys(message).sort().join(',') !== 'deadline,request_id,site,type' ||
            message.site !== 'wechat_channels' || this.config.yuanbaoAccount !== true ||
            typeof this.readAccount !== 'function') throw new Error('undeclared_source');
        if (typeof message.deadline !== 'string' ||
            !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(message.deadline)) throw new Error('invalid_deadline');
        const deadlineMs = Date.parse(message.deadline);
        if (!Number.isFinite(deadlineMs)) throw new Error('invalid_deadline');
        if (Date.now() >= deadlineMs) {
          this.send({ type: 'yuanbao_account', request_id: message.request_id, cause: 'extension_timeout' });
          return;
        }
        this.busy = true;
        try {
          const account = await this.readAccount(deadlineMs);
          if (Date.now() >= deadlineMs) {
            this.send({ type: 'yuanbao_account', request_id: message.request_id, cause: 'extension_timeout' });
            return;
          }
          this.send({ type: 'yuanbao_account', request_id: message.request_id, ...account });
        } finally { this.busy = false; }
        return;
      }
      if (message.type !== 'cookies') throw new Error('invalid_request');
      const domains = message.domains;
      if (!Array.isArray(domains) || !domains.length || domains.length > this.config.domains.length ||
          new Set(domains).size !== domains.length || !domains.every(d => this.config.domains.includes(d))) throw new Error('undeclared_domain');
      this.busy = true;
      try {
        const results = await Promise.all(domains.map(domain => this.getAll({ domain })));
        const selected = filterCookies(results.flat(), domains);
        const unique = [...new Map(selected.map(c => [JSON.stringify([c.domain, c.path, c.name]), c])).values()];
        const response = { type: 'cookies', request_id: message.request_id, cookies: unique };
        if (encoder.encode(JSON.stringify(response)).length > MAX_MESSAGE_BYTES) throw new Error('message_too_large');
        this.send(response);
      } finally { this.busy = false; }
    }
  }
  class Backoff {
    constructor() { this.attempt = 0; }
    next() { return this.attempt++ === 0 ? 0 : Math.min(30000, 1000 * 2 ** Math.min(this.attempt - 2, 5)); }
    reset() { this.attempt = 0; }
  }
  const api = { Protocol, Backoff, proof, filterCookies, MAX_MESSAGE_BYTES };
  globalThis.FrameFetchIdentity = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
