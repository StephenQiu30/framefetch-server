import { createUuid } from '@/lib/uuid';

const STORAGE_KEY = 'video-server:navigation-history';
const HISTORY_ENTRY_KEY = '__videoServerNavigationEntryId';
export const NAVIGATION_PUSH_EVENT = 'video-server:navigation-push';

const MAX_ENTRIES = 32;

type NavigationEntry = {
  id: string;
  route: string;
};

export type NavigationState = {
  entries: NavigationEntry[];
  index: number;
};

export type NavigationPushDetail = {
  entryId: string;
  route: string;
};

export function markNavigationPush(targetHref: string) {
  if (typeof window === 'undefined') return;
  const targetRoute = internalRoute(targetHref);
  if (!targetRoute || targetRoute === currentRoute()) return;

  const route = currentRoute();
  const marker = currentHistoryEntryId();
  let state = readNavigationState();
  const markedIndex = findMarkedIndex(state, marker, route);

  if (!state || markedIndex < 0) {
    state = createNavigationState(route);
  } else {
    state.index = markedIndex;
  }

  state = appendNavigationEntry(state, targetRoute);
  writeNavigationState(state);
  window.dispatchEvent(
    new CustomEvent<NavigationPushDetail>(NAVIGATION_PUSH_EVENT, {
      detail: {
        entryId: state.entries[state.index].id,
        route: targetRoute,
      },
    }),
  );
}

function appendNavigationEntry(state: NavigationState, route: string) {
  const entries = [
    ...state.entries.slice(0, state.index + 1),
    createEntry(route),
  ];
  const overflow = Math.max(0, entries.length - MAX_ENTRIES);
  return {
    entries: entries.slice(overflow),
    index: entries.length - overflow - 1,
  };
}

export function createNavigationState(route: string): NavigationState {
  return {
    entries: [createEntry(route)],
    index: 0,
  };
}

export function currentRoute() {
  return `${window.location.pathname}${window.location.search}`;
}

export function currentHistoryEntryId() {
  return historyEntryId(window.history.state);
}

export function historyEntryId(value: unknown) {
  if (!value || typeof value !== 'object') return undefined;
  const marker = (value as Record<string, unknown>)[HISTORY_ENTRY_KEY];
  return typeof marker === 'string' ? marker : undefined;
}

export function findMarkedIndex(
  state: NavigationState | undefined,
  marker: string | undefined,
  route: string,
) {
  if (!state || !marker) return -1;
  return state.entries.findIndex(
    (entry) => entry.id === marker && entry.route === route,
  );
}

export function tagCurrentHistoryEntry(entryId: string) {
  const historyState =
    window.history.state && typeof window.history.state === 'object'
      ? window.history.state
      : {};
  if (historyEntryId(historyState) === entryId) return;
  window.history.replaceState(
    { ...historyState, [HISTORY_ENTRY_KEY]: entryId },
    '',
    window.location.href,
  );
}

export function readNavigationState(): NavigationState | undefined {
  try {
    const value: unknown = JSON.parse(
      sessionStorage.getItem(STORAGE_KEY) ?? '',
    );
    if (!value || typeof value !== 'object') return undefined;
    const state = value as Partial<NavigationState>;
    if (
      !Array.isArray(state.entries) ||
      state.entries.length === 0 ||
      !state.entries.every(isNavigationEntry) ||
      !Number.isInteger(state.index) ||
      (state.index ?? -1) < 0 ||
      (state.index ?? 0) >= state.entries.length
    ) {
      return undefined;
    }
    return state as NavigationState;
  } catch {
    return undefined;
  }
}

export function writeNavigationState(state: NavigationState) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Every BackLink keeps a stable fallback when storage is unavailable.
  }
}

function internalRoute(targetHref: string) {
  try {
    const target = new URL(targetHref, window.location.href);
    return target.origin === window.location.origin
      ? `${target.pathname}${target.search}`
      : undefined;
  } catch {
    return undefined;
  }
}

function createEntry(route: string): NavigationEntry {
  return { id: createUuid(), route };
}

function isNavigationEntry(entry: unknown): entry is NavigationEntry {
  return Boolean(
    entry &&
      typeof entry === 'object' &&
      typeof (entry as Partial<NavigationEntry>).id === 'string' &&
      typeof (entry as Partial<NavigationEntry>).route === 'string',
  );
}
