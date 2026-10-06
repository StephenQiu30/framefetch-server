import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthField, AuthPageFrame } from '@/components/auth/auth-page-frame';
import { BasicLayout } from '@/components/layout/basic-layout';
import { InputGroupInput } from '@/components/ui/input-group';
import { render } from '../helpers/query-render';

const runtime = vi.hoisted(() => ({
  loading: false,
  status: undefined as 'unknown' | undefined,
  pathname: '/',
  replace: vi.fn(),
  user: undefined as
    | undefined
    | {
        created_at: string;
        email: string;
        id: string;
        role: 'admin' | 'user';
        updated_at: string;
        username: string;
      },
}));

vi.mock('@/components/auth/auth-provider', async (importOriginal) => ({
  ...(await importOriginal()),
  useAuth: () => ({
    loading: runtime.loading,
    status:
      runtime.status ??
      (runtime.loading
        ? 'unknown'
        : runtime.user
          ? 'authenticated'
          : 'anonymous'),
    signOut: vi.fn(),
    user: runtime.user,
  }),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => runtime.pathname,
  useRouter: () => ({ refresh: vi.fn(), replace: runtime.replace }),
}));

describe('BasicLayout', () => {
  beforeEach(() => {
    document.documentElement.style.setProperty('--breakpoint-lg', '64rem');
    runtime.loading = false;
    runtime.status = undefined;
    runtime.pathname = '/';
    runtime.replace.mockReset();
    runtime.user = undefined;
  });

  it.each([
    '/',
    '/history',
    '/history/activity',
    '/documents',
    '/providers',
    '/admin/operation-logs',
    '/user/login',
    '/user/register',
    '/guide/',
  ])('mounts quick actions in the header on %s', (pathname) => {
    runtime.pathname = pathname;
    render(
      <BasicLayout>
        <div>页面内容</div>
      </BasicLayout>,
    );
    expect(
      within(screen.getByRole('banner')).getByRole('button', {
        name: '搜索或粘贴链接',
      }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole('contentinfo')).queryByRole('button', {
        name: '搜索或粘贴链接',
      }),
    ).not.toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    expect(screen.getAllByRole('dialog', { name: '快捷操作' })).toHaveLength(1);
    expect(
      screen.getByRole('option', { name: '登录后使用' }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('option', { name: /解析链接/ }),
    ).not.toBeInTheDocument();
  });

  it('keeps only the brand and authorization note in the mobile footer', () => {
    vi.stubGlobal('matchMedia', () => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));

    try {
      render(
        <BasicLayout>
          <div>页面内容</div>
        </BasicLayout>,
      );

      const footer = screen.getByRole('contentinfo');
      expect(
        within(footer).getByRole('link', { name: '帧取 · FrameFetch' }),
      ).toBeInTheDocument();
      expect(
        within(footer).getByText(/请仅处理已获授权内容/),
      ).toBeInTheDocument();
      expect(
        within(footer).queryByRole('button', { name: '搜索或粘贴链接' }),
      ).not.toBeInTheDocument();
      expect(
        within(footer).queryByRole('navigation', { name: '项目链接' }),
      ).not.toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('renders the shared accessible navigation on application routes', () => {
    runtime.pathname = '/providers';
    render(
      <BasicLayout>
        <div>页面内容</div>
      </BasicLayout>,
    );

    const banner = screen.getByRole('banner');
    expect(banner).toBeInTheDocument();
    const brandLink = screen.getByRole('link', { name: '帧取首页' });
    expect(brandLink).toHaveAttribute('href', '/');
    expect(brandLink.querySelector('img')).toHaveAttribute('src', '/logo.svg');
    const desktopNavigation = screen.getByRole('navigation', {
      name: '主要导航',
    });
    expect(desktopNavigation).toHaveAttribute('data-slot', 'navigation-menu');
    const desktopHomeLink = within(desktopNavigation).getByRole('link', {
      name: '首页',
    });
    expect(desktopHomeLink).toHaveAttribute('href', '/');
    expect(desktopHomeLink).not.toHaveAttribute('aria-current');
    const historyLink = screen.getByRole('link', { name: /下载记录/ });
    expect(historyLink).toHaveAttribute('href', '/history');
    expect(historyLink).not.toHaveAttribute('aria-current');
    expect(
      screen.queryByRole('link', { name: /解析中心/ }),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByRole('navigation', { name: '主要导航' })).getByRole(
        'link',
        { name: '剧本文档' },
      ),
    ).toHaveAttribute('href', '/documents');
    expect(screen.getByRole('link', { name: /平台状态/ })).toHaveAttribute(
      'href',
      '/providers',
    );
    expect(screen.getByRole('link', { name: /账户/ })).toHaveAttribute(
      'href',
      '/user/login?redirect=%2Fproviders',
    );
    expect(screen.getByRole('link', { name: '跳到主要内容' })).toHaveAttribute(
      'href',
      '#main-content',
    );

    const mobileMenuTrigger = screen.getByRole('button', {
      name: '打开导航菜单',
    });
    fireEvent.click(mobileMenuTrigger);
    const mobileNavigation = screen.getByRole('navigation', {
      name: '移动导航',
    });
    expect(mobileNavigation).toHaveAttribute('data-slot', 'navigation-menu');
    expect(
      within(mobileNavigation).getByRole('link', { name: '首页' }),
    ).not.toHaveAttribute('aria-current');
    expect(
      within(mobileNavigation).getByRole('link', { name: '下载记录' }),
    ).not.toHaveAttribute('aria-current');
    expect(
      within(mobileNavigation)
        .getAllByRole('link', { name: '剧本文档' })
        .find((link) => link.getAttribute('href') === '/documents'),
    ).toHaveAttribute('href', '/documents');
    expect(
      within(mobileNavigation).getByRole('link', { name: '平台状态' }),
    ).toHaveAttribute('aria-current', 'page');
    expect(desktopNavigation.querySelector('a[href^="/content"]')).toBeNull();
    expect(mobileNavigation.querySelector('a[href^="/content"]')).toBeNull();
  });

  it('does not advertise anonymous login while identity recovery is unavailable', () => {
    runtime.status = 'unknown';
    runtime.loading = false;
    render(
      <BasicLayout>
        <div>原地恢复</div>
      </BasicLayout>,
    );
    expect(
      screen.queryByRole('link', { name: '登录' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '打开导航菜单' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '帧取首页' })).toBeVisible();
  });

  it.each(['/', '/guide', '/guide/', '/self-hosting/', '/about'])(
    'renders public navigation on %s',
    (pathname) => {
      runtime.pathname = pathname;
      render(
        <BasicLayout>
          <div>公开首页</div>
        </BasicLayout>,
      );

      const navigation = screen.getByRole('navigation', { name: '主要导航' });
      expect(
        within(navigation).getByRole('link', { name: '产品能力' }),
      ).toHaveAttribute('href', '/#capabilities');
      expect(
        within(navigation).getByRole('link', { name: '自托管架构' }),
      ).toHaveAttribute('href', '/#architecture');
      expect(
        within(navigation).getByRole('link', { name: 'GitHub' }),
      ).toHaveAttribute('href', 'https://github.com/StephenQiu30/video-server');
      expect(screen.getByRole('link', { name: '登录' })).toHaveAttribute(
        'href',
        '/user/login',
      );
      expect(
        screen.getByRole('button', { name: /切换到.+主题/ }),
      ).toBeInTheDocument();
      expect(screen.queryAllByRole('menuitemradio')).toHaveLength(0);
      expect(
        screen.getByRole('button', { name: '打开导航菜单' }),
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: '打开导航菜单' }));
      const mobileNavigation = screen.getByRole('navigation', {
        name: '移动导航',
      });
      expect(
        within(mobileNavigation).getByRole('link', { name: '使用指南' }),
      ).toHaveAttribute('href', expect.stringMatching(/^\/guide\/?$/));
      expect(
        within(mobileNavigation).getByRole('link', { name: '自托管部署' }),
      ).toHaveAttribute('href', expect.stringMatching(/^\/self-hosting\/?$/));
      expect(
        within(mobileNavigation).getByRole('link', { name: '关于' }),
      ).toHaveAttribute('href', expect.stringMatching(/^\/about\/?$/));
    },
  );

  it.each(['/', '/guide/'])(
    'hides authenticated navigation during session discovery on %s',
    (pathname) => {
      runtime.pathname = pathname;
      runtime.loading = true;
      const { container } = render(
        <BasicLayout>
          <div>正在加载</div>
        </BasicLayout>,
      );

      const actions = container.querySelector('[data-slot="header-actions"]');
      expect(actions).toHaveAttribute('aria-busy', 'true');
      expect(
        container.querySelector('[data-slot="header-auth-pending"]'),
      ).toBeInTheDocument();
      expect(
        container.querySelector('[data-slot="header-account"]'),
      ).not.toBeInTheDocument();
      expect(
        container.querySelector('[data-slot="skeleton"]'),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('navigation', { name: '主要导航' }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: /切换到.+主题/ }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('link', { name: /账户/ }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: '打开导航菜单' }),
      ).not.toBeInTheDocument();
    },
  );

  it('focuses the mobile navigation title instead of the sign-out action', async () => {
    runtime.user = {
      created_at: '2026-08-09T10:00:00Z',
      email: 'viewer@example.com',
      id: 'viewer-id',
      role: 'user',
      updated_at: '2026-08-09T10:00:00Z',
      username: 'viewer',
    };
    render(
      <BasicLayout>
        <div>页面内容</div>
      </BasicLayout>,
    );

    fireEvent.click(screen.getByRole('button', { name: '打开导航菜单' }));

    const title = await screen.findByRole('heading', { name: '导航' });
    await waitFor(() => expect(title).toHaveFocus());
    expect(screen.getByRole('button', { name: '退出登录' })).not.toHaveFocus();
  });

  it('keeps explicit desktop and mobile routes from history back to parsing', async () => {
    runtime.pathname = '/history';
    render(
      <BasicLayout>
        <div>历史页面</div>
      </BasicLayout>,
    );

    expect(screen.getByRole('link', { name: '帧取首页' })).toHaveAttribute(
      'href',
      '/',
    );
    const desktopNavigation = screen.getByRole('navigation', {
      name: '主要导航',
    });
    expect(
      within(desktopNavigation).getByRole('link', { name: '下载记录' }),
    ).toHaveAttribute('aria-current', 'page');

    fireEvent.click(screen.getByRole('button', { name: '打开导航菜单' }));
    const mobileNavigation = await screen.findByRole('navigation', {
      name: '移动导航',
    });
    const mobileParserLink = within(mobileNavigation).getByRole('link', {
      name: '首页',
    });
    expect(mobileParserLink).toHaveAttribute('href', '/');
    expect(mobileParserLink).not.toHaveAttribute('aria-current');
    expect(
      within(mobileNavigation).getByRole('link', { name: '下载记录' }),
    ).toHaveAttribute('aria-current', 'page');
    fireEvent.click(mobileParserLink);
    expect(
      screen.queryByRole('navigation', { name: '移动导航' }),
    ).not.toBeInTheDocument();
  });

  it('keeps personal activity out of desktop and mobile primary navigation', async () => {
    runtime.pathname = '/history/activity';
    render(
      <BasicLayout>
        <div>解析历史页面</div>
      </BasicLayout>,
    );

    const desktopNavigation = screen.getByRole('navigation', {
      name: '主要导航',
    });
    expect(
      within(desktopNavigation).queryByRole('link', { name: '解析中心' }),
    ).not.toBeInTheDocument();
    expect(
      within(desktopNavigation).getByRole('link', { name: '下载记录' }),
    ).not.toHaveAttribute('aria-current');

    fireEvent.click(screen.getByRole('button', { name: '打开导航菜单' }));
    const mobileNavigation = await screen.findByRole('navigation', {
      name: '移动导航',
    });
    expect(
      within(mobileNavigation).queryByRole('link', { name: '解析中心' }),
    ).not.toBeInTheDocument();
    expect(
      within(mobileNavigation).getByRole('link', { name: '下载记录' }),
    ).not.toHaveAttribute('aria-current');
  });

  it('exposes download analytics to administrators on desktop and mobile', async () => {
    runtime.pathname = '/admin/analytics';
    runtime.user = {
      created_at: '2026-08-09T10:00:00Z',
      email: 'owner@example.com',
      id: 'owner-id',
      role: 'admin',
      updated_at: '2026-08-09T10:00:00Z',
      username: 'owner',
    };
    render(
      <BasicLayout>
        <div>使用统计页面</div>
      </BasicLayout>,
    );

    fireEvent.pointerDown(
      screen.getByRole('button', { name: '打开账户菜单' }),
      { button: 0, ctrlKey: false },
    );
    const desktopLink = await screen.findByRole('menuitem', {
      name: '使用统计',
    });
    expect(desktopLink).toHaveAttribute('href', '/admin/analytics');
    expect(
      screen.getByRole('menuitem', { name: '系统操作日志' }),
    ).toHaveAttribute('href', '/admin/operation-logs');
    expect(desktopLink).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('menuitem', { name: '平台目录' })).toHaveAttribute(
      'href',
      '/admin/providers',
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() =>
      expect(
        screen.queryByRole('menuitem', { name: '使用统计' }),
      ).not.toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole('button', { name: '打开导航菜单' }));
    const mobileNavigation = await screen.findByRole('navigation', {
      name: '移动导航',
    });
    const mobileLink = within(mobileNavigation).getByRole('link', {
      name: '使用统计',
    });
    expect(mobileLink).toHaveAttribute('href', '/admin/analytics');
    expect(mobileLink).toHaveAttribute('aria-current', 'page');
    expect(
      within(mobileNavigation).getByRole('link', { name: '平台目录' }),
    ).toHaveAttribute('href', '/admin/providers');
  });

  it('opens the avatar menu on mouse hover and keeps it open while entering the menu', async () => {
    runtime.user = {
      created_at: '2026-08-09T10:00:00Z',
      email: 'owner@example.com',
      id: 'owner-id',
      role: 'admin',
      updated_at: '2026-08-09T10:00:00Z',
      username: 'owner',
    };
    render(
      <BasicLayout>
        <div>页面内容</div>
      </BasicLayout>,
    );

    const trigger = screen.getByRole('button', { name: '打开账户菜单' });
    expect(trigger.querySelector('svg')).toBeNull();
    fireEvent.pointerOver(trigger, { pointerType: 'mouse' });
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    const item = await screen.findByRole('menuitem', { name: '个人资料' });
    const menu = item.closest('[role="menu"]');
    expect(menu).not.toBeNull();
    fireEvent.pointerLeave(trigger, { pointerType: 'mouse' });
    fireEvent.pointerEnter(menu as HTMLElement, { pointerType: 'mouse' });
    await new Promise((resolve) => setTimeout(resolve, 220));
    expect(menu).toBeInTheDocument();

    fireEvent.pointerLeave(menu as HTMLElement, { pointerType: 'mouse' });
    await waitFor(() => expect(item).not.toBeInTheDocument());
  });

  it('uses the shared BasicLayout chrome on authentication routes', () => {
    runtime.pathname = '/user/login';
    render(
      <BasicLayout>
        <AuthPageFrame
          description="登录后继续使用。"
          title="登录帧取"
          titleId="login-title"
        >
          <div>登录页面</div>
        </AuthPageFrame>
      </BasicLayout>,
    );

    expect(document.querySelector('[data-slot="basic-layout"]')).toBeTruthy();
    expect(document.querySelector('header.sticky')).toBeInTheDocument();
    expect(
      screen.queryByRole('navigation', { name: '主要导航' }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /切换到.+主题/ }),
    ).toBeInTheDocument();
  });

  it('keeps the authentication heading and field semantics accessible', () => {
    const { container } = render(
      <AuthPageFrame
        description="登录后继续使用。"
        title="登录帧取"
        titleId="login-title"
      >
        <AuthField
          error="请输入邮箱地址"
          idPrefix="login"
          label="邮箱地址"
          name="email"
        >
          <InputGroupInput
            aria-describedby="email-error"
            aria-invalid
            id="login-email"
          />
        </AuthField>
      </AuthPageFrame>,
    );

    expect(screen.getByRole('heading', { level: 1 })).toHaveAttribute(
      'id',
      'login-title',
    );
    expect(
      screen.getByRole('link', { name: '返回上一步' }),
    ).toBeInTheDocument();
    expect(screen.getByText('FrameFetch 万能视频下载器')).toBeInTheDocument();
    expect(screen.getByLabelText('邮箱地址')).toHaveAttribute(
      'aria-describedby',
      'email-error',
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(
      container.querySelector('[data-slot="auth-frame"]'),
    ).toBeInTheDocument();
    expect(container.querySelector('[data-slot="card"]')).toBeNull();
  });
});
