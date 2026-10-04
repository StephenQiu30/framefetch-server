import { act, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useAnalysisJob } from '@/components/analysis/use-analysis-job';
import { ApiError } from '@/lib/request-error';
import { analysisJob } from '../fixtures/analysis-fixtures';
import { stubCryptoUuids } from '../helpers/crypto';
import { renderHook } from '../helpers/query-render';

const runtime = vi.hoisted(() => ({
  getAnalysis: vi.fn(),
  getAnalysisHistoryRecord: vi.fn(),
  createAnalysis: vi.fn(),
  deleteAnalysis: vi.fn(),
  retryAnalysis: vi.fn(),
  getLatestDownloadAnalysis: vi.fn(),
}));

describe('useAnalysisJob', () => {
  beforeEach(() => {
    runtime.getAnalysis.mockReset();
    runtime.getAnalysisHistoryRecord.mockReset();
    runtime.createAnalysis.mockReset();
    runtime.deleteAnalysis.mockReset();
    runtime.retryAnalysis.mockReset();
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

  it.each(['analysis_outcome_unknown', 'analysis_cli_failed'] as const)(
    'guards direct retry calls for unknown outcomes (%s)',
    async (errorCode) => {
      const failed = { ...analysisJob('failed'), error_code: errorCode };
      runtime.getLatestDownloadAnalysis.mockResolvedValue(failed);
      runtime.retryAnalysis.mockResolvedValue({
        ...analysisJob('queued'),
        run_no: 2,
        version: failed.version + 1,
      });
      stubCryptoUuids('33333333-3333-4333-8333-333333333333');
      const { result } = renderHook(() =>
        useAnalysisJob('download-id', 60_000),
      );
      await waitFor(() => expect(result.current.job?.id).toBe(failed.id));

      await act(async () => result.current.retry());
      if (errorCode === 'analysis_outcome_unknown') {
        expect(runtime.retryAnalysis).not.toHaveBeenCalled();
      } else {
        expect(runtime.retryAnalysis).toHaveBeenCalledOnce();
        expect(runtime.retryAnalysis).toHaveBeenCalledWith(
          { analysis_id: failed.id },
          {
            headers: {
              'Idempotency-Key': '33333333-3333-4333-8333-333333333333',
            },
          },
        );
      }
    },
  );

  it.each(['skill', 'content'] as const)(
    'never retries retired %s input tasks through the hook',
    async (inputKind) => {
      const legacy = { ...analysisJob('succeeded'), input_kind: inputKind };
      runtime.getLatestDownloadAnalysis.mockResolvedValue(legacy);
      const { result } = renderHook(() =>
        useAnalysisJob('download-id', 60_000),
      );
      await waitFor(() => expect(result.current.job?.id).toBe(legacy.id));
      await act(async () => result.current.retry());
      expect(runtime.retryAnalysis).not.toHaveBeenCalled();
    },
  );

  it('uses a fresh create idempotency key after deleting an analysis', async () => {
    const first = analysisJob('succeeded');
    const second = { ...first, id: '77777777-7777-4777-8777-777777777777' };
    runtime.createAnalysis
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(second);
    runtime.deleteAnalysis.mockResolvedValue(undefined);
    stubCryptoUuids(
      '11111111-1111-4111-8111-111111111111',
      '22222222-2222-4222-8222-222222222222',
    );
    const { result } = renderHook(() => useAnalysisJob('download-id', 60_000));
    const input: API.AnalysisRequest = {
      skill_id: 'director-breakdown',
      output_language: 'zh-CN',
      custom_prompt: null,
    };

    await act(async () => result.current.start(input));
    await waitFor(() => expect(result.current.job?.id).toBe(first.id));
    await act(async () => result.current.remove());
    await waitFor(() => expect(result.current.job).toBeNull());
    await act(async () => result.current.start(input));

    expect(runtime.createAnalysis).toHaveBeenNthCalledWith(
      1,
      { download_id: 'download-id' },
      input,
      {
        headers: { 'Idempotency-Key': '11111111-1111-4111-8111-111111111111' },
      },
    );
    expect(runtime.createAnalysis).toHaveBeenNthCalledWith(
      2,
      { download_id: 'download-id' },
      input,
      {
        headers: { 'Idempotency-Key': '22222222-2222-4222-8222-222222222222' },
      },
    );
  });
});

vi.mock('@/api/analyses', async (original) => ({
  ...(await original<typeof import('@/api/analyses')>()),
  cancelAnalysis: vi.fn(),
  createAnalysis: runtime.createAnalysis,
  createDocumentAnalysis: vi.fn(),
  deleteAnalysis: runtime.deleteAnalysis,
  getAnalysis: runtime.getAnalysis,
  getAnalysisHistoryRecord: runtime.getAnalysisHistoryRecord,
  getLatestDocumentAnalysis: vi.fn(),
  getLatestDownloadAnalysis: runtime.getLatestDownloadAnalysis,
  retryAnalysis: runtime.retryAnalysis,
}));
