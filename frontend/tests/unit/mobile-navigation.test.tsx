import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { MobileNavigation } from '@/components/layout/mobile-navigation';
import { render } from '../helpers/query-render';

const viewer: API.UserResponse = {
  created_at: '2026-10-01T00:00:00Z',
  email: 'viewer@example.com',
  id: 'viewer-id',
  role: 'user',
  updated_at: '2026-10-01T00:00:00Z',
  username: 'viewer',
};

function renderNavigation({
  pathname = '/guide/',
  signingOut = false,
  user,
}: {
  pathname?: string;
  signingOut?: boolean;
  user?: API.UserResponse;
} = {}) {
  const onSignOut = vi.fn(async () => undefined);
  render(
    <MobileNavigation
      loading={false}
      onSignOut={onSignOut}
      pathname={pathname}
      signingOut={signingOut}
      user={user}
    />,
  );
  const trigger = screen.getByRole('button', { name: '打开导航菜单' });
  fireEvent.click(trigger);
  return { onSignOut, trigger };
}

describe('mobile navigation', () => {
  it('keeps public resources and authentication reachable for anonymous visitors', () => {
    renderNavigation();

    const resources = screen.getByRole('region', { name: '资源' });
    expect(
      within(resources).getByRole('link', { name: '使用指南' }),
    ).toHaveAttribute('href', '/guide');
    expect(
      within(resources).getByRole('link', { name: '使用指南' }),
    ).toHaveAttribute('aria-current', 'page');
    expect(
      within(resources).getByRole('link', { name: '自托管部署' }),
    ).toHaveAttribute('href', '/self-hosting');
    expect(
      within(resources).getByRole('link', { name: '关于' }),
    ).toHaveAttribute('href', '/about');
    expect(
      within(resources).getByRole('link', { name: 'GitHub' }),
    ).toHaveAttribute(
      'href',
      'https://github.com/StephenQiu30/framefetch-server',
    );
    expect(
      within(resources).getByRole('link', { name: '文档' }),
    ).toHaveAttribute(
      'href',
      'https://github.com/StephenQiu30/framefetch-server/tree/main/docs',
    );
    expect(screen.getByRole('link', { name: '登录账户' })).toHaveAttribute(
      'href',
      '/user/login?redirect=%2Fguide%2F',
    );
    expect(screen.getByRole('link', { name: '注册账户' })).toHaveAttribute(
      'href',
      '/user/register',
    );
    expect(
      screen.queryByRole('region', { name: '管理' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('link', { name: '我的处理记录' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '退出登录' }),
    ).not.toBeInTheDocument();
  });

  it('exposes personal activity for signed-in users without exposing administrator links', () => {
    renderNavigation({ pathname: '/history/activity', user: viewer });

    const workspace = screen.getByRole('region', { name: '工作区' });
    expect(
      within(workspace).getByRole('link', { name: '我的处理记录' }),
    ).toHaveAttribute('href', '/history/activity');
    expect(
      within(workspace).getByRole('link', { name: '我的处理记录' }),
    ).toHaveAttribute('aria-current', 'page');
    expect(
      within(workspace).getByRole('link', { name: '下载记录' }),
    ).not.toHaveAttribute('aria-current');
    expect(
      within(workspace).getByRole('link', { name: '个人资料' }),
    ).toHaveAttribute('href', '/account');
    expect(screen.getByRole('region', { name: '资源' })).toBeInTheDocument();
    expect(
      screen.queryByRole('region', { name: '管理' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('link', { name: '登录账户' }),
    ).not.toBeInTheDocument();
  });

  it('groups all administrator routes alongside workspace and resources', () => {
    renderNavigation({
      pathname: '/admin/users',
      user: { ...viewer, role: 'admin' },
    });

    const management = screen.getByRole('region', { name: '管理' });
    expect(within(management).getAllByRole('link')).toHaveLength(6);
    expect(
      within(management).getByRole('link', { name: '用户管理' }),
    ).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('region', { name: '工作区' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '资源' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '退出登录' })).toBeEnabled();
  });

  it('focuses the title and restores focus after a resource link closes the drawer', async () => {
    const { trigger } = renderNavigation({ user: viewer });

    const title = screen.getByRole('heading', { name: '导航' });
    await waitFor(() => expect(title).toHaveFocus());
    expect(screen.getByRole('button', { name: '退出登录' })).not.toHaveFocus();

    fireEvent.click(screen.getByRole('link', { name: '关于' }));

    await waitFor(() => {
      expect(
        screen.queryByRole('dialog', { name: '导航' }),
      ).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    });
  });

  it('closes on Escape and restores the menu trigger focus', async () => {
    const { trigger } = renderNavigation();

    fireEvent.keyDown(document, { key: 'Escape' });

    await waitFor(() => {
      expect(
        screen.queryByRole('dialog', { name: '导航' }),
      ).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    });
  });

  it('runs sign-out once and closes the drawer', async () => {
    const { onSignOut } = renderNavigation({ user: viewer });

    fireEvent.click(screen.getByRole('button', { name: '退出登录' }));

    expect(onSignOut).toHaveBeenCalledOnce();
    await waitFor(() =>
      expect(
        screen.queryByRole('dialog', { name: '导航' }),
      ).not.toBeInTheDocument(),
    );
  });

  it('prevents duplicate sign-out while the request is pending', () => {
    const { onSignOut } = renderNavigation({ signingOut: true, user: viewer });
    const signOut = screen.getByRole('button', { name: '正在退出…' });

    expect(signOut).toBeDisabled();
    fireEvent.click(signOut);
    expect(onSignOut).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog', { name: '导航' })).toBeInTheDocument();
  });
});
