import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import AnalysisDetailRoute from '@/components/analysis/analysis-detail-route';
import { httpClient } from '@/lib/request';
import { analysisJob } from '../fixtures/analysis-fixtures';
import { httpRequests } from '../helpers/http';
import { render } from '../helpers/query-render';

vi.mock('next/navigation', () => ({
  useSearchParams: () =>
    new URLSearchParams({ analysisId: 'historical-content' }),
  useRouter: () => ({ back: vi.fn(), push: vi.fn() }),
}));

describe('retired content history', () => {
  it('keeps a stored report readable without offering an executable writing task', async () => {
    const job: API.AnalysisResponse = {
      ...analysisJob('succeeded'),
      id: 'historical-content',
      input_kind: 'content',
      skill_id: 'content-writing',
      result_contract: 'content-document',
      result: {
        kind: 'content_document',
        document_type: 'article',
        language: 'zh-CN',
        title: '历史保存的报告',
        blocks: [],
        evidence_index: [],
        source_set_ref: 'historical-source',
        review_status: 'passed',
        review_history: [],
      },
      report_markdown: '# 历史保存的报告\n\n已保存正文仍可阅读。',
    };
    vi.mocked(httpClient.request).mockImplementation(async (config) => {
      const payload = config.url?.endsWith('/history-record')
        ? {
            ...job,
            record_type: 'content_creation',
            title: '历史内容记录',
            source_availability: 'available',
          }
        : config.url === '/api/analysis-skills'
          ? []
          : config.url?.endsWith('/runs')
            ? { items: [], next_before_run_no: null }
            : job;
      return { data: { code: 'ok', message: 'OK', data: payload } } as never;
    });
    const { container } = render(<AnalysisDetailRoute />);

    expect(await screen.findByText('已保存正文仍可阅读。')).toBeInTheDocument();
    const rerun = screen.getByRole('button', { name: '重新运行' });
    expect(rerun).toBeDisabled();
    fireEvent.click(rerun);
    expect(
      screen.queryByRole('button', { name: '确认执行' }),
    ).not.toBeInTheDocument();
    expect(container.querySelector('a[href^="/content"]')).toBeNull();
    expect(screen.getByRole('link', { name: '导出 DOCX' })).toBeInTheDocument();
    expect(httpRequests().every((request) => request.method === 'GET')).toBe(
      true,
    );
  });
});

describe('historical analysis retry', () => {
  it.each(['analysis_outcome_unknown', 'analysis_cli_failed'] as const)(
    'does not write an unknown retry while keeping known failures retryable (%s)',
    async (errorCode) => {
      vi.mocked(httpClient.request).mockReset();
      const failed = {
        ...analysisJob('failed'),
        id: 'historical-content',
        error_code: errorCode,
      } satisfies API.AnalysisResponse;
      vi.mocked(httpClient.request).mockImplementation(async (config) => {
        const payload = config.url?.endsWith('/history-record')
          ? {
              ...failed,
              record_type: 'video_analysis',
              download_id: 'owned-download',
              title: '已有视频分析',
              source_availability: 'available',
            }
          : config.url === '/api/analysis-skills'
            ? []
            : config.url?.endsWith('/runs')
              ? { items: [], next_before_run_no: null }
              : failed;
        return { data: { code: 'ok', message: 'OK', data: payload } } as never;
      });
      render(<AnalysisDetailRoute />);

      const retry = await screen.findByRole('button', { name: '重试' });
      if (errorCode === 'analysis_outcome_unknown') {
        expect(retry).toBeDisabled();
        fireEvent.click(retry);
        expect(
          screen.queryByRole('button', { name: '确认执行' }),
        ).not.toBeInTheDocument();
        expect(
          httpRequests().every((request) => request.method === 'GET'),
        ).toBe(true);
      } else {
        expect(retry).toBeEnabled();
        fireEvent.click(retry);
        fireEvent.click(
          await screen.findByRole('button', { name: '确认执行' }),
        );
        await waitFor(() =>
          expect(
            httpRequests().find((request) => request.method === 'POST'),
          ).toMatchObject({
            url: `/api/analyses/${failed.id}/retry`,
          }),
        );
      }
    },
  );
});
