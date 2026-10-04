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
import AnalysisConfigurator from '@/components/analysis/analysis-configurator';
import { useDownloadHistory } from '@/components/downloads/use-download-history';
import { QueryProvider } from '@/components/layout/query-provider';
import { privateQueryKey } from '@/lib/query-keys';
import { advanceSessionGeneration } from '@/lib/session-events';
import { analysisSkills } from '../fixtures/analysis-fixtures';

const runtime = vi.hoisted(() => ({ history: vi.fn(), skills: vi.fn() }));
vi.mock('@/api/downloads', () => ({ getDownloadHistory: runtime.history }));
vi.mock('@/api/analyses', () => ({ listAnalysisSkills: runtime.skills }));

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

  it('does not overwrite an edited prompt when the skill catalog arrives late', async () => {
    let finish!: (value: API.AnalysisSkillResponse[]) => void;
    runtime.skills.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const start = vi.fn();
    render(
      <QueryProvider>
        <AnalysisConfigurator
          inputId="test-input"
          busy={false}
          onStart={start}
        />
      </QueryProvider>,
    );
    expect(screen.getByText('正在加载可用的分析任务…')).toBeInTheDocument();
    expect(screen.getByLabelText('分析任务')).toBeDisabled();
    expect(screen.getByRole('button', { name: '开始 AI 分析' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('分析提示词'), {
      target: { value: '保留我输入的要求' },
    });
    await act(async () => finish(analysisSkills));
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: '开始 AI 分析' }),
      ).toBeEnabled(),
    );
    expect(screen.getByLabelText('分析提示词')).toHaveValue('保留我输入的要求');
    fireEvent.click(screen.getByRole('button', { name: '开始 AI 分析' }));
    expect(start).toHaveBeenCalledWith(
      expect.objectContaining({ custom_prompt: '保留我输入的要求' }),
    );
  });

  it('shows an empty skill catalog and allows a refresh without losing the prompt', async () => {
    runtime.skills
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce(analysisSkills);
    const start = vi.fn();
    render(
      <QueryProvider>
        <AnalysisConfigurator
          inputId="test-input"
          busy={false}
          onStart={start}
        />
      </QueryProvider>,
    );

    await screen.findByText('当前没有可用的分析任务。');
    expect(screen.queryByText('正在加载可用的分析任务…')).toBeNull();
    expect(screen.getByLabelText('分析任务')).toBeDisabled();
    const startButton = screen.getByRole('button', { name: '开始 AI 分析' });
    expect(startButton).toBeDisabled();
    fireEvent.click(startButton);
    expect(start).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('分析提示词'), {
      target: { value: '等待清单时保留的要求' },
    });
    fireEvent.click(screen.getByRole('button', { name: '刷新清单' }));
    await waitFor(() => expect(startButton).toBeEnabled());
    expect(screen.getByLabelText('分析任务')).toHaveTextContent('导演拉片');
    expect(screen.getByLabelText('分析提示词')).toHaveValue(
      '等待清单时保留的要求',
    );
    fireEvent.click(startButton);
    expect(start).toHaveBeenCalledWith(
      expect.objectContaining({
        skill_id: analysisSkills[0].id,
        custom_prompt: '等待清单时保留的要求',
      }),
    );
    expect(runtime.skills).toHaveBeenCalledTimes(2);
  });

  it('distinguishes a catalog error from a successful empty response and retries', async () => {
    runtime.skills
      .mockRejectedValueOnce(new Error('Network unavailable'))
      .mockResolvedValueOnce(analysisSkills);
    render(
      <QueryProvider>
        <AnalysisConfigurator
          inputId="test-input"
          busy={false}
          onStart={vi.fn()}
        />
      </QueryProvider>,
    );

    await screen.findByText('任务清单加载失败。');
    expect(screen.getByLabelText('分析任务')).toHaveTextContent('清单加载失败');
    expect(screen.queryByText('当前没有可用的分析任务。')).toBeNull();
    expect(screen.queryByText('正在加载可用的分析任务…')).toBeNull();
    expect(screen.getByRole('button', { name: '开始 AI 分析' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: '开始 AI 分析' }),
      ).toBeEnabled(),
    );
    expect(screen.queryByText('任务清单加载失败。')).toBeNull();
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
