import { act, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useAnalysisJob } from '@/components/analysis/use-analysis-job';
import { useDownloadJob } from '@/components/downloads/use-download-job';
import { analysisJob } from '../fixtures/analysis-fixtures';
import { job } from '../fixtures/download-fixtures';
import { renderHook } from '../helpers/query-render';

const runtime = vi.hoisted(() => ({
  get: vi.fn(),
  latest: vi.fn(),
  cancel: vi.fn(),
  remove: vi.fn(),
  callbacks: [] as Array<() => void>,
}));
vi.mock('@/lib/task-socket', async (importOriginal) => ({
  ...(await importOriginal()),
  taskSocket: {
    subscribe: (
      _type: string,
      _id: string,
      _version: number,
      callback: () => void,
    ) => {
      runtime.callbacks.push(callback);
      return () => undefined;
    },
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

describe.each(['download', 'analysis'] as const)(
  '%s response ordering',
  (kind) => {
    const useJob = kind === 'download' ? useDownloadJob : useAnalysisJob;
    const active =
      kind === 'download' ? job('running') : analysisJob('running');
    beforeEach(() => {
      runtime.callbacks = [];
      runtime.get.mockReset().mockResolvedValue(active);
      runtime.latest.mockReset().mockResolvedValue(active);
      runtime.cancel.mockReset();
      runtime.remove.mockReset().mockResolvedValue(undefined);
    });

    it('does not accept an older snapshot after a newer response', async () => {
      const { result } = renderHook(() => useJob(active.id, 60_000));
      await waitFor(() => expect(runtime.callbacks).toHaveLength(1));
      runtime.get.mockResolvedValueOnce({
        ...active,
        version: 4,
        progress: 60,
      });
      act(() => runtime.callbacks[0]());
      await waitFor(() => expect(result.current.job?.version).toBe(4));
      runtime.get.mockResolvedValueOnce({
        ...active,
        version: 3,
        progress: 40,
      });
      await act(async () => runtime.callbacks[0]());
      expect(result.current.job?.version).toBe(4);
      expect(result.current.job?.progress).toBe(60);
    });

    it('coalesces simultaneous socket notifications into one active query', async () => {
      const { result } = renderHook(() => useJob(active.id, 60_000));
      await waitFor(() => expect(runtime.callbacks).toHaveLength(1));
      runtime.get.mockClear();
      const pending = deferred<typeof active>();
      runtime.get.mockReturnValueOnce(pending.promise);
      act(() => {
        runtime.callbacks[0]();
        runtime.callbacks[0]();
        runtime.callbacks[0]();
      });
      expect(runtime.get).toHaveBeenCalledTimes(1);
      await act(async () => pending.resolve({ ...active, version: 4 }));
      await waitFor(() => expect(result.current.job?.version).toBe(4));
    });

    it.each(['success', 'failure'] as const)(
      'ignores a pending query %s after deletion',
      async (outcome) => {
        const { result } = renderHook(() => useJob(active.id, 60_000));
        await waitFor(() => expect(runtime.callbacks).toHaveLength(1));
        const pending = deferred<typeof active>();
        runtime.get.mockImplementationOnce(() => pending.promise);
        act(() => {
          runtime.callbacks[0]();
        });
        await act(async () => {
          await result.current.remove();
        });
        await act(async () => {
          if (outcome === 'success') pending.resolve(active);
          else pending.reject(new Error('old request failed'));
        });
        await waitFor(() => expect(result.current.job).toBeNull());
        expect(result.current.error).toBeNull();
      },
    );

    it.each(['success', 'failure'] as const)(
      'ignores an old target query %s after switching targets',
      async (outcome) => {
        const { result, rerender } = renderHook(
          ({ id }) => useJob(id, 60_000),
          { initialProps: { id: active.id } },
        );
        await waitFor(() => expect(runtime.callbacks).toHaveLength(1));
        const pending = deferred<typeof active>();
        runtime.get.mockImplementationOnce(() => pending.promise);
        act(() => {
          runtime.callbacks[0]();
        });
        const next = { ...active, id: 'another-job', version: 7 };
        runtime.get.mockResolvedValue(next);
        runtime.latest.mockResolvedValue(next);
        rerender({ id: next.id });
        await waitFor(() => expect(result.current.job?.id).toBe(next.id));
        await act(async () => {
          if (outcome === 'success') pending.resolve(active);
          else pending.reject(new Error('old request failed'));
        });
        expect(result.current.job?.id).toBe(next.id);
        expect(result.current.error).toBeNull();
      },
    );

    it.each(['success', 'failure'] as const)(
      'ignores a pending query %s after cancellation',
      async (outcome) => {
        const { result } = renderHook(() => useJob(active.id, 60_000));
        await waitFor(() => expect(runtime.callbacks).toHaveLength(1));
        const pending = deferred<typeof active>();
        runtime.get.mockImplementationOnce(() => pending.promise);
        act(() => {
          runtime.callbacks[0]();
        });
        runtime.cancel.mockResolvedValue({
          ...active,
          status: 'cancelled',
          version: 5,
        });
        await act(async () => result.current.cancel());
        await act(async () => {
          if (outcome === 'success') pending.resolve(active);
          else pending.reject(new Error('old request failed'));
        });
        await waitFor(() =>
          expect(result.current.job?.status).toBe('cancelled'),
        );
        expect(result.current.error).toBeNull();
      },
    );
  },
);

vi.mock('@/api/downloads', async (original) => ({
  ...(await original<typeof import('@/api/downloads')>()),
  getDownload: runtime.get,
  cancelDownload: runtime.cancel,
  retryDownload: vi.fn(),
  deleteDownload: runtime.remove,
  issueDownloadUrl: vi.fn(),
}));
vi.mock('@/lib/browser-download', async (original) => ({
  ...(await original<typeof import('@/lib/browser-download')>()),
  triggerBrowserDownload: vi.fn(),
}));
vi.mock('@/lib/uuid', async (original) => ({
  ...(await original<typeof import('@/lib/uuid')>()),
  createUuid: () => 'key',
}));
vi.mock('@/lib/request-error', async (original) => ({
  ...(await original<typeof import('@/lib/request-error')>()),
  displayError: () => 'old request failed',
}));
vi.mock('@/api/analyses', async (original) => ({
  ...(await original<typeof import('@/api/analyses')>()),
  getAnalysis: runtime.get,
  getLatestDownloadAnalysis: runtime.latest,
  getLatestDocumentAnalysis: runtime.latest,
  cancelAnalysis: runtime.cancel,
  createAnalysis: vi.fn(),
  createDocumentAnalysis: vi.fn(),
  deleteAnalysis: runtime.remove,
  retryAnalysis: vi.fn(),
}));
