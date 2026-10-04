import { useQueryClient } from '@tanstack/react-query';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { StrictMode, useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useDownloadHistory } from '@/components/downloads/use-download-history';
import { QueryProvider } from '@/components/layout/query-provider';
import { privateQueryKey } from '@/lib/query-keys';
import { advanceSessionGeneration } from '@/lib/session-events';

const runtime = vi.hoisted(() => ({ history: vi.fn(), skills: vi.fn() }));
vi.mock('@/api/downloads', () => ({ getDownloadHistory: runtime.history }));

function page(total: number): API.DownloadHistoryResponse {
  return {
    items: [],
    page: 1,
    page_size: 20,
    total,
    summary: { total, active: 0, succeeded: 0, failed: 0 },
  };
}

function History() {
  const state = useDownloadHistory({ page: 1, page_size: 20 });
  return (
    <>
      <div data-testid="data">{JSON.stringify(state.data)}</div>
      <div data-testid="loading">{String(state.loading)}</div>
      {state.error && <div role="alert">{state.error}</div>}
      <button onClick={state.retry} type="button">
        Refresh
      </button>
    </>
  );
}

function Routes() {
  const [visible, setVisible] = useState(true);
  const client = useQueryClient();
  return (
    <>
      <button onClick={() => setVisible(!visible)} type="button">
        Navigate
      </button>
      <button
        onClick={() =>
          void client.invalidateQueries({
            queryKey: privateQueryKey('download-history'),
            refetchType: 'none',
          })
        }
        type="button"
      >
        Mark stale
      </button>
      {visible ? <History /> : <div>Other page</div>}
    </>
  );
}

describe('root query continuity', () => {
  beforeEach(() => {
    runtime.history.mockReset();
    runtime.skills.mockReset();
  });

  it('keeps loaded data across route unmounts without a loading flash', async () => {
    runtime.history.mockResolvedValue(page(1));
    render(
      <QueryProvider>
        <Routes />
      </QueryProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId('data')).toHaveTextContent('"total":1'),
    );
    fireEvent.click(screen.getByText('Navigate'));
    fireEvent.click(screen.getByText('Navigate'));
    expect(screen.getByTestId('data')).toHaveTextContent('"total":1');
    expect(screen.getByTestId('loading')).toHaveTextContent('false');
    expect(runtime.history).toHaveBeenCalledOnce();
  });

  it('keeps stale content when a background revalidation fails', async () => {
    runtime.history
      .mockResolvedValueOnce(page(2))
      .mockRejectedValue(new Error('Network unavailable'));
    render(
      <QueryProvider>
        <Routes />
      </QueryProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId('data')).toHaveTextContent('"total":2'),
    );
    fireEvent.click(screen.getByText('Navigate'));
    fireEvent.click(screen.getByText('Mark stale'));
    fireEvent.click(screen.getByText('Navigate'));
    expect(screen.getByTestId('data')).toHaveTextContent('"total":2');
    await screen.findByRole('alert');
    expect(screen.getByTestId('data')).toHaveTextContent('"total":2');
    expect(screen.getByTestId('loading')).toHaveTextContent('false');
    expect(runtime.history).toHaveBeenCalledTimes(2);
  });

  it('cancels old identity requests and never restores their late private results', async () => {
    let finishOld!: (value: API.DownloadHistoryResponse) => void;
    let oldSignal!: AbortSignal;
    runtime.history
      .mockImplementationOnce((_params, options) => {
        oldSignal = options.signal;
        return new Promise((resolve) => {
          finishOld = resolve;
        });
      })
      .mockResolvedValue(page(3));
    render(
      <QueryProvider>
        <Routes />
      </QueryProvider>,
    );
    act(() => advanceSessionGeneration());
    expect(oldSignal.aborted).toBe(true);
    await waitFor(() =>
      expect(screen.getByTestId('data')).toHaveTextContent('"total":3'),
    );
    await act(async () => finishOld(page(4)));
    expect(screen.getByTestId('data')).not.toHaveTextContent('"total":4');
    fireEvent.click(screen.getByText('Navigate'));
    fireEvent.click(screen.getByText('Navigate'));
    expect(screen.getByTestId('data')).toHaveTextContent('"total":3');
  });

  it('clears already loaded private data synchronously when identity changes', async () => {
    runtime.history
      .mockResolvedValueOnce(page(4))
      .mockReturnValue(new Promise(() => {}));
    render(
      <QueryProvider>
        <Routes />
      </QueryProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId('data')).toHaveTextContent('"total":4'),
    );
    act(() => advanceSessionGeneration());
    expect(screen.getByTestId('data')).toHaveTextContent('null');
    expect(screen.getByTestId('loading')).toHaveTextContent('true');
  });

  it('survives React strict effect replay without losing the active query', async () => {
    runtime.history.mockResolvedValue(page(5));
    render(
      <StrictMode>
        <QueryProvider>
          <Routes />
        </QueryProvider>
      </StrictMode>,
    );
    await waitFor(() =>
      expect(screen.getByTestId('data')).toHaveTextContent('"total":5'),
    );
    fireEvent.click(screen.getByText('Navigate'));
    fireEvent.click(screen.getByText('Navigate'));
    expect(screen.getByTestId('data')).toHaveTextContent('"total":5');
  });
});
