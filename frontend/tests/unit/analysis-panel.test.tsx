import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AnalysisPanel from '@/components/analysis/analysis-panel';
import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import AnalysisResultView from '@/components/analysis/analysis-result-view';
import { httpClient } from '@/lib/request';
import { ApiError } from '@/lib/request-error';
import {
  analysisJob,
  analysisResult,
  analysisSkills,
  articleResult,
} from '../fixtures/analysis-fixtures';
import { job } from '../fixtures/download-fixtures';
import { stubCryptoUuids } from '../helpers/crypto';
import {
  httpRequests,
  mockHttpError,
  mockHttpResponses,
} from '../helpers/http';
import { renderWithToasts as render } from '../helpers/query-render';
import { degradeLatestSocket, emitTaskUpdate } from '../helpers/websocket';

describe('AnalysisPanel', () => {
  afterEach(() => {
    document.querySelectorAll('[data-framefetch-download]').forEach((frame) => {
      frame.remove();
    });
  });
  beforeEach(() => {
    mockHttpResponses(null, analysisSkills);
  });

  it('does not offer a new analysis while the existing record is unknown', async () => {
    vi.mocked(httpClient.request).mockReset();
    mockHttpError(
      new ApiError(503, 'analysis_unavailable', 'Unavailable', 'Unavailable'),
    );
    render(<AnalysisPanel downloadId={job().id} />);
    expect(
      screen.queryByRole('button', { name: '开始 AI 分析' }),
    ).not.toBeInTheDocument();
    await screen.findByText('暂时无法读取分析记录');
    expect(
      screen.queryByRole('button', { name: '开始 AI 分析' }),
    ).not.toBeInTheDocument();
    mockHttpResponses(analysisJob('succeeded'));
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    await screen.findByRole('heading', { name: analysisResult.title });
  });

  it('keeps retry errors visible beside the completed result', async () => {
    vi.mocked(httpClient.request).mockReset();
    mockHttpResponses(analysisJob('succeeded'));
    mockHttpError(
      new ApiError(503, 'analysis_unavailable', 'Unavailable', 'Unavailable'),
    );
    render(<AnalysisPanel downloadId={job().id} />);
    fireEvent.click(await screen.findByRole('button', { name: '重新分析' }));
    expect(await screen.findByText('操作未完成')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: analysisResult.title }),
    ).toBeInTheDocument();
  });

  it.each(['succeeded', 'running'] as const)(
    'routes %s report downloads outside the current document',
    async (status) => {
      vi.mocked(httpClient.request).mockReset();
      mockHttpResponses({
        ...analysisJob('succeeded'),
        status,
      });
      render(<AnalysisPanel downloadId={job().id} />);
      const link = await screen.findByRole('link', {
        name: status === 'succeeded' ? '导出 DOCX' : '下载上一版 DOCX',
      });
      const blob = new Blob(['report'], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      });
      mockHttpResponses(blob);
      const createUrl = vi
        .spyOn(URL, 'createObjectURL')
        .mockReturnValue('blob:report-test');
      const click = vi
        .spyOn(HTMLAnchorElement.prototype, 'click')
        .mockImplementation(() => {});
      expect(!fireEvent.click(link)).toBe(true);
      await waitFor(() => expect(createUrl).toHaveBeenCalledWith(blob));
      expect(httpRequests().at(-1)).toMatchObject({
        url: `/api/analyses/${analysisJob('succeeded').id}/report.docx`,
        responseType: 'blob',
      });
      expect(click).toHaveBeenCalledOnce();
      createUrl.mockRestore();
      click.mockRestore();
    },
  );

  it('preserves the completed report when deletion fails', async () => {
    vi.mocked(httpClient.request).mockReset();
    mockHttpResponses(analysisJob('succeeded'));
    mockHttpError(
      new ApiError(503, 'analysis_unavailable', 'Unavailable', 'Unavailable'),
    );
    render(<AnalysisPanel downloadId={job().id} />);
    fireEvent.click(await screen.findByRole('button', { name: '删除分析' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认删除' }));
    expect(await screen.findByText('操作未完成')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: analysisResult.title }),
    ).toBeInTheDocument();
  });

  it.each(['succeeded', 'running'] as const)(
    'connects article evidence in the %s branch',
    async (status) => {
      vi.mocked(httpClient.request).mockReset();
      mockHttpResponses({
        ...analysisJob('succeeded'),
        status,
        result: articleResult,
        skill_id: 'video-to-article',
        result_contract: 'video-article',
      });
      const seek = vi.fn();
      render(<AnalysisPanel downloadId={job().id} onSelectTime={seek} />);
      fireEvent.mouseDown(
        await screen.findByRole('tab', { name: '回查依据' }),
        {
          button: 0,
          ctrlKey: false,
        },
      );
      fireEvent.click(
        await screen.findByRole('button', { name: '查看视频依据 0:30–1:02' }),
      );
      expect(seek).toHaveBeenCalledWith(30_000);
    },
  );

  it('explains why article evidence cannot be replayed after media cleanup', async () => {
    vi.mocked(httpClient.request).mockReset();
    mockHttpResponses({
      ...analysisJob('succeeded'),
      result: articleResult,
    });
    render(
      <AnalysisPanel
        downloadId={job().id}
        playbackUnavailableReason="原视频文件已清理"
      />,
    );
    fireEvent.mouseDown(await screen.findByRole('tab', { name: '回查依据' }), {
      button: 0,
      ctrlKey: false,
    });
    expect(
      await screen.findByRole('button', { name: '查看视频依据 0:30–1:02' }),
    ).toBeDisabled();
    expect(screen.getByText('原视频文件已清理')).toBeInTheDocument();
  });

  it.each(['succeeded', 'running'] as const)(
    'connects evidence from the %s result to playback',
    async (status) => {
      vi.mocked(httpClient.request).mockReset();
      mockHttpResponses({
        ...analysisJob('succeeded'),
        status,
      });
      const seek = vi.fn();
      render(<AnalysisPanel downloadId={job().id} onSelectTime={seek} />);
      const time = await screen.findByRole('button', { name: '0:30' });
      expect(time).toBeEnabled();
      fireEvent.click(time);
      expect(seek).toHaveBeenCalledWith(30_000);
    },
  );

  it('loads analysis skills and exposes an editable prompt', async () => {
    render(<AnalysisPanel downloadId={job().id} />);
    expect(
      await screen.findByRole('heading', { name: 'AI 智能分析' }),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText('分析 Skill')).toHaveAttribute(
      'id',
      'analysis-skill',
    );
    expect(screen.getByLabelText('输出语言')).toHaveAttribute(
      'id',
      'analysis-language',
    );
    await waitFor(() =>
      expect(screen.getByLabelText('分析提示词')).toHaveValue(
        '逐镜头分析画面、叙事作用和高光价值。',
      ),
    );
    expect(screen.getByText('导演拉片')).toBeInTheDocument();
    expect(
      screen.getByText(/完整视频文件会交给本机 Agent/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /实际查看的画面帧、任务指令和必要上下文会发送到所选云端模型/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/不会把原始视频容器直接上传给模型服务/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始 AI 分析' })).toBeEnabled();
  });

  it('restores the latest persisted analysis after a page load', async () => {
    vi.mocked(httpClient.request).mockReset();
    mockHttpResponses(analysisJob('succeeded'));

    render(<AnalysisPanel downloadId={job().id} />);

    expect(await screen.findByText('已完成')).toBeInTheDocument();
    expect(screen.getByText('第 1 次执行')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: analysisResult.title }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '导出 DOCX' })).toHaveAttribute(
      'href',
      '#report-docx',
    );
    expect(screen.getByText(/原始文件持久保存/)).toBeInTheDocument();
  });

  it('shows an explicit unavailable state instead of stale report links', async () => {
    vi.mocked(httpClient.request).mockReset();
    const available = analysisJob('succeeded');
    if (!available.report) throw new Error('report fixture is required');
    const unavailable = {
      ...available,
      report: { ...available.report, artifacts: [] },
    };
    mockHttpResponses(unavailable);

    render(<AnalysisPanel downloadId={job().id} />);

    expect(
      await screen.findByText('报告已清理或暂时不可用'),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('link', { name: '导出 DOCX' }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/分析结果仍可查看，但报告文件已被清理或暂时不可读取/),
    ).toBeInTheDocument();
  });

  it('deletes an analysis only after accessible confirmation', async () => {
    vi.mocked(httpClient.request).mockReset();
    const succeeded = analysisJob('succeeded');
    mockHttpResponses(succeeded, undefined, analysisSkills);
    render(<AnalysisPanel downloadId={job().id} />);

    const trigger = await screen.findByRole('button', { name: '删除分析' });
    fireEvent.click(trigger);
    expect(
      await screen.findByRole('alertdialog', { name: '删除分析与报告？' }),
    ).toHaveTextContent('此操作不可撤销');
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }));

    await waitFor(() =>
      expect(screen.queryByText(analysisResult.title)).not.toBeInTheDocument(),
    );
    expect(httpRequests().some((request) => request.method === 'DELETE')).toBe(
      true,
    );
  });

  it('creates, receives WebSocket state and renders a structured result', async () => {
    mockHttpResponses(analysisJob('running'), analysisJob('succeeded'));
    stubCryptoUuids('11111111-1111-4111-8111-111111111111');
    render(<AnalysisPanel downloadId={job().id} pollIntervalMs={5} />);

    fireEvent.change(await screen.findByLabelText('分析提示词'), {
      target: { value: '重点识别产品功能演示。' },
    });
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: '开始 AI 分析' }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: '开始 AI 分析' }));
    await screen.findByText('正在分析');
    emitTaskUpdate('analysis', analysisJob('running').id, 2);
    expect(await screen.findByText('已完成')).toBeInTheDocument();
    expect(screen.getByText('第 1 次执行')).toBeInTheDocument();
    expect(httpRequests()[2]?.data).toEqual({
      skill_id: 'director-breakdown',
      output_language: 'zh-CN',
      custom_prompt: '重点识别产品功能演示。',
    });
    expect(screen.getByText('可靠的视频处理流水线')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: '视觉摘要' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '分镜' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '场景' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '高光' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '资产' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '报告预览' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '导出 DOCX' })).toHaveAttribute(
      'href',
      '#report-docx',
    );
    expect(screen.getByRole('link', { name: '导出 Markdown' })).toHaveAttribute(
      'href',
      '#report-md',
    );

    const reportTab = screen.getByRole('tab', { name: '报告预览' });
    fireEvent.mouseDown(reportTab, { button: 0, ctrlKey: false });
    fireEvent.click(reportTab);
    const preview = await screen.findByLabelText('Markdown 分析报告预览');
    expect(within(preview).getByText('一、基础信息')).toBeInTheDocument();
  });

  it('polls repeatedly while realtime synchronization is degraded', async () => {
    vi.useFakeTimers();
    try {
      mockHttpResponses(
        analysisJob('running'),
        analysisJob('running'),
        analysisJob('succeeded'),
      );
      stubCryptoUuids('11111111-1111-4111-8111-111111111111');
      render(<AnalysisPanel downloadId={job().id} pollIntervalMs={5} />);
      await vi.waitFor(() =>
        expect(
          screen.getByRole('button', { name: '开始 AI 分析' }),
        ).toBeEnabled(),
      );
      fireEvent.click(screen.getByRole('button', { name: '开始 AI 分析' }));
      await vi.waitFor(() =>
        expect(screen.getByText('正在分析')).toBeInTheDocument(),
      );

      await act(async () => {
        await Promise.resolve();
        degradeLatestSocket();
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_001);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_001);
      });

      const refreshes = httpRequests().filter((request) =>
        (request.url ?? '').includes(`/analyses/${analysisJob('running').id}`),
      );
      expect(refreshes).toHaveLength(2);
      expect(screen.getByText('已完成')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('renders Markdown without executable HTML or outbound links', () => {
    render(
      <AnalysisReportPreview
        markdown={
          '# 报告\n\n<script>x</script>\n\n[外链](https://invalid.example)'
        }
      />,
    );

    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(document.querySelector('script')).not.toBeInTheDocument();
    expect(screen.getByText('外链')).toBeInTheDocument();
  });

  it('exposes shot timestamps for a video player integration', () => {
    const onSelectTime = vi.fn();
    render(
      <AnalysisResultView
        onSelectTime={onSelectTime}
        result={analysisResult}
      />,
    );

    fireEvent.click(screen.getAllByRole('button', { name: '0:30' })[0]);
    expect(onSelectTime).toHaveBeenCalledWith(30_000);
  });

  it('renders empty highlight and asset states', async () => {
    render(
      <AnalysisResultView
        result={{ ...analysisResult, assets: [], highlights: [] }}
      />,
    );

    const highlightsTab = screen.getByRole('tab', { name: '高光' });
    fireEvent.mouseDown(highlightsTab, { button: 0, ctrlKey: false });
    fireEvent.click(highlightsTab);
    expect(
      await screen.findByText('未识别出独立视觉高光。'),
    ).toBeInTheDocument();
    const assetsTab = screen.getByRole('tab', { name: '资产' });
    fireEvent.mouseDown(assetsTab, { button: 0, ctrlKey: false });
    fireEvent.click(assetsTab);
    expect(
      await screen.findByText('未识别出可复用的视觉资产。'),
    ).toBeInTheDocument();
  });

  it('cancels an active analysis task', async () => {
    mockHttpResponses(analysisJob('running'), analysisJob('cancelled'));
    stubCryptoUuids('11111111-1111-4111-8111-111111111111');
    render(<AnalysisPanel downloadId={job().id} pollIntervalMs={60_000} />);

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: '开始 AI 分析' }),
      ).toBeEnabled(),
    );

    fireEvent.click(
      await screen.findByRole('button', { name: '开始 AI 分析' }),
    );
    const trigger = await screen.findByRole('button', { name: '取消分析' });
    fireEvent.click(trigger);

    expect(
      await screen.findByRole('alertdialog', {
        name: '取消当前分析任务？',
      }),
    ).toHaveTextContent('确认后将停止当前分析。你之后仍可重新发起分析任务。');
    expect(httpRequests()).toHaveLength(3);

    const keepAnalyzing = screen.getByRole('button', { name: '继续分析' });
    await waitFor(() => expect(keepAnalyzing).toHaveFocus());
    fireEvent.click(keepAnalyzing);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(httpRequests()).toHaveLength(3);

    fireEvent.click(trigger);
    fireEvent.click(
      await screen.findByRole('button', { name: '确认取消分析' }),
    );
    expect(await screen.findByText('分析已取消')).toBeInTheDocument();
    expect(httpRequests()[3]?.url).toContain('/cancel');
  });

  it('retries the same analysis id with an idempotency key', async () => {
    const failed = analysisJob('failed');
    const retried = {
      ...analysisJob('queued'),
      id: failed.id,
      run_id: '66666666-6666-4666-8666-666666666666',
      run_no: 2,
      run_trigger: 'manual_retry',
      version: failed.version + 1,
    } satisfies API.AnalysisResponse;
    mockHttpResponses(failed, retried);
    stubCryptoUuids('33333333-3333-4333-8333-333333333333');
    render(<AnalysisPanel downloadId={job().id} pollIntervalMs={60_000} />);

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: '开始 AI 分析' }),
      ).toBeEnabled(),
    );

    fireEvent.click(
      await screen.findByRole('button', { name: '开始 AI 分析' }),
    );
    fireEvent.click(await screen.findByRole('button', { name: '重试分析' }));

    expect(await screen.findByText(/第 2 次执行/)).toBeInTheDocument();
    const retryRequest = httpRequests()[3];
    expect(retryRequest?.url).toContain(`/analyses/${failed.id}/retry`);
    expect(retryRequest?.headers?.['Idempotency-Key']).toBe(
      '33333333-3333-4333-8333-333333333333',
    );
    expect(retried.id).toBe(failed.id);
  });

  it('shows a Chinese message for a failed analysis', async () => {
    mockHttpResponses(analysisJob('failed'));
    stubCryptoUuids('11111111-1111-4111-8111-111111111111');
    render(<AnalysisPanel downloadId={job().id} pollIntervalMs={60_000} />);

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: '开始 AI 分析' }),
      ).toBeEnabled(),
    );

    fireEvent.click(
      await screen.findByRole('button', { name: '开始 AI 分析' }),
    );
    expect(
      await screen.findByText('AI 分析执行失败，请稍后重试。'),
    ).toBeInTheDocument();
    expect(screen.queryByText('analysis_cli_failed')).not.toBeInTheDocument();
  });

  it('shows safe creation errors', async () => {
    mockHttpError(
      new ApiError(
        503,
        'analysis_unavailable',
        '服务不可用',
        'AI 分析服务暂时不可用',
      ),
    );
    render(<AnalysisPanel downloadId={job().id} />);
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: '开始 AI 分析' }),
      ).toBeEnabled(),
    );
    fireEvent.click(
      await screen.findByRole('button', { name: '开始 AI 分析' }),
    );
    expect(
      await screen.findByText('AI 分析服务暂时不可用，请稍后重试。'),
    ).toBeInTheDocument();
  });
});
