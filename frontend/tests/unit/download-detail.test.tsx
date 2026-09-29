import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DownloadJobView from '@/components/downloads/download-job-view';
import { httpClient } from '@/lib/request';
import { ApiError } from '@/lib/request-error';
import { analysisSkills } from '../fixtures/analysis-fixtures';
import {
  galleryJob,
  inspection,
  job,
  videoCollectionJob,
} from '../fixtures/download-fixtures';
import {
  httpRequests,
  mockHttpError,
  mockHttpResponses,
} from '../helpers/http';
import { renderWithToasts as render } from '../helpers/query-render';
import { emitTaskUpdate } from '../helpers/websocket';

const runtime = vi.hoisted(() => ({
  preview: {
    error: null as string | null,
    loading: false,
    reload: vi.fn(),
    reportPlaybackError: vi.fn(),
    source: 'data:video/mp4;base64,AAAA' as string | null,
  },
  push: vi.fn(),
  replace: vi.fn(),
}));

const signedVideoUrl = {
  filename: 'Owned video.mp4',
  url: 'about:blank#download',
  expires_at: '2026-08-06T10:05:00Z',
};

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: runtime.push, replace: runtime.replace }),
}));

vi.mock('@/components/downloads/use-video-preview-source', () => ({
  useVideoPreviewSource: () => runtime.preview,
}));

