import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { WorkspaceHome } from '@/components/intake/workspace-home';
import { TooltipProvider } from '@/components/ui/tooltip';
import { job } from '../fixtures/download-fixtures';
import { render } from '../helpers/query-render';

const runtime = vi.hoisted(() => ({
  providers: {
    data: null as API.ProviderListResponse | null,
    loading: false,
    error: null as string | null,
  },
  history: {
    data: null as API.DownloadHistoryResponse | null,
    loading: false,
    error: null as string | null,
  },
  historyHook: vi.fn(),
}));
vi.mock('@/components/providers/use-provider-statuses', () => ({
  useProviderStatuses: () => runtime.providers,
}));
vi.mock('@/components/downloads/use-download-history', () => ({
  useDownloadHistory: (params: unknown) => {
    runtime.historyHook(params);
    return { ...runtime.history, retry: vi.fn() };
  },
}));

vi.mock('@/components/auth/auth-provider', async (importOriginal) => ({
  ...(await importOriginal()),
  useAuth: () => ({ user: { id: 'intent-test-owner', role: 'user' } }),
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

describe('WorkspaceHome', () => {
  beforeEach(() => {
    runtime.providers = { data: null, loading: false, error: null };
    runtime.history = { data: null, loading: false, error: null };
    runtime.historyHook.mockClear();
  });
  it('shows the direct content intake instead of a workspace explainer', () => {
    render(
      <TooltipProvider>
        <WorkspaceHome />
      </TooltipProvider>,
    );

    expect(screen.getByLabelText('公开视频地址')).toBeInTheDocument();
    expect(
      screen.getByRole('tablist', { name: '选择内容来源' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '链接下载' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '本地视频' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '剧本文档' })).toBeInTheDocument();
    expect(
      screen.queryByRole('link', { name: '新建下载' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('选择素材，')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看平台状态' })).toHaveAttribute(
      'href',
      '/providers',
    );
    expect(
      screen.queryByText('平台身份来自你的 Chrome'),
    ).not.toBeInTheDocument();
    expect(runtime.historyHook).toHaveBeenCalledWith({ page: 1, page_size: 4 });
  });
  it('shows only enabled provider names, capped at five', () => {
    runtime.providers.data = {
      items: [
        'YouTube',
        '哔哩哔哩',
        '抖音',
        'TikTok',
        'X',
        '视频号',
        '未启用',
      ].map((display_name, index) => ({
        key: `provider-${index}`,
        display_name,
        registered: true,
        extractor_exists: true,
        download_supported: index < 6,
        status: index < 6 ? 'unknown' : 'disabled',
        capabilities: [],
        hosts: [],
        host_suffixes: [],
        identity: 'none',
        user_action: null,
      })),
    };
    render(
      <TooltipProvider>
        <WorkspaceHome />
      </TooltipProvider>,
    );
    expect(
      screen.getByText(
        /支持 YouTube、哔哩哔哩、抖音、TikTok、X 等平台的公开内容/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/视频号|未启用/)).not.toBeInTheDocument();
  });

  it.each(['loading', 'error'] as const)(
    'keeps the platform status link during provider %s',
    (kind) => {
      runtime.providers.loading = kind === 'loading';
      runtime.providers.error = kind === 'error' ? '暂不可用' : null;
      render(
        <TooltipProvider>
          <WorkspaceHome />
        </TooltipProvider>,
      );
      expect(screen.getByText(/支持多个平台的公开内容/)).toBeInTheDocument();
      expect(
        screen.getByRole('link', { name: '查看平台状态' }),
      ).toBeInTheDocument();
    },
  );

  it('renders recent covers with status, source and time, keeping active progress', () => {
    runtime.history.data = {
      items: ['running', 'succeeded', 'failed', 'queued'].map(
        (status, index) => ({
          ...job(status as API.DownloadStatus),
          id: `recent-${index}`,
          title: `下载 ${index}`,
          format_name: '1080P MP4',
        }),
      ),
      page: 1,
      page_size: 4,
      total: 4,
      summary: { total: 4, succeeded: 1, failed: 1, active: 2 },
    };
    render(
      <TooltipProvider>
        <WorkspaceHome />
      </TooltipProvider>,
    );
    expect(
      document.querySelectorAll('[data-slot="recent-download-cover"]'),
    ).toHaveLength(4);
    expect(
      screen.getByRole('progressbar', { name: '下载 0 下载进度' }),
    ).toHaveAttribute('aria-valuenow', '35');
    expect(screen.getByRole('link', { name: /下载 1/ })).toHaveAttribute(
      'href',
      '/downloads/detail?jobId=recent-1',
    );
    expect(document.querySelectorAll('time')).toHaveLength(4);
  });
});
