'use client';

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';

import {
  createNavigationState,
  currentHistoryEntryId,
  currentRoute,
  findMarkedIndex,
  historyEntryId,
  markNavigationPush,
  NAVIGATION_PUSH_EVENT,
  type NavigationPushDetail,
  type NavigationState,
  readNavigationState,
  tagCurrentHistoryEntry,
  writeNavigationState,
} from '@/components/layout/navigation-state';

const NavigationHistoryContext = createContext(false);

export function NavigationHistoryProvider({
  children,
  currentPath,
}: {
  children: ReactNode;
  currentPath: string;
}) {
  const [canGoBack, setCanGoBack] = useState(false);
  const initializedRef = useRef(false);
  const pendingTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );

  const commitState = useCallback((state: NavigationState) => {
    writeNavigationState(state);
    setCanGoBack(state.index > 0);
  }, []);

  const syncCurrentRoute = useCallback(
    (pathname: string) => {
      const route = `${pathname}${window.location.search}`;
      const marker = currentHistoryEntryId();
      let state = readNavigationState();

      if (!initializedRef.current) {
        initializedRef.current = true;
        const markedIndex = findMarkedIndex(state, marker, route);
        if (!state || markedIndex < 0) {
          state = createNavigationState(route);
        } else {
          state.index = markedIndex;
        }
      } else if (!state) {
        state = createNavigationState(route);
      } else if (state.entries[state.index]?.route !== route) {
        const markedIndex = findMarkedIndex(state, marker, route);
        if (markedIndex >= 0) {
          state.index = markedIndex;
        } else {
          state.entries[state.index] = createNavigationState(route).entries[0];
        }
      }

      tagCurrentHistoryEntry(state.entries[state.index].id);
      commitState(state);
    },
    [commitState],
  );

  useEffect(() => {
    function handleLinkClick(event: MouseEvent) {
      if (!isPlainPrimaryClick(event)) return;
      const element = event.target;
      const link =
        element instanceof Element
          ? element.closest<HTMLAnchorElement>('a[href]')
          : null;
      if (
        !link ||
        link.dataset.navigationBack !== undefined ||
        link.download ||
        (link.target && link.target !== '_self')
      ) {
        return;
      }
      markNavigationPush(link.href);
    }

    function handleNavigationPush(event: Event) {
      const detail = (event as CustomEvent<NavigationPushDetail>).detail;
      if (!detail) return;
      clearTimeout(pendingTimerRef.current);
      tagWhenRouteArrives(detail, pendingTimerRef, 0, () => {
        const state = readNavigationState();
        if (
          state?.entries[state.index]?.id === detail.entryId &&
          state.entries[state.index].route === detail.route
        ) {
          commitState(state);
        }
      });
    }

    function handlePopState(event: PopStateEvent) {
      const route = currentRoute();
      const marker = historyEntryId(event.state);
      const state = readNavigationState();
      const markedIndex = findMarkedIndex(state, marker, route);

      if (!state || markedIndex < 0) {
        const resetState = createNavigationState(route);
        tagCurrentHistoryEntry(resetState.entries[0].id);
        commitState(resetState);
        return;
      }

      state.index = markedIndex;
      commitState(state);
    }

    document.addEventListener('click', handleLinkClick, true);
    window.addEventListener(NAVIGATION_PUSH_EVENT, handleNavigationPush);
    window.addEventListener('popstate', handlePopState);
    return () => {
      clearTimeout(pendingTimerRef.current);
      document.removeEventListener('click', handleLinkClick, true);
      window.removeEventListener(NAVIGATION_PUSH_EVENT, handleNavigationPush);
      window.removeEventListener('popstate', handlePopState);
    };
  }, [commitState]);

  useEffect(
    () => syncCurrentRoute(currentPath),
    [currentPath, syncCurrentRoute],
  );

  return (
    <NavigationHistoryContext.Provider value={canGoBack}>
      {children}
    </NavigationHistoryContext.Provider>
  );
}

export function useCanNavigateBack() {
  return useContext(NavigationHistoryContext);
}

function isPlainPrimaryClick(event: MouseEvent) {
  return !(
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  );
}

function tagWhenRouteArrives(
  detail: NavigationPushDetail,
  timerRef: { current: ReturnType<typeof setTimeout> | undefined },
  attempt: number,
  onArrive: () => void,
) {
  if (currentRoute() === detail.route) {
    tagCurrentHistoryEntry(detail.entryId);
    onArrive();
    return;
  }
  if (attempt >= 40) return;
  timerRef.current = setTimeout(
    () => tagWhenRouteArrives(detail, timerRef, attempt + 1, onArrive),
    25,
  );
}
