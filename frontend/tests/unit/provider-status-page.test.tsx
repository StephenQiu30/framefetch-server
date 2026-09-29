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

  it('distinguishes registration, verification and availability', async () => {
    runtime.listProviders.mockResolvedValue(statuses());
    render(<ProviderStatusView />);

    expect(
      await screen.findByRole('heading', { level: 1, name: '平台状态' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('banner')).toHaveAttribute(
      'data-slot',
      'page-header',
    );
    const table = await screen.findByRole('table', { name: '平台能力状态' });
    const youtube = within(table)
      .getByRole('heading', { name: 'YouTube' })
      .closest('tr');
    expect(youtube).not.toBeNull();
    expect(youtube).toHaveTextContent('已接入 · 当前不可用');
    const capabilities = within(youtube as HTMLElement).getByText(
      '单视频 · 音视频分离',
    );
    expect(capabilities).not.toHaveAttribute('data-slot', 'badge');
    expect(youtube).not.toHaveTextContent('状态检查：暂无当前版本记录');
    fireEvent.click(
      within(youtube as HTMLElement).getByRole('button', {
        name: '验证详情',
      }),
    );
    const youtubeDetails = screen.getByText('仅匿名公开内容').closest('tr');
    expect(youtubeDetails).not.toBeNull();
    expect(youtubeDetails).toHaveTextContent('状态检查：暂无当前版本记录');
    expect(youtubeDetails).toHaveTextContent('真实下载：暂无当前版本证据');
    expect(youtubeDetails).toHaveTextContent('完整分析：暂无当前版本证据');
    expect(youtubeDetails).not.toHaveTextContent('Cookie 版本');

    const tiktok = within(table)
      .getByRole('heading', { name: 'TikTok' })
      .closest('tr');
    expect(tiktok).not.toBeNull();
    expect(tiktok).toHaveTextContent('当前可用');
    fireEvent.click(
      within(tiktok as HTMLElement).getByRole('button', {
        name: '验证详情',
      }),
    );
    const tiktokDetails = screen
      .getByText('公开样本下载：可用 · 2026年8月29日')
      .closest('tr');
    expect(tiktokDetails).not.toBeNull();
    expect(tiktokDetails).toHaveTextContent('仅匿名公开内容');

    const bilibili = within(table)
      .getByRole('heading', { name: '哔哩哔哩' })
      .closest('tr');
    expect(bilibili).not.toBeNull();
    expect(bilibili).toHaveTextContent('当前可用');
    fireEvent.click(
      within(bilibili as HTMLElement).getByRole('button', {
        name: '验证详情',
      }),
    );
    const bilibiliDetails = screen
      .getByText(/状态检查：2026年8月11日/)
      .closest('tr');
    expect(bilibiliDetails).not.toBeNull();
    expect(bilibiliDetails).toHaveTextContent('仅匿名公开内容');
    expect(bilibiliDetails).toHaveTextContent(
      '公开样本下载：可用 · 2026年8月9日',
    );
    expect(bilibiliDetails).toHaveTextContent('2026年8月10日');

    const hongguo = within(table)
      .getByRole('heading', { name: '红果短剧官方分享' })
      .closest('tr');
    expect(hongguo).not.toBeNull();
    expect(hongguo).toHaveTextContent('当前可用');
    expect(hongguo).toHaveTextContent('下载解析器已部署');
    fireEvent.click(
      within(hongguo as HTMLElement).getByRole('button', {
        name: '验证详情',
      }),
    );
    expect(screen.getByText(/官方分享链接当前单集/)).toBeInTheDocument();

    const qqvideo = within(table)
      .getByRole('heading', { name: '腾讯视频' })
      .closest('tr');
    expect(qqvideo).not.toBeNull();
    expect(qqvideo).toHaveTextContent('已停用');
    expect(qqvideo).toHaveTextContent('仅识别链接，未开放下载');
    fireEvent.click(
      within(qqvideo as HTMLElement).getByRole('button', {
        name: '验证详情',
      }),
    );
    const qqvideoDetails = screen
      .getByText(/支持识别腾讯视频单视频链接/)
      .closest('tr');
    expect(qqvideoDetails).not.toBeNull();
    expect(qqvideoDetails).toHaveTextContent('当前未开放');
    expect(qqvideoDetails).toHaveTextContent('VIP、付费及 DRM 内容不提供下载');
    expect(qqvideoDetails).not.toHaveTextContent('运维');

    const vimeo = within(table)
      .getByRole('heading', { name: 'Vimeo' })
      .closest('tr');
    expect(vimeo).not.toBeNull();
    expect(vimeo).toHaveTextContent('已接入 · 待重新验证');
    expect(
      within(vimeo as HTMLElement).getByText('已接入 · 待重新验证'),
    ).toHaveAttribute('data-variant', 'secondary');
  });

  it('keeps media sample evidence separate from current route availability', async () => {
    const base = statuses().items[0];
    runtime.listProviders.mockResolvedValue({
      items: [
        {
          ...base,
          key: 'douyin',
          display_name: '抖音',
          status: 'unknown',
          access_state: 'operator_probe',
          download_available: true,
        },
        {
          ...base,
          key: 'xiaohongshu',
          display_name: '小红书',
          status: 'degraded',
          access_state: 'degraded',
          download_available: true,
        },
      ],
    });
    render(<ProviderStatusView />);

    const douyin = (
      await screen.findByRole('heading', { name: '抖音' })
    ).closest('tr');
    expect(douyin).toHaveTextContent('近期媒体样本通过');
    expect(douyin).toHaveTextContent('受控线路待验证');
    expect(
      within(douyin as HTMLElement).getByText('近期媒体样本通过'),
    ).toHaveAttribute('data-variant', 'secondary');
    const xiaohongshu = screen
      .getByRole('heading', { name: '小红书' })
      .closest('tr');
    expect(xiaohongshu).toHaveTextContent('支持下载 · 当前降级');
    expect(
      within(xiaohongshu as HTMLElement).getByText('支持下载 · 当前降级'),
    ).toHaveAttribute('data-variant', 'secondary');
    expect(screen.queryByText(/0 个当前可用/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('radio', { name: '当前可用' }));
    expect(
      screen.queryByRole('heading', { name: '抖音' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: '需关注' }));
    expect(screen.getByRole('heading', { name: '抖音' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '小红书' })).toBeInTheDocument();
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

  it('labels operator-only evidence without calling it a public sample', async () => {
    const operatorOnly = statuses().items[1];
    runtime.listProviders.mockResolvedValue({
      items: [
        {
          ...operatorOnly,
          key: 'operator-only',
          display_name: '受控线路示例',
          access_modes: ['operator_managed'],
        },
      ],
    });
    render(<ProviderStatusView />);

    const provider = (
      await screen.findByRole('heading', { name: '受控线路示例' })
    ).closest('tr');
    expect(provider).not.toBeNull();
    fireEvent.click(
      within(provider as HTMLElement).getByRole('button', {
        name: '验证详情',
      }),
    );
    const details = screen.getByText(/受控线路样本下载：可用/).closest('tr');
    expect(details).not.toBeNull();
    expect(details).not.toHaveTextContent('公开样本下载');
  });

  it('filters the status list without duplicating diagnostic details', async () => {
    runtime.listProviders.mockResolvedValue(statuses());
    render(<ProviderStatusView />);

    await screen.findByRole('heading', { name: 'YouTube' });
    fireEvent.click(screen.getByRole('radio', { name: '当前可用' }));

    expect(
      screen.queryByRole('heading', { name: 'YouTube' }),
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
      name: '当前可用',
    });
    fireEvent.click(availableFilter);
    act(() => {
      availableFilter.focus();
    });
    fireEvent.keyDown(availableFilter, { key: 'ArrowRight' });

    expect(screen.getByRole('radio', { name: '需关注' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    expect(
      screen.queryByRole('heading', { name: 'TikTok' }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'YouTube' }),
    ).toBeInTheDocument();

    const attentionFilter = screen.getByRole('radio', { name: '需关注' });
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
  return {
    items: [
      {
        key: 'youtube',
        access_policies: [],
        default_access_policy_id: null,
        evidence_state: 'missing',
        hosts: [],
        host_suffixes: [],
        display_name: 'YouTube',
        registered: true,
        extractor_exists: true,
        capabilities: ['single_video', 'audio_video_split'],
        access_modes: ['anonymous'],
        access_state: 'authorization_required',
        status: 'access_required',
        last_checked_at: null,
        last_check_succeeded: null,
        download_supported: true,
        download_available: false,
        last_media_verified_at: null,
        last_verified_at: null,
        user_action:
          '该平台当前要求额外授权或验证；请稍后重试，或上传你拥有或已获授权的文件。',
      },
      {
        key: 'tiktok',
        access_policies: [],
        default_access_policy_id: null,
        evidence_state: 'fresh',
        hosts: [],
        host_suffixes: [],
        display_name: 'TikTok',
        registered: true,
        extractor_exists: true,
        capabilities: ['single_video', 'short_video'],
        access_modes: ['anonymous'],
        access_state: 'public_ready',
        status: 'verified',
        last_checked_at: '2026-08-29T03:33:50Z',
        last_check_succeeded: true,
        download_supported: true,
        download_available: true,
        last_media_verified_at: '2026-08-29T03:33:50Z',
        last_verified_at: null,
        user_action: null,
      },
      {
        key: 'bilibili',
        access_policies: [],
        default_access_policy_id: null,
        evidence_state: 'fresh',
        hosts: [],
        host_suffixes: [],
        display_name: '哔哩哔哩',
        registered: true,
        extractor_exists: true,
        capabilities: ['single_video'],
        access_modes: ['anonymous'],
        access_state: 'public_ready',
        status: 'verified',
        last_checked_at: '2026-08-11T03:30:00Z',
        last_check_succeeded: true,
        download_supported: true,
        download_available: true,
        last_media_verified_at: '2026-08-09T00:00:00Z',
        last_verified_at: '2026-08-10T00:00:00Z',
        user_action: null,
      },
      {
        key: 'hongguo_web',
        access_policies: [],
        default_access_policy_id: null,
        evidence_state: 'fresh',
        hosts: [],
        host_suffixes: [],
        display_name: '红果短剧官方分享',
        registered: true,
        extractor_exists: true,
        capabilities: ['single_video'],
        access_modes: ['anonymous'],
        access_state: 'public_ready',
        status: 'unknown',
        last_checked_at: '2026-08-11T03:30:00Z',
        last_check_succeeded: true,
        download_supported: true,
        download_available: true,
        last_media_verified_at: '2026-08-11T03:30:00Z',
        last_verified_at: null,
        user_action:
          '已接入红果官方分享链接当前单集；不支持 App 受保护媒体、全集抓取或批量下载。',
      },
      {
        key: 'qqvideo',
        access_policies: [],
        default_access_policy_id: null,
        evidence_state: 'missing',
        hosts: [],
        host_suffixes: [],
        display_name: '腾讯视频',
        registered: true,
        extractor_exists: true,
        capabilities: ['single_video'],
        access_modes: [],
        access_state: 'disabled',
        status: 'disabled',
        last_checked_at: null,
        last_check_succeeded: null,
        download_supported: false,
        download_available: false,
        last_media_verified_at: null,
        last_verified_at: null,
        user_action:
          '支持识别腾讯视频单视频链接并引导官方播放；消费端私有接口、VIP、付费及 DRM 内容不提供下载。自有媒资请通过腾讯云 VOD 官方导出或上传明文文件。',
      },
      {
        key: 'vimeo',
        access_policies: [],
        default_access_policy_id: null,
        evidence_state: 'stale',
        hosts: [],
        host_suffixes: [],
        display_name: 'Vimeo',
        registered: true,
        extractor_exists: true,
        capabilities: ['single_video'],
        access_modes: ['anonymous'],
        access_state: 'public_probe',
        status: 'verified',
        last_checked_at: '2026-08-01T00:00:00Z',
        last_check_succeeded: true,
        download_supported: true,
        download_available: false,
        last_media_verified_at: '2026-08-01T00:00:00Z',
        last_verified_at: null,
        user_action: null,
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
