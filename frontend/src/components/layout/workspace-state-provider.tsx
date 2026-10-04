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
const WorkspaceState = createContext<{
  history: HistoryFilters;
  setHistory: Dispatch<SetStateAction<HistoryFilters>>;
} | null>(null);

// Private view state survives soft navigation, but never leaves this identity's
// in-memory application root. Unsubmitted searches are not URL or storage data.
export function WorkspaceStateProvider({ children }: { children: ReactNode }) {
  const [history, setHistory] = useState<HistoryFilters>({
    page: 1,
    searchInput: '',
    search: '',
  });
  const value = useMemo(() => ({ history, setHistory }), [history]);
  return <WorkspaceState value={value}>{children}</WorkspaceState>;
}

export function useWorkspaceState() {
  const state = useContext(WorkspaceState);
  if (!state) throw new Error('WorkspaceStateProvider is required');
  return state;
}
