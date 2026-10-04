import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AnalysisRuns } from '@/components/analysis/analysis-detail-route';
import { httpClient } from '@/lib/request';
import { httpRequests, mockHttpResponses } from '../helpers/http';
import { render } from '../helpers/query-render';

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
}));
const run: API.AnalysisRunHistoryResponse = {
  id: 'run-1',
  run_no: 1,
  trigger: 'initial',
  status: 'running',
  created_at: '2026-10-04T00:00:00Z',
  started_at: null,
  finished_at: null,
  error_code: null,
};

describe('analysis run history', () => {
  beforeEach(() => {
    vi.mocked(httpClient.request).mockReset();
  });
  it('reads terminal history when the same run finishes before the polling interval', async () => {
    mockHttpResponses({ items: [run], next_before_run_no: null });
    const view = render(<AnalysisRuns id="task-1" runNo={1} active />);
    expect(await screen.findByText('正在分析')).toBeInTheDocument();
    mockHttpResponses({
      items: [{ ...run, status: 'succeeded' }],
      next_before_run_no: null,
    });
    view.rerender(<AnalysisRuns id="task-1" runNo={1} active={false} />);
    expect(await screen.findByText('分析已完成')).toBeInTheDocument();
    expect(httpRequests()).toHaveLength(2);
  });
  it('identifies retained historical drafts and translates failure reasons', async () => {
    mockHttpResponses({
      items: [
        { ...run, trigger: 'manual_edit', status: 'succeeded' },
        {
          ...run,
          id: 'old',
          run_no: 0,
          status: 'failed',
          error_code: 'analysis_outcome_unknown',
        },
      ],
      next_before_run_no: null,
    });
    render(<AnalysisRuns id="task-1" runNo={1} active={false} />);
    expect(
      await screen.findByText('第 1 份报告 · 历史人工稿'),
    ).toBeInTheDocument();
    expect(screen.getByText(/为避免重复计费未自动重试/)).toBeInTheDocument();
    expect(
      screen.queryByText('analysis_outcome_unknown'),
    ).not.toBeInTheDocument();
  });
});
