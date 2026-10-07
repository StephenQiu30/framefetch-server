import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { BackLink } from '@/components/layout/back-link';
import { NavigationHistoryProvider } from '@/components/layout/navigation-history';
import { markNavigationPush } from '@/components/layout/navigation-state';

const STORAGE_KEY = 'framefetch-server:navigation-history';
const HISTORY_ENTRY_KEY = '__videoServerNavigationEntryId';

type StoredState = {
  entries: Array<{ id: string; route: string }>;
  index: number;
};

describe('BackLink', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/');
    sessionStorage.removeItem(STORAGE_KEY);
  });

  it('keeps an explicit fallback destination for direct entries', () => {
    render(<BackLink fallbackHref="/history" />);

    expect(screen.getByRole('link', { name: '返回上一步' })).toHaveAttribute(
      'href',
      '/history',
    );
  });

  it('uses the fallback instead of leaving the site on a direct entry', () => {
    window.history.replaceState({}, '', '/downloads/detail?jobId=direct');
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    render(
      <NavigationHistoryProvider currentPath="/downloads/detail">
        <BackLink fallbackHref="/history" />
      </NavigationHistoryProvider>,
    );

    fireEvent.click(screen.getByRole('link', { name: '返回上一步' }));

    expect(back).not.toHaveBeenCalled();
    expect(readState().entries.at(-1)?.route).toBe('/history');
  });

  it('discards a stale app stack when the browser entry has no app marker', () => {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        entries: [
          { id: crypto.randomUUID(), route: '/' },
          { id: crypto.randomUUID(), route: '/history' },
        ],
        index: 1,
      }),
    );
    window.history.replaceState({}, '', '/downloads/detail?jobId=direct');

    render(
      <NavigationHistoryProvider currentPath="/downloads/detail">
        <BackLink fallbackHref="/history" />
      </NavigationHistoryProvider>,
    );

    expect(readState().entries.map((entry) => entry.route)).toEqual([
      '/downloads/detail?jobId=direct',
    ]);
    expect(readState().index).toBe(0);
  });

  it('uses browser history when a previous in-app entry exists', () => {
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    const { rerender } = render(
      <NavigationHistoryProvider currentPath="/">
        <BackLink fallbackHref="/" />
      </NavigationHistoryProvider>,
    );

    act(() => {
      markNavigationPush('/downloads/detail?jobId=example');
      window.history.pushState({}, '', '/downloads/detail?jobId=example');
    });
    rerender(
      <NavigationHistoryProvider currentPath="/downloads/detail">
        <BackLink fallbackHref="/" />
      </NavigationHistoryProvider>,
    );

    fireEvent.click(screen.getByRole('link', { name: '返回上一步' }));

    expect(back).toHaveBeenCalledOnce();
  });

  it('truncates forward entries when pushing after browser back', () => {
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    const { rerender } = render(
      <NavigationHistoryProvider currentPath="/">
        <BackLink fallbackHref="/" />
      </NavigationHistoryProvider>,
    );

    act(() => {
      markNavigationPush('/history');
      window.history.pushState({}, '', '/history');
    });
    rerender(
      <NavigationHistoryProvider currentPath="/history">
        <BackLink fallbackHref="/" />
      </NavigationHistoryProvider>,
    );

    const rootEntry = readState().entries[0];
    act(() => {
      window.history.replaceState(
        { [HISTORY_ENTRY_KEY]: rootEntry.id },
        '',
        '/',
      );
      window.dispatchEvent(
        new PopStateEvent('popstate', { state: window.history.state }),
      );
      markNavigationPush('/account');
      window.history.replaceState({}, '', '/account');
    });
    rerender(
      <NavigationHistoryProvider currentPath="/account">
        <BackLink fallbackHref="/" />
      </NavigationHistoryProvider>,
    );

    expect(readState().entries.map((entry) => entry.route)).toEqual([
      '/',
      '/account',
    ]);
    fireEvent.click(screen.getByRole('link', { name: '返回上一步' }));
    expect(back).toHaveBeenCalledOnce();
  });

  it('replaces the current entry even when the target repeats an older route', () => {
    const { rerender } = render(
      <NavigationHistoryProvider currentPath="/">
        <BackLink fallbackHref="/" />
      </NavigationHistoryProvider>,
    );

    act(() => {
      markNavigationPush('/history');
      window.history.pushState({}, '', '/history');
    });
    rerender(
      <NavigationHistoryProvider currentPath="/history">
        <BackLink fallbackHref="/" />
      </NavigationHistoryProvider>,
    );

    act(() => {
      window.history.replaceState(window.history.state, '', '/');
    });
    rerender(
      <NavigationHistoryProvider currentPath="/">
        <BackLink fallbackHref="/" />
      </NavigationHistoryProvider>,
    );

    const state = readState();
    expect(state.entries.map((entry) => entry.route)).toEqual(['/', '/']);
    expect(state.entries[0].id).not.toBe(state.entries[1].id);
    expect(readState().index).toBe(1);
  });

  it('uses entry markers to distinguish repeated routes on popstate', () => {
    const { rerender } = render(
      <NavigationHistoryProvider currentPath="/">
        <BackLink fallbackHref="/" />
      </NavigationHistoryProvider>,
    );

    act(() => {
      markNavigationPush('/history');
      window.history.pushState({}, '', '/history');
    });
    rerender(
      <NavigationHistoryProvider currentPath="/history">
        <BackLink fallbackHref="/" />
      </NavigationHistoryProvider>,
    );
    act(() => {
      markNavigationPush('/');
      window.history.pushState({}, '', '/');
    });
    rerender(
      <NavigationHistoryProvider currentPath="/">
        <BackLink fallbackHref="/" />
      </NavigationHistoryProvider>,
    );

    const entries = readState().entries;
    act(() => {
      window.history.replaceState(
        { [HISTORY_ENTRY_KEY]: entries[0].id },
        '',
        '/',
      );
      window.dispatchEvent(
        new PopStateEvent('popstate', { state: window.history.state }),
      );
    });
    expect(readState().index).toBe(0);

    act(() => {
      window.history.replaceState(
        { [HISTORY_ENTRY_KEY]: entries[2].id },
        '',
        '/',
      );
      window.dispatchEvent(
        new PopStateEvent('popstate', { state: window.history.state }),
      );
    });
    expect(readState().index).toBe(2);
  });

  it('tracks query-only detail pushes and exact popstate entries', async () => {
    window.history.replaceState({}, '', '/downloads/detail?jobId=a');
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    render(
      <NavigationHistoryProvider currentPath="/downloads/detail">
        <BackLink fallbackHref="/history" />
      </NavigationHistoryProvider>,
    );

    act(() => {
      markNavigationPush('/downloads/detail?jobId=b');
      window.history.pushState({}, '', '/downloads/detail?jobId=b');
    });
    await waitFor(() => {
      const currentEntry = readState().entries[1];
      expect(window.history.state[HISTORY_ENTRY_KEY]).toBe(currentEntry.id);
    });
    fireEvent.click(screen.getByRole('link', { name: '返回上一步' }));
    expect(back).toHaveBeenCalledOnce();

    const firstEntry = readState().entries[0];
    back.mockClear();
    act(() => {
      window.history.replaceState(
        { [HISTORY_ENTRY_KEY]: firstEntry.id },
        '',
        '/downloads/detail?jobId=a',
      );
      window.dispatchEvent(
        new PopStateEvent('popstate', { state: window.history.state }),
      );
    });
    fireEvent.click(screen.getByRole('link', { name: '返回上一步' }));

    expect(back).not.toHaveBeenCalled();
    expect(readState().index).toBe(1);
    expect(readState().entries[1].route).toBe('/history');
  });
});

function readState() {
  return JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? '') as StoredState;
}
