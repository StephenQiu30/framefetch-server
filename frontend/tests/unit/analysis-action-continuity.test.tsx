import { onlineManager } from '@tanstack/react-query';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAnalysisJob } from '@/components/analysis/use-analysis-job';
import { QueryProvider } from '@/components/layout/query-provider';
import { advanceSessionGeneration } from '@/lib/session-events';
import { analysisJob } from '../fixtures/analysis-fixtures';

const runtime = vi.hoisted(() => ({ create: vi.fn(), latest: vi.fn() }));
vi.mock('@/api/analyses', () => ({
  cancelAnalysis: runtime.create,
  getLatestDownloadAnalysis: runtime.latest,
  getAnalysis: runtime.latest,
}));
vi.mock('@/lib/task-socket', async (importOriginal) => ({
  ...(await importOriginal()),
  taskSocket: { subscribe: () => () => undefined },
}));
function Detail({ id }: { id: string }) {
  const state = useAnalysisJob(id, 60_000);
  return (
    <>
      <output data-testid="action">{state.action ?? 'idle'}</output>
      <output data-testid="job">{state.job?.id ?? 'none'}</output>
      <output data-testid="status">{state.job?.status ?? 'none'}</output>
      <output data-testid="loading">{String(state.loading)}</output>
      {state.error && <div role="alert">{state.error}</div>}
      <button type="button" onClick={() => void state.cancel()}>
        Cancel
      </button>
    </>
  );
}
function Routes() {
  const [visible, setVisible] = useState(true);
  const [id, setId] = useState('first');
  return (
    <>
      <button type="button" onClick={() => setVisible(!visible)}>
        Navigate
      </button>
      <button
        type="button"
        onClick={() => setId(id === 'first' ? 'second' : 'first')}
      >
        Switch
      </button>
      {visible && <Detail id={id} />}
    </>
  );
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

describe('analysis operations across routes', () => {
  beforeEach(() => {
    runtime.create.mockReset();
    runtime.latest.mockReset().mockResolvedValue(analysisJob('running'));
  });
  afterEach(() => onlineManager.setOnline(true));

  it('keeps a pending cancellation visible and blocks duplicate writes after remount', async () => {
    const pending = deferred<API.AnalysisResponse>();
    runtime.create.mockReturnValue(pending.promise);
    render(
      <QueryProvider>
        <Routes />
      </QueryProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId('loading')).toHaveTextContent('false'),
    );
    await waitFor(() =>
      expect(screen.getByTestId('loading')).toHaveTextContent('false'),
    );
    fireEvent.click(screen.getByText('Cancel'));
    await waitFor(() => expect(runtime.create).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByText('Navigate'));
    fireEvent.click(screen.getByText('Navigate'));
    expect(screen.getByTestId('action')).toHaveTextContent('cancel');
    fireEvent.click(screen.getByText('Cancel'));
    expect(runtime.create).toHaveBeenCalledOnce();
    await act(async () => pending.resolve(analysisJob('cancelled')));
    await waitFor(() =>
      expect(screen.getByTestId('job')).toHaveTextContent(analysisJob().id),
    );
    await waitFor(() =>
      expect(screen.getByTestId('action')).toHaveTextContent('idle'),
    );
  });

  it('retains an unmounted cancellation failure for an explicit retry', async () => {
    const pending = deferred<API.AnalysisResponse>();
    runtime.create
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValueOnce(analysisJob('cancelled'));
    render(
      <QueryProvider>
        <Routes />
      </QueryProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId('loading')).toHaveTextContent('false'),
    );
    fireEvent.click(screen.getByText('Cancel'));
    await waitFor(() => expect(runtime.create).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByText('Navigate'));
    await act(async () => pending.reject(new Error('response lost')));
    fireEvent.click(screen.getByText('Navigate'));
    await screen.findByRole('alert');
    fireEvent.click(screen.getByText('Cancel'));
    await waitFor(() => expect(runtime.create).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.getByTestId('job')).toHaveTextContent(analysisJob().id),
    );
  });

  it('updates only the original input when its response arrives on another page', async () => {
    const pending = deferred<API.AnalysisResponse>();
    runtime.create.mockReturnValue(pending.promise);
    render(
      <QueryProvider>
        <Routes />
      </QueryProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId('loading')).toHaveTextContent('false'),
    );
    fireEvent.click(screen.getByText('Cancel'));
    await waitFor(() => expect(runtime.create).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByText('Switch'));
    await act(async () => pending.resolve(analysisJob('cancelled')));
    await waitFor(() =>
      expect(screen.getByTestId('status')).toHaveTextContent('running'),
    );
    fireEvent.click(screen.getByText('Switch'));
    await waitFor(() =>
      expect(screen.getByTestId('status')).toHaveTextContent('cancelled'),
    );
  });

  it('does not publish a previous identity response into the new root', async () => {
    const pending = deferred<API.AnalysisResponse>();
    runtime.create.mockReturnValue(pending.promise);
    render(
      <QueryProvider>
        <Routes />
      </QueryProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId('loading')).toHaveTextContent('false'),
    );
    fireEvent.click(screen.getByText('Cancel'));
    await waitFor(() => expect(runtime.create).toHaveBeenCalledOnce());
    act(() => advanceSessionGeneration());
    await act(async () => pending.resolve(analysisJob('cancelled')));
    await waitFor(() =>
      expect(screen.getByTestId('status')).toHaveTextContent('running'),
    );
    expect(screen.getByTestId('action')).toHaveTextContent('idle');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('fails an offline write without replaying it when the connection returns', async () => {
    runtime.create.mockRejectedValue(new Error('offline'));
    render(
      <QueryProvider>
        <Routes />
      </QueryProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId('loading')).toHaveTextContent('false'),
    );
    onlineManager.setOnline(false);
    fireEvent.click(screen.getByText('Cancel'));
    await screen.findByRole('alert');
    expect(runtime.create).toHaveBeenCalledOnce();
    await act(async () => onlineManager.setOnline(true));
    expect(runtime.create).toHaveBeenCalledOnce();
  });
});
