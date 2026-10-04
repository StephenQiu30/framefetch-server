'use client';

import {
  createContext,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useContext,
  useMemo,
  useState,
} from 'react';

type HistoryFilters = {
  page: number;
  searchInput: string;
  search: string;
  status?: API.DownloadStatus;
};
type AnalysisDraft = {
  skillId: string;
  language: 'zh-CN' | 'en-US';
  customPrompt: string | null;
};
export const emptyAnalysisDraft: AnalysisDraft = {
  skillId: '',
  language: 'zh-CN',
  customPrompt: null,
};

const WorkspaceState = createContext<{
  history: HistoryFilters;
  setHistory: Dispatch<SetStateAction<HistoryFilters>>;
  analyses: Record<string, AnalysisDraft>;
  setAnalyses: Dispatch<SetStateAction<Record<string, AnalysisDraft>>>;
} | null>(null);

// Private view state survives soft navigation, but never leaves this identity's
// in-memory application root. Prompts and searches are not URL or storage data.
export function WorkspaceStateProvider({ children }: { children: ReactNode }) {
  const [history, setHistory] = useState<HistoryFilters>({
    page: 1,
    searchInput: '',
    search: '',
  });
  const [analyses, setAnalyses] = useState<Record<string, AnalysisDraft>>({});
  const value = useMemo(
    () => ({ history, setHistory, analyses, setAnalyses }),
    [history, analyses],
  );
  return <WorkspaceState value={value}>{children}</WorkspaceState>;
}

export function useWorkspaceState() {
  const state = useContext(WorkspaceState);
  if (!state) throw new Error('WorkspaceStateProvider is required');
  return state;
}
