import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DownloadWorkspace from '@/components/intake/download-workspace';
import { PUBLIC_INPUT_REQUIRED } from '@/components/intake/public-input';
import { QuickParseDialog } from '@/components/intake/quick-parse-dialog';
import { TooltipProvider } from '@/components/ui/tooltip';
import { intentFixture } from '../fixtures/intent-fixtures';
import { httpRequests, mockHttpResponses } from '../helpers/http';
import { render } from '../helpers/query-render';

const identity = vi.hoisted(() => ({ authenticated: true, role: 'user' }));
const navigation = vi.hoisted(() => ({ pathname: '/history', push: vi.fn() }));

vi.mock('@/components/auth/auth-provider', async (importOriginal) => ({
  ...(await importOriginal()),
  useAuth: () => ({
    user: identity.authenticated
      ? { id: 'quick-parse-owner', role: identity.role }
      : null,
  }),
}));
vi.mock('next/navigation', () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ push: navigation.push }),
}));

function Harness() {
  const [home, setHome] = useState(false);
  return (
    <TooltipProvider>
      <QuickParseDialog />
      <button onClick={() => setHome(true)} type="button">
        挂载首页
      </button>
      {home ? <DownloadWorkspace /> : null}
    </TooltipProvider>
  );
}

describe('quick parse', () => {
  beforeEach(() => {
    identity.authenticated = true;
    identity.role = 'user';
    navigation.pathname = '/history';
    navigation.push.mockReset();
    window.history.replaceState({}, '', '/history');
  });

  it('restores the keyboard origin when dismissed', async () => {
    render(<Harness />);
    const origin = screen.getByRole('button', { name: '挂载首页' });
    origin.focus();
    fireEvent.keyDown(origin, { key: 'k', ctrlKey: true });
    expect(screen.getByRole('combobox', { name: '链接或页面' })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('combobox', { name: '链接或页面' }), {
      key: 'Escape',
    });
    await waitFor(() => expect(origin).toHaveFocus());
  });

  it('offers anonymous users login without queuing a parse', () => {
    identity.authenticated = false;
    navigation.pathname = '/user/register';
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '快捷操作' }));
    fireEvent.click(screen.getByRole('option', { name: '登录后使用' }));
    expect(navigation.push).toHaveBeenCalledWith('/user/login?redirect=%2F');
    expect(httpRequests()).toHaveLength(0);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('opens with ⌘K and hands one parse request to the homepage', async () => {
    const shareText = '看看这个视频 https://example.com/video';
    mockHttpResponses(
      intentFixture({ status: 'resolving', inspection_id: null }),
    );
    render(<Harness />);

    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    const dialog = screen.getByRole('dialog', { name: '快捷操作' });
    const input = within(dialog).getByRole('combobox', {
      name: '链接或页面',
    });
    fireEvent.change(input, { target: { value: shareText } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(navigation.push).toHaveBeenCalledWith('/');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '挂载首页' }));
    await waitFor(() =>
      expect(
        httpRequests().filter((request) => request.method === 'POST'),
      ).toHaveLength(1),
    );
    expect(httpRequests()[0].data).toEqual({ input: shareText });
    expect(screen.getByRole('textbox', { name: '公开视频地址' })).toHaveValue(
      shareText,
    );
  });

  it('supports Ctrl+K and keeps blank input in the dialog', () => {
    render(<Harness />);
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    const dialog = screen.getByRole('dialog', { name: '快捷操作' });
    fireEvent.click(within(dialog).getByRole('option', { name: /解析链接/ }));

    expect(within(dialog).getByRole('alert')).toHaveTextContent(
      PUBLIC_INPUT_REQUIRED,
    );
    expect(navigation.push).not.toHaveBeenCalled();
    expect(httpRequests()).toHaveLength(0);
  });

  it('keeps a multiline share message intact when pasted into CommandInput', () => {
    render(<Harness />);
    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    const input = screen.getByRole('combobox', {
      name: '链接或页面',
    });
    fireEvent.paste(input, {
      clipboardData: {
        getData: () => '看看这个视频\nhttps://example.com/video',
      },
    });

    expect(input).toHaveValue('看看这个视频 https://example.com/video');
  });

  it.each([
    ['上传本地视频', '本地视频'],
    ['上传剧本文档', '剧本文档'],
  ])('opens the %s workspace from ⌘K', (action, tabName) => {
    render(<Harness />);
    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    const dialog = screen.getByRole('dialog', { name: '快捷操作' });
    fireEvent.click(within(dialog).getByRole('option', { name: action }));

    expect(navigation.push).toHaveBeenCalledWith('/');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '挂载首页' }));
    expect(screen.getByRole('tab', { name: tabName })).toHaveAttribute(
      'data-state',
      'active',
    );
    expect(httpRequests()).toHaveLength(0);
  });

  it.each([
    ['首页', '/'],
    ['使用指南', '/guide/'],
    ['自托管部署', '/self-hosting/'],
    ['关于', '/about/'],
    ['下载记录', '/history'],
    ['我的处理记录', '/history/activity'],
    ['剧本文档', '/documents'],
    ['平台状态', '/providers'],
    ['个人资料', '/account'],
  ])('navigates to %s without starting a parse', (label, href) => {
    render(<Harness />);
    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    fireEvent.click(screen.getByRole('option', { name: label }));
    if (href === navigation.pathname) {
      expect(navigation.push).not.toHaveBeenCalled();
    } else {
      expect(navigation.push).toHaveBeenCalledWith(href);
    }
    expect(httpRequests()).toHaveLength(0);
  });

  it.each([
    ['系统操作日志', '/admin/operation-logs'],
    ['AI 服务', '/admin/ai-providers'],
    ['使用统计', '/admin/analytics'],
    ['文件管理', '/admin/files'],
    ['平台目录', '/admin/providers'],
    ['用户管理', '/admin/users'],
  ])('offers %s to administrators only', (label, href) => {
    identity.role = 'admin';
    render(<Harness />);
    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    fireEvent.click(screen.getByRole('option', { name: label }));
    expect(navigation.push).toHaveBeenCalledWith(href);
    expect(httpRequests()).toHaveLength(0);
  });

  it('filters page names and uses Enter for the matching page', () => {
    render(<Harness />);
    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    const input = screen.getByRole('combobox', { name: '链接或页面' });
    fireEvent.change(input, { target: { value: '剧本文档' } });
    expect(
      screen.queryByRole('option', { name: /解析链接/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('option', { name: '下载记录' }),
    ).not.toBeInTheDocument();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(navigation.push).toHaveBeenCalledWith('/documents');
    expect(httpRequests()).toHaveLength(0);
  });

  it('keeps upload commands searchable', () => {
    render(<Harness />);
    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    const input = screen.getByRole('combobox', { name: '链接或页面' });
    fireEvent.change(input, { target: { value: '上传本地视频' } });
    expect(
      screen.queryByRole('option', { name: /解析链接/ }),
    ).not.toBeInTheDocument();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(navigation.push).toHaveBeenCalledWith('/');
    expect(httpRequests()).toHaveLength(0);
  });

  it('keeps pasted share URLs on the parse action', () => {
    render(<Harness />);
    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    const input = screen.getByRole('combobox', { name: '链接或页面' });
    fireEvent.change(input, {
      target: { value: '看看这个视频 https://example.com/video' },
    });
    expect(
      screen.getByRole('option', { name: /解析链接/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('option', { name: '首页' }),
    ).not.toBeInTheDocument();
  });

  it('keeps private and admin destinations out of the anonymous menu', () => {
    identity.authenticated = false;
    render(<Harness />);
    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    expect(
      screen.getByRole('combobox', { name: '链接或页面' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('option', { name: '注册账户' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('option', { name: '使用指南' }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('option', { name: '下载记录' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('option', { name: '用户管理' }),
    ).not.toBeInTheDocument();
    expect(httpRequests()).toHaveLength(0);
  });

  it('hides admin destinations from regular accounts', () => {
    render(<Harness />);
    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    expect(
      screen.queryByRole('option', { name: '用户管理' }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('option', { name: '个人资料' }),
    ).toBeInTheDocument();
  });
});
