import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProviderStatusView } from '@/components/providers/provider-status-view';
import { render } from '../helpers/query-render';

const runtime = vi.hoisted(() => ({
  listProviders: vi.fn(),
}));

vi.mock('@/components/auth/auth-provider', async (importOriginal) => ({
  ...(await importOriginal()),
  useAuth: () => ({
    user: { role: 'admin' },
  }),
}));

describe('provider status page', () => {
  beforeEach(() => {
    runtime.listProviders.mockReset();
  });

  it('shows registration and identity without retired verification evidence', async () => {
    runtime.listProviders.mockResolvedValue(statuses());
    render(<ProviderStatusView />);

    const table = await screen.findByRole('table', { name: '平台能力状态' });
    const youtube = within(table)
      .getByRole('heading', { name: 'YouTube' })
      .closest('tr');
    expect(youtube).toHaveTextContent('已接入');
    expect(youtube).toHaveTextContent('优先登录');
    expect(youtube).toHaveTextContent('单视频 · 音视频分离');
    const qqvideo = within(table)
      .getByRole('heading', { name: '腾讯视频' })
      .closest('tr');
    expect(qqvideo).toHaveTextContent('未开放');
    expect(qqvideo).toHaveTextContent('需要登录');
    expect(screen.queryByRole('button', { name: '验证详情' })).toBeNull();
    expect(screen.queryByText(/验证记录|完整分析|真实下载|会话/)).toBeNull();
  });

  it('keeps platform names and every status detail in the narrow-screen record', async () => {
    const data = statuses();
    data.items[0].user_action = '请在 Chrome 登录后重新解析。';
    runtime.listProviders.mockResolvedValue(data);
    render(<ProviderStatusView />);

    const table = await screen.findByRole('table', { name: '平台能力状态' });
    const heading = within(table).getByRole('heading', { name: 'YouTube' });
    const primaryCell = heading.closest('th');
    expect(primaryCell).toHaveAttribute('scope', 'row');
    expect(primaryCell).not.toHaveClass('max-w-0');
    expect(primaryCell).toHaveTextContent('youtube');
    expect(primaryCell).toHaveTextContent('已接入');
    expect(primaryCell).toHaveTextContent('优先登录');
    expect(primaryCell).toHaveTextContent('单视频 · 音视频分离');
    expect(primaryCell).toHaveTextContent('请在 Chrome 登录后重新解析。');
    expect(primaryCell?.querySelector('p')).not.toHaveClass('truncate');

    for (const cell of heading.closest('tr')?.querySelectorAll('td') ?? []) {
      expect(cell).toHaveClass('hidden', 'lg:table-cell');
    }
    const columns = table.querySelectorAll('thead th');
    expect(columns).toHaveLength(4);
    for (const column of Array.from(columns).slice(1)) {
      expect(column).toHaveClass('hidden', 'lg:table-cell');
    }
  });

  it('includes the fallback capability and guidance in a compact platform record', async () => {
    const data = statuses();
    data.items[0].capabilities = [];
    runtime.listProviders.mockResolvedValue(data);
    render(<ProviderStatusView />);

    const heading = await screen.findByRole('heading', { name: 'YouTube' });
    const primaryCell = heading.closest('th');
    expect(primaryCell).toHaveTextContent('暂无已登记能力');
    expect(primaryCell).toHaveTextContent('下载结果以实际文件为准。');
  });

  it('supports loading, safe error and retry states', async () => {
    const first = deferred<API.ProviderListResponse>();
    const refresh = deferred<API.ProviderListResponse>();
    runtime.listProviders
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(refresh.promise)
      .mockResolvedValueOnce(statuses());
    render(<ProviderStatusView />);

    expect(
      screen.getByRole('status', { name: '正在加载平台状态' }),
    ).toBeInTheDocument();
    const initialRefresh = screen.getByRole('button', {
      name: '正在刷新平台状态',
    });
    expect(initialRefresh).toBeDisabled();
    await act(async () => first.resolve(statuses()));
    expect(await screen.findByText('YouTube')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '刷新状态' }));
    expect(screen.getByText('YouTube')).toBeInTheDocument();
    expect(
      screen.queryByRole('status', { name: '正在加载平台状态' }),
    ).not.toBeInTheDocument();
    await act(async () => refresh.reject(new Error('状态服务暂不可用')));
    const refreshAlert = await screen.findByRole('alert');
    expect(refreshAlert).toHaveTextContent('平台状态刷新失败');
    expect(refreshAlert).toHaveTextContent('状态服务暂不可用');
    expect(screen.getByText('YouTube')).toBeInTheDocument();
    fireEvent.click(
      within(refreshAlert).getByRole('button', { name: '重新加载' }),
    );
    expect(await screen.findByText('哔哩哔哩')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText('平台状态刷新失败')).not.toBeInTheDocument(),
    );
    expect(runtime.listProviders).toHaveBeenCalledTimes(3);
  });

  it('uses the unified page error state for an initial load failure', async () => {
    runtime.listProviders.mockRejectedValue(new Error('状态服务暂不可用'));
    render(<ProviderStatusView />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveAttribute('data-slot', 'empty');
    expect(alert).toHaveTextContent('平台状态暂时不可用');
    expect(alert).toHaveTextContent(
      '我们暂时无法读取最新的平台状态，请稍后再试。',
    );
    expect(alert.querySelector('[data-slot="empty-content"]')).not.toBeNull();
    expect(
      within(alert).getByRole('button', { name: '重新加载' }),
    ).toBeInTheDocument();
  });

  it('filters the status list without duplicating diagnostic details', async () => {
    runtime.listProviders.mockResolvedValue(statuses());
    render(<ProviderStatusView />);

    await screen.findByRole('heading', { name: 'YouTube' });
    fireEvent.click(screen.getByRole('radio', { name: '已接入' }));

    expect(
      screen.queryByRole('heading', { name: '腾讯视频' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'TikTok' })).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: '哔哩哔哩' }),
    ).toBeInTheDocument();
  });

  it('selects the next status filter with the arrow keys', async () => {
    runtime.listProviders.mockResolvedValue(statuses());
    render(<ProviderStatusView />);

    await screen.findByRole('heading', { name: 'YouTube' });
    const availableFilter = screen.getByRole('radio', {
      name: '已接入',
    });
    fireEvent.click(availableFilter);
    act(() => {
      availableFilter.focus();
    });
    fireEvent.keyDown(availableFilter, { key: 'ArrowRight' });

    expect(screen.getByRole('radio', { name: '未开放' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    expect(
      screen.queryByRole('heading', { name: 'TikTok' }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: '腾讯视频' }),
    ).toBeInTheDocument();

    const attentionFilter = screen.getByRole('radio', { name: '未开放' });
    act(() => {
      attentionFilter.focus();
    });
    fireEvent.keyDown(attentionFilter, { key: 'ArrowRight' });
    expect(screen.getByRole('radio', { name: '全部' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
  });

  it('paginates long status lists instead of rendering every diagnostic row', async () => {
    const template = statuses().items[1];
    runtime.listProviders.mockResolvedValue({
      items: Array.from({ length: 11 }, (_, index) => ({
        ...template,
        display_name: `平台 ${index + 1}`,
        key: `provider_${index + 1}`,
      })),
    });
    render(<ProviderStatusView />);

    await screen.findByRole('heading', { name: '平台 1' });
    expect(
      screen.queryByRole('heading', { name: '平台 11' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '下一页' }));
    expect(
      screen.getByRole('heading', { name: '平台 11' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('navigation', { name: '平台状态分页' }),
    ).toHaveTextContent('2 / 2');
  });
});

function statuses(): API.ProviderListResponse {
  const provider = {
    registered: true,
    extractor_exists: true,
    capabilities: ['single_video'],
    status: 'unknown',
    download_supported: true,
    user_action: null,
    hosts: [],
    host_suffixes: [],
    identity: 'none',
  } satisfies Omit<API.ProviderStatusResponse, 'key' | 'display_name'>;
  return {
    items: [
      {
        ...provider,
        key: 'youtube',
        display_name: 'YouTube',
        identity: 'prefer',
        capabilities: ['single_video', 'audio_video_split'],
      },
      { ...provider, key: 'tiktok', display_name: 'TikTok' },
      { ...provider, key: 'bilibili', display_name: '哔哩哔哩' },
      {
        ...provider,
        key: 'qqvideo',
        display_name: '腾讯视频',
        status: 'disabled',
        download_supported: false,
        identity: 'required',
      },
    ],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, reject, resolve };
}

vi.mock('@/lib/request-error', async (original) => ({
  ...(await original<typeof import('@/lib/request-error')>()),
  displayError: (reason: unknown) =>
    reason instanceof Error ? reason.message : '请求失败',
}));
vi.mock('@/api/providers', async (original) => ({
  ...(await original<typeof import('@/api/providers')>()),
  listProviders: runtime.listProviders,
}));
