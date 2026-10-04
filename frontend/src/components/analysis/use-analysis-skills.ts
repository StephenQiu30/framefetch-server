import { useQuery } from '@tanstack/react-query';
import { listAnalysisSkills } from '@/api/analyses';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';

export function useAnalysisSkills(inputKind: API.AnalysisInputKind = 'video') {
  const result = useQuery({
    queryKey: privateQueryKey('analysis-skills', inputKind),
    queryFn: async ({ signal }) => {
      const data = await listAnalysisSkills(
        { input_kind: inputKind },
        { signal },
      );
      if (!Array.isArray(data)) throw new Error('分析 Skill 清单格式无效');
      return data;
    },
    staleTime: 5 * 60_000,
  });
  return {
    error: result.error ? displayError(result.error) : null,
    loading: result.isPending,
    retry: () => result.refetch(),
    skills: result.data ?? [],
  };
}
