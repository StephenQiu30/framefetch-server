import { act, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useAnalysisJob } from '@/components/analysis/use-analysis-job';
import { ApiError } from '@/lib/request-error';
import { analysisJob } from '../fixtures/analysis-fixtures';
import { renderHook } from '../helpers/query-render';

const runtime = vi.hoisted(() => ({
  getAnalysis: vi.fn(),
  getAnalysisHistoryRecord: vi.fn(),
  deleteAnalysis: vi.fn(),
  getLatestDownloadAnalysis: vi.fn(),
}));

describe('useAnalysisJob', () => {
  beforeEach(() => {
    runtime.getAnalysis.mockReset();
    runtime.getAnalysisHistoryRecord.mockReset();
    runtime.deleteAnalysis.mockReset();
    runtime.getLatestDownloadAnalysis.mockReset();
    runtime.getLatestDownloadAnalysis.mockResolvedValue(null);
  });

  it('opens the selected screenplay analysis and rejects mismatched sources without falling back', async () => {
    const selected = { ...analysisJob('succeeded'), input_kind: 'screenplay' };
    runtime.getAnalysis.mockResolvedValue(selected);
    runtime.getAnalysisHistoryRecord.mockResolvedValue({
      document_id: 'doc-a',
    });
    const { result } = renderHook(() =>
      useAnalysisJob('doc-a', 60000, 'screenplay', selected.id),
    );
    await waitFor(() => expect(result.current.job?.id).toBe(selected.id));
    expect(runtime.getLatestDownloadAnalysis).not.toHaveBeenCalled();
    runtime.getAnalysisHistoryRecord.mockResolvedValue({
      document_id: 'doc-b',
    });
    await act(async () => result.current.retryPoll());
    await waitFor(() =>
      expect(result.current.error).toContain('不属于当前素材'),
    );
    expect(runtime.getAnalysis).toHaveBeenCalledTimes(1);
  });

  it('does not replace a missing selected analysis with the latest result', async () => {
    runtime.getAnalysis.mockRejectedValue(
      new ApiError(404, 'request_failed', '记录已删除', '记录已删除'),
    );
    const { result } = renderHook(() =>
      useAnalysisJob('', 60000, 'video', 'missing'),
    );
    await waitFor(() => expect(result.current.error).toContain('记录已删除'));
    expect(result.current.job).toBeNull();
    expect(runtime.getLatestDownloadAnalysis).not.toHaveBeenCalled();
  });
});

vi.mock('@/api/analyses', async (original) => ({
  ...(await original<typeof import('@/api/analyses')>()),
  cancelAnalysis: vi.fn(),
  deleteAnalysis: runtime.deleteAnalysis,
  getAnalysis: runtime.getAnalysis,
  getAnalysisHistoryRecord: runtime.getAnalysisHistoryRecord,
  getLatestDocumentAnalysis: vi.fn(),
  getLatestDownloadAnalysis: runtime.getLatestDownloadAnalysis,
}));
