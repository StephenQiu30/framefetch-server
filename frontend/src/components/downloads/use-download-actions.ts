import {
  useMutation,
  useMutationState,
  useQueryClient,
} from '@tanstack/react-query';
import { useMemo } from 'react';
import {
  cancelDownload,
  deleteDownload,
  issueDownloadUrl,
  retryDownload,
} from '@/api/downloads';
import { triggerBrowserDownload } from '@/lib/browser-download';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';
import { sessionGeneration } from '@/lib/session-events';
import { createUuid } from '@/lib/uuid';

export type DownloadAction = 'cancel' | 'delete' | 'download' | 'retry';
type Operation = { jobId: string } & (
  | { action: 'retry'; key: string }
  | { action: 'cancel' | 'delete' | 'download' }
);
type Result =
  | { action: 'retry' | 'cancel'; job: API.DownloadResponse }
  | { action: 'download'; file: API.DownloadUrlResponse }
  | { action: 'delete' };

/** History and detail observe the same writes; navigation belongs to the caller. */
export function useDownloadActions(jobId?: string) {
  const queries = useQueryClient();
  const mutationKey = useMemo(() => privateQueryKey('download-action'), []);
  const generation = mutationKey[1];
  const operations = useMutationState({
    filters: { mutationKey, exact: true },
    select: (mutation) => ({
      ...mutation.state,
      data: mutation.state.data as Result | undefined,
      variables: mutation.state.variables as Operation,
    }),
  });
  const relevant = jobId
    ? operations.filter((item) => item.variables.jobId === jobId)
    : operations;
  const latest = relevant.at(-1);
  const pendingActions = operations
    .filter((item) => item.status === 'pending')
    .map((item) => ({
      id: item.variables.jobId,
      type: item.variables.action,
    }));
  const mutation = useMutation({
    mutationKey,
    retry: false,
    networkMode: 'always',
    mutationFn: async (operation: Operation): Promise<Result> => {
      if (operation.action !== 'download')
        await queries.cancelQueries({
          queryKey: privateQueryKey('download', operation.jobId),
        });
      if (generation !== sessionGeneration())
        throw new Error('Session changed');
      const params = { job_id: encodeURIComponent(operation.jobId) };
      if (operation.action === 'retry')
        return {
          action: 'retry',
          job: await retryDownload(params, {
            headers: { 'Idempotency-Key': operation.key },
          }),
        };
      if (operation.action === 'cancel')
        return { action: 'cancel', job: await cancelDownload(params) };
      if (operation.action === 'download')
        return {
          action: 'download',
          file: await issueDownloadUrl(
            { ...params, preview: false },
            { headers: { 'X-Framefetch-Download-Client': 'local-web' } },
          ),
        };
      await deleteDownload(params);
      return { action: 'delete' };
    },
    onSuccess: async (result, operation) => {
      if (generation !== sessionGeneration()) return;
      if (result.action === 'download') {
        triggerBrowserDownload(result.file.url, result.file.filename);
        return;
      }
      const targetId = 'job' in result ? result.job.id : operation.jobId;
      const detailKey = privateQueryKey('download', targetId);
      const analysisKey = privateQueryKey('analysis', 'video', targetId);
      await queries.cancelQueries({ queryKey: detailKey });
      if (result.action === 'delete')
        await queries.cancelQueries({ queryKey: analysisKey });
      if (generation !== sessionGeneration()) return;
      if (result.action === 'delete') {
        queries.setQueryData(detailKey, null);
        queries.removeQueries({ queryKey: analysisKey });
      } else {
        const current = queries.getQueryData<API.DownloadResponse | null>(
          detailKey,
        );
        if (!current || result.job.version >= current.version)
          queries.setQueryData(
            detailKey,
            mergeDownloadPresentation(current ?? null, result.job),
          );
      }
      void queries.invalidateQueries({
        queryKey: privateQueryKey('download-history'),
      });
    },
  });

  async function execute(
    targetId: string,
    action: DownloadAction,
  ): Promise<Result | null> {
    if (
      queries.isMutating({
        mutationKey,
        exact: true,
        predicate: (item) =>
          (item.state.variables as Operation | undefined)?.jobId === targetId,
      })
    )
      return null;
    let operation: Operation;
    if (action === 'retry') {
      const previous = queries
        .getMutationCache()
        .findAll({ mutationKey, exact: true })
        .toReversed()
        .find((item) => {
          const value = item.state.variables as Operation | undefined;
          return value?.jobId === targetId && value.action === 'retry';
        });
      const value = previous?.state.variables as Operation | undefined;
      operation = {
        action,
        jobId: targetId,
        key:
          previous?.state.status === 'error' && value?.action === 'retry'
            ? value.key
            : createUuid(),
      };
    } else operation = { action, jobId: targetId };
    try {
      const result = await mutation.mutateAsync(operation);
      return generation === sessionGeneration() ? result : null;
    } catch {
      return null;
    }
  }

  return {
    execute,
    pendingActions,
    action: latest?.status === 'pending' ? latest.variables.action : null,
    error: latest?.status === 'error' ? displayError(latest.error) : null,
    retryTarget:
      latest?.status === 'success' && latest.data?.action === 'retry'
        ? latest.data.job.id
        : null,
    removed:
      latest?.status === 'success' && latest.variables.action === 'delete',
  };
}

export function mergeDownloadPresentation(
  current: API.DownloadResponse | null,
  next: API.DownloadResponse,
): API.DownloadResponse {
  if (!current) return next;
  return {
    ...next,
    title: next.title ?? current.title,
    extractor_key: next.extractor_key ?? current.extractor_key,
    duration_seconds: next.duration_seconds ?? current.duration_seconds,
    thumbnail_url: next.thumbnail_url ?? current.thumbnail_url,
    format: next.format ?? current.format,
  };
}
