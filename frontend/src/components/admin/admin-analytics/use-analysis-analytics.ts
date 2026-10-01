import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { getAnalysisAnalytics } from '@/api/admin';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';

export function useAdminAnalysisAnalytics(days: 7 | 30 | 90, enabled = true) {
  const result = useQuery({
    queryKey: privateQueryKey('admin-analysis-analytics', days),
    queryFn: ({ signal }) => getAnalysisAnalytics({ days }, { signal }),
    placeholderData: keepPreviousData,
    enabled,
  });
  return {
    data: result.data ?? null,
    error: result.error ? displayError(result.error) : null,
    loading: result.isFetching,
    retry: () => {
      void result.refetch();
    },
  };
}
