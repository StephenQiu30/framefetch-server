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
  createAnalysis: runtime.create,
  getLatestDownloadAnalysis: runtime.latest,
}));
vi.mock('@/lib/task-socket', async (importOriginal) => ({
  ...(await importOriginal()),
  taskSocket: { subscribe: () => () => undefined },
}));
const input: API.AnalysisRequest = {
  skill_id: 'director-breakdown',
  output_language: 'zh-CN',
  custom_prompt: null,
};

function Detail({ id }: { id: string }) {
  const state = useAnalysisJob(id, 60_000);
  return (
    <>
      <output data-testid="action">{state.action ?? 'idle'}</output>
      <output data-testid="job">{state.job?.id ?? 'none'}</output>
      <output data-testid="loading">{String(state.loading)}</output>
      {state.error && <div role="alert">{state.error}</div>}
      <button type="button" onClick={() => void state.start(input)}>
        Start
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
    runtime.latest.mockReset().mockResolvedValue(null);
  });
  afterEach(() => onlineManager.setOnline(true));

  it('keeps a pending creation visible and blocks duplicate writes after remount', async () => {
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
    fireEvent.click(screen.getByText('Start'));
    await waitFor(() => expect(runtime.create).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByText('Navigate'));
    fireEvent.click(screen.getByText('Navigate'));
    expect(screen.getByTestId('action')).toHaveTextContent('start');
    fireEvent.click(screen.getByText('Start'));
    expect(runtime.create).toHaveBeenCalledOnce();
    await act(async () => pending.resolve(analysisJob('running')));
    await waitFor(() =>
      expect(screen.getByTestId('job')).toHaveTextContent(analysisJob().id),
    );
    await waitFor(() =>
      expect(screen.getByTestId('action')).toHaveTextContent('idle'),
    );
  });

  it('retains an unmounted failure and its idempotency key for an explicit retry', async () => {
    const pending = deferred<API.AnalysisResponse>();
    runtime.create
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValueOnce(analysisJob('running'));
    render(
      <QueryProvider>
        <Routes />
      </QueryProvider>,
    );
    fireEvent.click(screen.getByText('Start'));
    await waitFor(() => expect(runtime.create).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByText('Navigate'));
    await act(async () => pending.reject(new Error('response lost')));
    fireEvent.click(screen.getByText('Navigate'));
    await screen.findByRole('alert');
    fireEvent.click(screen.getByText('Start'));
    await waitFor(() => expect(runtime.create).toHaveBeenCalledTimes(2));
    expect(runtime.create.mock.calls[1][2]).toEqual(
      runtime.create.mock.calls[0][2],
    );
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
    fireEvent.click(screen.getByText('Start'));
    await waitFor(() => expect(runtime.create).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByText('Switch'));
    await act(async () => pending.resolve(analysisJob('running')));
    expect(screen.getByTestId('job')).toHaveTextContent('none');
    fireEvent.click(screen.getByText('Switch'));
    expect(screen.getByTestId('job')).toHaveTextContent(analysisJob().id);
  });

  it('does not publish a previous identity response into the new root', async () => {
    const pending = deferred<API.AnalysisResponse>();
    runtime.create.mockReturnValue(pending.promise);
    render(
      <QueryProvider>
        <Routes />
      </QueryProvider>,
    );
    fireEvent.click(screen.getByText('Start'));
    await waitFor(() => expect(runtime.create).toHaveBeenCalledOnce());
    act(() => advanceSessionGeneration());
    await act(async () => pending.resolve(analysisJob('running')));
    expect(screen.getByTestId('job')).toHaveTextContent('none');
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
    fireEvent.click(screen.getByText('Start'));
    await screen.findByRole('alert');
    expect(runtime.create).toHaveBeenCalledOnce();
    await act(async () => onlineManager.setOnline(true));
    expect(runtime.create).toHaveBeenCalledOnce();
  });
});
