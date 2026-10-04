import {
  useMutation,
  useMutationState,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  cancelAnalysis,
  deleteAnalysis,
  getAnalysis,
  getAnalysisHistoryRecord,
  getLatestDocumentAnalysis,
  getLatestDownloadAnalysis,
} from '@/api/analyses';
import { isTerminalAnalysisStatus } from '@/components/analysis/analysis-panel-model';
import { privateQueryKey } from '@/lib/query-keys';
import { ApiError, displayError } from '@/lib/request-error';
import { sessionGeneration } from '@/lib/session-events';
import { TaskSocketStatusCode, taskSocket } from '@/lib/task-socket';

type Operation = { action: 'cancel' | 'delete'; analysisId: string };

export function useAnalysisJob(
  inputId: string,
  pollIntervalMs: number,
  inputKind: API.AnalysisInputKind = 'video',
  selectedAnalysisId?: string,
) {
  const queries = useQueryClient();
  const [socketStatus, setSocketStatus] = useState(
    TaskSocketStatusCode.Disconnected,
  );
  const sourceKey = `${inputKind}:${inputId}:${selectedAnalysisId ?? 'latest'}`;
  const queryKey = useMemo(
    () =>
      privateQueryKey(
        'analysis',
        inputKind,
        inputId,
        selectedAnalysisId ?? 'latest',
      ),
    [inputKind, inputId, selectedAnalysisId],
  );
  const mutationKey = useMemo(
    () =>
      privateQueryKey(
        'analysis-action',
        inputKind,
        inputId,
        selectedAnalysisId ?? 'latest',
      ),
    [inputKind, inputId, selectedAnalysisId],
  );
  const sourceKeyRef = useRef(sourceKey);
  const versionRef = useRef(0);
  const operations = useMutationState({
    filters: { mutationKey, exact: true },
    select: (mutation) => mutation.state,
  });
  const latest = operations.at(-1);
  const action =
    latest?.status === 'pending'
      ? (latest.variables as Operation).action
      : null;
  const actionError =
    latest?.status === 'error' ? displayError(latest.error) : null;
  const mutation = useMutation({
    mutationKey,
    retry: false,
    networkMode: 'always',
    mutationFn: async (
      operation: Operation,
    ): Promise<API.AnalysisResponse | null> => {
      await queries.cancelQueries({ queryKey });
      if (queryKey[1] !== sessionGeneration())
        throw new Error('Session changed');
      const params = { analysis_id: encodeURIComponent(operation.analysisId) };
      if (operation.action === 'cancel') return cancelAnalysis(params);
      await deleteAnalysis(params);
      return null;
    },
    onSuccess: async (next) => {
      if (queryKey[1] !== sessionGeneration()) return;
      await queries.cancelQueries({ queryKey });
      if (queryKey[1] !== sessionGeneration()) return;
      const current = queries.getQueryData<API.AnalysisResponse | null>(
        queryKey,
      );
      if (current && next && isOlder(current, next)) return;
      queries.setQueryData(queryKey, next);
      for (const resource of [
        'intent-history',
        'analysis-history-record',
        'analysis-runs',
      ]) {
        void queries.invalidateQueries({ queryKey: privateQueryKey(resource) });
      }
    },
  });

  const snapshot = useQuery({
    queryKey,
    enabled: !action,
    queryFn: async ({ signal }) => {
      if (selectedAnalysisId && inputId) {
        const record = await getAnalysisHistoryRecord(
          { analysis_id: encodeURIComponent(selectedAnalysisId) },
          { signal },
        );
        if (
          (inputKind === 'screenplay'
            ? record.document_id
            : record.download_id) !== inputId
        )
          throw new ApiError(
            409,
            'analysis_source_mismatch',
            '来源不匹配',
            '该分析记录不属于当前素材，请从我的处理记录重新打开。',
          );
      }
      const previous = queries.getQueryData<API.AnalysisResponse | null>(
        queryKey,
      );
      const active = previous && !isTerminalAnalysisStatus(previous.status);
      const next = active
        ? await getAnalysis(
            { analysis_id: encodeURIComponent(previous.id) },
            { signal },
          )
        : selectedAnalysisId
          ? await getAnalysis(
              { analysis_id: encodeURIComponent(selectedAnalysisId) },
              { signal },
            )
          : inputKind === 'screenplay'
            ? await getLatestDocumentAnalysis(
                { document_id: encodeURIComponent(inputId) },
                { signal },
              )
            : await getLatestDownloadAnalysis(
                { download_id: encodeURIComponent(inputId) },
                { signal },
              );
      if (active && next?.id !== previous.id)
        throw new Error('Unexpected analysis response');
      if (selectedAnalysisId && next?.id !== selectedAnalysisId)
        throw new Error('Unexpected analysis response');
      const current = queries.getQueryData<API.AnalysisResponse | null>(
        queryKey,
      );
      return current && next && isOlder(current, next) ? current : next;
    },
    refetchInterval: (query) => {
      const current = query.state.data;
      if (
        !current ||
        query.state.error ||
        isTerminalAnalysisStatus(current.status)
      )
        return false;
      return socketStatus === TaskSocketStatusCode.Connected
        ? Math.max(15_000, pollIntervalMs * 10)
        : Math.max(2_000, pollIntervalMs);
    },
    refetchOnWindowFocus: true,
  });
  const job = snapshot.data ?? null;
  const error =
    actionError ?? (snapshot.error ? displayError(snapshot.error) : null);
  const analysisId = job?.id ?? null;
  const shouldSync = job ? !isTerminalAnalysisStatus(job.status) : false;
  versionRef.current = job?.version ?? 0;

  useEffect(() => {
    if (sourceKeyRef.current === sourceKey) return;
    sourceKeyRef.current = sourceKey;
    setSocketStatus(TaskSocketStatusCode.Disconnected);
  }, [sourceKey]);

  const refetch = snapshot.refetch;
  useEffect(() => {
    if (action || !analysisId || !shouldSync) return;
    return taskSocket.subscribe(
      'analysis',
      analysisId,
      versionRef.current,
      () => {
        void refetch({ cancelRefetch: false });
      },
      setSocketStatus,
    );
  }, [action, analysisId, refetch, shouldSync]);

  async function execute(operation: Operation) {
    // Pending is recorded synchronously, before another click or route mount.
    if (queries.isMutating({ mutationKey, exact: true })) return;
    try {
      await mutation.mutateAsync(operation);
    } catch {
      /* Shared state owns the visible error. */
    }
  }
  const cancel = async () => {
    if (analysisId) await execute({ action: 'cancel', analysisId });
  };
  const retryPoll = useCallback(async () => {
    if (!action) await refetch({ cancelRefetch: false });
  }, [action, refetch]);
  const remove = async () => {
    if (analysisId) await execute({ action: 'delete', analysisId });
  };

  return {
    action,
    cancel,
    error,
    errorKind: actionError
      ? 'action'
      : snapshot.error
        ? job
          ? 'sync'
          : 'load'
        : null,
    job,
    loading: snapshot.isPending,
    remove,
    retryPoll,
    socketStatus,
  };
}

function isOlder(current: API.AnalysisResponse, next: API.AnalysisResponse) {
  return (
    current.id === next.id &&
    (next.version < current.version || next.run_no < current.run_no)
  );
}
