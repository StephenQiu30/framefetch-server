"""First-party account assertions; never infer login from Cookie presence.

Scripts return only tri-state booleans. Account identifiers and response bodies
remain inside the isolated browser, never in RPC responses or logs.
"""

from app.services.provider_types import ProviderKey

# Keep these probes tied to the authenticated page's own state, not public
# profile pages (which can identify a creator without identifying the viewer).
PAGE_IDENTITY_PROBES: dict[str, str] = {
    ProviderKey.XIAOHONGSHU: """() => {
      const user = window.__INITIAL_STATE__?.user;
      const info = user?.userInfo?.value;
      if (user?.loggedIn?.value === true && info?.userId && info.guest === false)
        return true;
      if (info?.guest === true) return false;
      return null;
    }""",
    ProviderKey.X: """() => {
      if (document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]'))
        return true;
      if (location.pathname === '/i/flow/login' &&
          document.querySelector('input[autocomplete="username"]')) return false;
      return null;
    }""",
    ProviderKey.INSTAGRAM: """() => {
      try {
        const viewer = window.require?.('PolarisViewer');
        if (typeof viewer?.id === 'string' && /^[1-9][0-9]*$/.test(viewer.id))
          return true;
      } catch (_) {}
      if (location.pathname.startsWith('/accounts/login') &&
          document.querySelector('input[name="username"]')) return false;
      return null;
    }""",
    ProviderKey.FACEBOOK: """() => {
      try {
        const user = window.require?.('CurrentUserInitialData');
        if (typeof user?.USER_ID === 'string' && /^[1-9][0-9]*$/.test(user.USER_ID))
          return true;
        if (user?.USER_ID === '0') return false;
      } catch (_) {}
      return null;
    }""",
    ProviderKey.PINTEREST: """() => {
      try {
        const node = document.querySelector('#__PWS_DATA__');
        if (!node) return null;
        const context = JSON.parse(node.textContent).context;
        if (context?.is_authenticated === true && context.user?.id) return true;
        if (context?.is_authenticated === false) return false;
      } catch (_) {}
      return null;
    }""",
    ProviderKey.YOUKU: """() => {
      const login = window.Xlogin;
      if (login?.checkLoginStatus !== true) return null;
      if (login.isLoginStatus === true && login._userInfo &&
          Object.keys(login._userInfo).length > 0) return true;
      if (login.isLoginStatus === false) return false;
      return null;
    }""",
    ProviderKey.QQVIDEO: """() => {
      const sdk = window.NavLoginPanelSDK;
      const panel = sdk?.pinia?.state?.value?.['login-panel'];
      if (sdk?.isReady && panel?.loginStatus === 1 && panel.loginInfo?.vuserid)
        return true;
      if (sdk?.isReady && panel?.loginStatus === -1) return false;
      return null;
    }""",
}

REDDIT_IDENTITY_PROBE = """async () => {
  try {
    const response = await fetch('/api/me.json', {
      credentials: 'include', signal: AbortSignal.timeout(15000)
    });
    if (response.status === 401) return false;
    if (!response.ok) return null;
    const data = await response.json();
    if (data?.data?.id && data.data.name) return true;
    if (data?.data === null) return false;
    return null;
  } catch (_) { return null; }
}"""