describe('DownloadJobView', () => {
  afterEach(() => {
    document
      .querySelectorAll('[data-framefetch-download]')
      .forEach((element) => {
        element.remove();
      });
  });

  beforeEach(() => {
    runtime.preview.error = null;
    runtime.preview.loading = false;
    runtime.preview.reload.mockReset();
    runtime.preview.source = 'data:video/mp4;base64,AAAA';
    runtime.push.mockReset();
    runtime.replace.mockReset();
    window.history.replaceState({}, '', '/downloads/detail/');
  });

  it('uses WebSocket state until the job succeeds and exposes analysis', async () => {
    mockHttpResponses(job('running'), job('succeeded'), null, analysisSkills);
    render(<DownloadJobView jobId={job().id} pollIntervalMs={5} />);

    expect((await screen.findAllByText('正在下载')).length).toBeGreaterThan(0);
    const mediaFrame = document.querySelector(
      '[data-slot="media-result-frame"]',
    );
    expect(mediaFrame).not.toBeNull();
    const cards = document.querySelectorAll(
      '[data-slot="media-result"] > [data-slot="card"]',
    );
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveClass('ring-0');
    expect(cards[1]).toHaveClass('ring-0');
    expect(cards[0].querySelector('[data-slot="media-result-frame"]')).toBe(
      mediaFrame,
    );
    expect(cards[1]).toContainElement(
      document.getElementById('download-status-title'),
    );
    emitTaskUpdate('download', job('running').id, 2);
    expect((await screen.findAllByText('服务端已完成')).length).toBeGreaterThan(
      0,
    );
    expect(
      screen.getByRole('heading', { level: 1, name: inspection.title }),
    ).toBeInTheDocument();
    expect(screen.getByText('持久保存')).toBeInTheDocument();
    expect(
      screen.getByRole('region', {
        name: `${inspection.title}视频预览`,
      }),
    ).toBeInTheDocument();
    const preview = screen.getByRole('region', {
      name: `${inspection.title}视频预览`,
    });
    expect(preview).toHaveStyle({ aspectRatio: 'auto' });
    expect(document.querySelector('[data-slot="media-result-frame"]')).toBe(
      mediaFrame,
    );
    expect(preview).toHaveClass('size-full');
    const frame = preview.closest('[data-slot="aspect-ratio"]');
    expect(frame).not.toBeNull();
    expect(frame?.parentElement).toHaveStyle({ paddingBottom: '56.25%' });
    expect(
      await screen.findByRole('heading', { name: 'AI 智能分析' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '返回上一步' })).toHaveAttribute(
      'href',
      '/history',
    );
  });

  it('cancels an active download', async () => {
    mockHttpResponses(job('running'), job('cancelled'));
    render(<DownloadJobView jobId={job().id} pollIntervalMs={60_000} />);

    const trigger = await screen.findByRole('button', { name: '取消任务' });
    fireEvent.click(trigger);

    const dialog = await screen.findByRole('alertdialog', {
      name: '取消当前下载任务？',
    });
    expect(dialog).toHaveTextContent(
      '确认后将停止当前下载。取消后可在当前页面重新下载。',
    );
    expect(httpRequests()).toHaveLength(1);

    const keepDownloading = screen.getByRole('button', { name: '继续下载' });
    await waitFor(() => expect(keepDownloading).toHaveFocus());
    fireEvent.click(keepDownloading);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(httpRequests()).toHaveLength(1);

    fireEvent.click(trigger);
    fireEvent.click(
      await screen.findByRole('button', { name: '确认取消下载' }),
    );
    expect((await screen.findAllByText('任务已取消')).length).toBeGreaterThan(
      0,
    );
    expect(httpRequests()[1]?.url).toBe(`/api/downloads/${job().id}/cancel`);
  });

  it('deletes the task and returns to download history', async () => {
    mockHttpResponses(job('succeeded'), null, analysisSkills, null);
    render(<DownloadJobView jobId={job().id} />);

    fireEvent.click(await screen.findByRole('button', { name: '删除任务' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认删除' }));

    await waitFor(() =>
      expect(runtime.replace).toHaveBeenCalledWith('/history'),
    );
    expect(httpRequests().at(-1)).toMatchObject({
      method: 'DELETE',
      url: `/api/downloads/${job().id}`,
    });
  });

  it.each(['failed', 'cancelled'] as const)(
    'creates a new download when a %s task is retried',
    async (status) => {
      const retried = {
        ...job('queued'),
        id: '44444444-4444-4444-8444-444444444444',
      };
      mockHttpResponses(job(status), retried);
      render(<DownloadJobView jobId={job().id} pollIntervalMs={60_000} />);

      fireEvent.click(await screen.findByRole('button', { name: '重新下载' }));

      await waitFor(() =>
        expect(runtime.push).toHaveBeenCalledWith(
          `/downloads/detail?jobId=${retried.id}`,
        ),
      );
      expect(httpRequests()[1]).toMatchObject({
        method: 'POST',
        url: `/api/downloads/${job().id}/retry`,
        headers: { 'Idempotency-Key': expect.any(String) },
      });
    },
  );

  it('shows a Chinese message for a failed download', async () => {
    mockHttpResponses(job('failed'));
    render(<DownloadJobView jobId={job().id} pollIntervalMs={60_000} />);

    expect(
      await screen.findByText('视频下载超时，请稍后重试。'),
    ).toBeInTheDocument();
    expect(screen.queryByText('download_timeout')).not.toBeInTheDocument();
  });

  it('turns media validation failures into a file recovery action', async () => {
    const failed = {
      ...job('failed'),
      error_code: 'media_validation_failed' as const,
      error_message: 'artifact digest does not match',
    };
    mockHttpResponses(failed);
    render(<DownloadJobView jobId={failed.id} pollIntervalMs={60_000} />);

    expect(
      await screen.findByRole('heading', { name: '文件校验未通过' }),
    ).toBeInTheDocument();
    expect(
      screen.getByText('下载文件内容校验失败，请重新获取下载源。'),
    ).toBeInTheDocument();
    expect(
      screen.queryByText('artifact digest does not match'),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '重新获取并下载' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        '下载并验证完成后，可继续生成视觉分镜、高光与资产目录。',
      ),
    ).not.toBeInTheDocument();
  });

  it('does not present a retry failure as a task read failure', async () => {
    mockHttpResponses(job('failed'));
    mockHttpError(
      new ApiError(
        503,
        'provider_verification_failed',
        'Unavailable',
        '暂时不可用',
      ),
    );
    render(<DownloadJobView jobId={job().id} pollIntervalMs={60_000} />);

    fireEvent.click(await screen.findByRole('button', { name: '重新下载' }));

    expect(await screen.findByText('操作未完成')).toBeInTheDocument();
    expect(screen.queryByText('无法读取下载任务')).not.toBeInTheDocument();
  });

  it('issues a short-lived URL for completed downloads', async () => {
    vi.mocked(httpClient.request).mockImplementation(async ({ url }) => {
      const data =
        url === `/api/downloads/${job().id}`
          ? job('succeeded')
          : url === `/api/downloads/${job().id}/analysis`
            ? null
            : url === '/api/analysis-skills'
              ? analysisSkills
              : url === `/api/downloads/${job().id}/download-url`
                ? signedVideoUrl
                : undefined;
      if (data === undefined) throw new Error(`Unexpected request: ${url}`);
      return { data: { code: 'ok', message: 'OK', data } } as never;
    });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});
    render(<DownloadJobView jobId={job().id} />);

    fireEvent.click(
      await screen.findByRole('button', { name: '获取视频文件' }),
    );
    await waitFor(() =>
      expect(
        document.querySelector<HTMLIFrameElement>(
          'iframe[data-framefetch-download]',
        ),
      ).toHaveAttribute('src', signedVideoUrl.url),
    );
    expect(click).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe('/downloads/detail/');
  });

  it('presents a completed image note as a ZIP instead of a video preview', async () => {
    mockHttpResponses(
      galleryJob('succeeded'),
      null,
      analysisSkills,
      signedVideoUrl,
    );
    render(<DownloadJobView jobId={galleryJob().id} />);

    expect(
      await screen.findByRole('heading', { name: '图集文件已就绪' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '获取图集 ZIP' }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('region', { name: `${galleryJob().title}视频预览` }),
    ).not.toBeInTheDocument();
  });

  it('presents a completed multi-video source as a ZIP', async () => {
    mockHttpResponses(
      videoCollectionJob('succeeded'),
      null,
      analysisSkills,
      signedVideoUrl,
    );
    render(<DownloadJobView jobId={videoCollectionJob().id} />);

    expect(
      await screen.findByRole('heading', { name: '视频合集文件已就绪' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '获取视频合集 ZIP' }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('region', {
        name: `${videoCollectionJob().title}视频预览`,
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { name: 'AI 智能分析' }),
    ).not.toBeInTheDocument();
  });

  it('offers a new download when a completed file has been cleaned', async () => {
    mockHttpResponses(
      { ...job('succeeded'), file_available: false },
      null,
      analysisSkills,
    );
    render(<DownloadJobView jobId={job().id} />);

    expect(
      await screen.findByRole('button', { name: '重新下载' }),
    ).toBeInTheDocument();
    expect(screen.getByText('视频文件已清理')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '获取视频文件' }),
    ).not.toBeInTheDocument();
  });

  it('offers to reload an unavailable preview', async () => {
    runtime.preview.error = '预览地址已失效。';
    runtime.preview.source = null;
    mockHttpResponses(job('succeeded'), null, analysisSkills);
    render(<DownloadJobView jobId={job().id} />);

    const warning = await screen.findByText('暂时无法预览视频');
    expect(warning).toBeInTheDocument();
    const frame = warning.closest('[data-slot="aspect-ratio"]');
    expect(frame).not.toBeNull();
    expect(frame?.parentElement).toHaveStyle({ paddingBottom: '56.25%' });
    fireEvent.click(screen.getByRole('button', { name: '重新加载预览' }));
    expect(runtime.preview.reload).toHaveBeenCalledOnce();
  });

  it('keeps the preview loading state in the shared media frame', async () => {
    runtime.preview.loading = true;
    runtime.preview.source = null;
    mockHttpResponses(job('succeeded'), null, analysisSkills);
    render(<DownloadJobView jobId={job().id} />);

    const loading = await screen.findByLabelText('正在准备视频预览');
    const frame = loading.closest('[data-slot="aspect-ratio"]');
    expect(frame).not.toBeNull();
    expect(frame?.parentElement).toHaveStyle({ paddingBottom: '56.25%' });
  });

  it('shows the declared source for an owned WeChat Channels import', async () => {
    runtime.preview.error = '预览不可用';
    runtime.preview.source = null;
    const imported = {
      ...job('succeeded'),
      duration_seconds: null,
      extractor_key: null,
      format: null,
      inspection_id: null,
      source_kind: 'browser_import' as const,
      source_label: '用户提供的视频号来源文件',
      title: null,
    };
    mockHttpResponses(imported, null, analysisSkills);
    render(<DownloadJobView jobId={imported.id} />);

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: '用户提供的视频号来源文件',
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText('用户提供的视频号来源文件 · 正在读取媒体信息'),
    ).toBeInTheDocument();
  });

  it('keeps a completed task usable after inspection metadata expires', async () => {
    mockHttpResponses(job('succeeded'), null, analysisSkills);
    render(<DownloadJobView jobId={job().id} />);

    await screen.findByRole('heading', { level: 1, name: inspection.title });
    expect(
      screen.queryByText(
        '原始媒体信息已过期，下载任务和已生成文件仍可继续使用。',
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: '视频文件已就绪' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('region', {
        name: `${inspection.title}视频预览`,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/1920×1080/)).toBeInTheDocument();
    expect(
      await screen.findByRole('heading', { name: 'AI 智能分析' }),
    ).toBeInTheDocument();
  });

  it('renders stable task errors without leaking details', async () => {
    mockHttpError(new ApiError(404, 'not_found', 'Not found', '任务不存在'));
    render(<DownloadJobView jobId={job().id} />);
    expect(
      await screen.findByText('任务或相关资源不存在，请返回下载记录确认。'),
    ).toBeInTheDocument();
  });
});
