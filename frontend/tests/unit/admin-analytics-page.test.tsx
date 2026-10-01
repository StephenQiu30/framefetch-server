import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AdminAnalyticsView } from '@/components/admin/admin-analytics-view';
import { render } from '../helpers/query-render';

const runtime = vi.hoisted(() => ({
  getAdminDownloadAnalytics: vi.fn(),
  getAnalysisAnalytics: vi.fn(),
}));

describe('administrator usage analytics', () => {
  beforeEach(() => {
    runtime.getAdminDownloadAnalytics.mockReset();
    runtime.getAnalysisAnalytics.mockReset();
  });

  it('renders KPI, trend data and source details', async () => {
    runtime.getAdminDownloadAnalytics.mockResolvedValue(analytics());
    render(<AdminAnalyticsView />);

    expect(
      await screen.findByRole('heading', { level: 1, name: '使用统计' }),
    ).toBeInTheDocument();
    expect(runtime.getAdminDownloadAnalytics).toHaveBeenCalledWith(
      {
        days: 30,
      },
      { signal: expect.any(AbortSignal) },
    );
    await waitFor(() =>
      expect(screen.getByText('下载总数').nextElementSibling).toHaveTextContent(
        '48',
      ),
    );
    expect(
      screen.getByText('成功率', { selector: '[data-slot="item-title"]' })
        .nextElementSibling,
    ).toHaveTextContent('75%');
    expect(screen.getByText('独立用户').nextElementSibling).toHaveTextContent(
      '12',
    );
    expect(screen.getByText('下载数据量').nextElementSibling).toHaveTextContent(
      '3 GB',
    );
    expect(screen.getByText(/平均视频时长/)).toHaveTextContent('2 分 5 秒');
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();

    expect(
      screen.getByRole('img', { name: '每日下载任务交互趋势图' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('img', { name: '下载任务状态环形图' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('img', { name: '每日下载成功率面积图' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('img', { name: '视频来源任务贡献条形图' }),
    ).toBeInTheDocument();
    const exactData = screen.getByRole('table', {
      name: '每日下载趋势精确数据',
    });
    expect(
      within(exactData).getByRole('row', { name: /2026-08-09 20 16 2 1/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('table', { name: '每日下载成功率精确数据' }),
    ).toBeInTheDocument();
    expect(screen.getByText('最近一天 71.4%')).toBeInTheDocument();

    expect(screen.getAllByRole('meter')).toHaveLength(2);
    expect(
      screen.getByRole('meter', { name: '抖音占全部下载的62.5%' }),
    ).toHaveAttribute('value', '62.5');
    expect(
      screen.queryByRole('table', { name: '各视频源下载表现' }),
    ).not.toBeInTheDocument();
    const detailsTrigger = screen.getByRole('button', {
      name: '查看 2 个来源',
    });
    expect(detailsTrigger).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(detailsTrigger);
    expect(detailsTrigger).toHaveAttribute('aria-expanded', 'true');
    expect(
      screen.getByRole('table', { name: '各视频源下载表现' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('rowheader', { name: /抖音 douyin/ }),
    ).toBeInTheDocument();
    expect(screen.getAllByText('抖音')).toHaveLength(1);
    expect(screen.getByRole('link', { name: '返回上一步' })).toHaveAttribute(
      'href',
      '/account',
    );
  });

  it('maps period changes and refresh to the analytics request', async () => {
    const periodRefresh = deferred<API.DownloadAnalyticsResponse>();
    runtime.getAdminDownloadAnalytics
      .mockResolvedValueOnce(analytics())
      .mockReturnValueOnce(periodRefresh.promise)
      .mockResolvedValueOnce(analytics());
    render(<AdminAnalyticsView />);
    await waitFor(() =>
      expect(runtime.getAdminDownloadAnalytics).toHaveBeenCalledTimes(1),
    );

    const periodSelect = screen.getByRole('combobox', { name: '统计周期' });
    expect(periodSelect).toHaveTextContent('最近 30 天');
    fireEvent.click(periodSelect);
    fireEvent.click(await screen.findByRole('option', { name: '最近 7 天' }));
    await waitFor(() =>
      expect(runtime.getAdminDownloadAnalytics).toHaveBeenLastCalledWith(
        {
          days: 7,
        },
        { signal: expect.any(AbortSignal) },
      ),
    );
    expect(screen.getByText('下载总数').nextElementSibling).toHaveTextContent(
      '48',
    );
    expect(
      screen.queryByRole('status', { name: '正在加载下载分析' }),
    ).not.toBeInTheDocument();
    expect(periodSelect).toHaveTextContent('最近 7 天');

    await act(async () => periodRefresh.resolve(analytics()));
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: '刷新使用统计' }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: '刷新使用统计' }));
    await waitFor(() =>
      expect(runtime.getAdminDownloadAnalytics).toHaveBeenCalledTimes(3),
    );
  });

  it('covers loading, error retry and empty states', async () => {
    const first = deferred<API.DownloadAnalyticsResponse>();
    runtime.getAdminDownloadAnalytics
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(
        analytics({
          daily: [],
          sources: [],
          summary: { ...analytics().summary, total: 0 },
        }),
      );
    render(<AdminAnalyticsView />);

    expect(
      screen.getByRole('status', { name: '正在加载下载分析' }),
    ).toBeInTheDocument();
    await act(async () => first.reject(new Error('统计服务暂不可用')));
    expect(await screen.findByText('统计服务暂不可用')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(
      await screen.findByText('当前周期还没有下载数据'),
    ).toBeInTheDocument();
  });

  it('loads AI execution statistics only after selecting its tab', async () => {
    runtime.getAdminDownloadAnalytics.mockResolvedValue(analytics());
    runtime.getAnalysisAnalytics.mockResolvedValue(analysisAnalytics());
    render(<AdminAnalyticsView />);
    await screen.findByRole('img', { name: '每日下载任务交互趋势图' });
    expect(runtime.getAnalysisAnalytics).not.toHaveBeenCalled();

    selectAnalyticsTab('AI 分析');
    expect(
      await screen.findByRole('img', { name: '每日 AI 分析执行趋势图' }),
    ).toBeInTheDocument();
    expect(runtime.getAnalysisAnalytics).toHaveBeenCalledWith(
      { days: 30 },
      { signal: expect.any(AbortSignal) },
    );
    expect(
      screen.queryByRole('img', { name: '每日下载任务交互趋势图' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'AI 分析' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(
      screen.getByRole('tabpanel', { name: 'AI 分析' }),
    ).toBeInTheDocument();
    expect(
      screen.getByText('执行次数', { selector: '[data-slot="item-title"]' })
        .nextElementSibling,
    ).toHaveTextContent('20');
    expect(
      screen.getByText('成功率', { selector: '[data-slot="item-title"]' })
        .nextElementSibling,
    ).toHaveTextContent('83.3%');
    expect(
      screen.getByText('平均完成耗时').nextElementSibling,
    ).toHaveTextContent('1 分 22 秒');
    expect(
      screen.getByText('进行中', { selector: '[data-slot="item-title"]' })
        .nextElementSibling,
    ).toHaveTextContent('5');
    expect(screen.getByText('12 次有效完成记录')).toBeInTheDocument();
    expect(
      screen.getByText(/按创建日期（UTC）统计分析执行记录/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('img', { name: 'AI 分析执行状态环形图' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('img', { name: 'AI 分析输入类型环形图' }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('AI 分析输入类型精确数据')).toHaveTextContent(
      '视频1260%剧本840%',
    );
    expect(screen.getByLabelText('AI 分析状态精确数据')).toHaveTextContent(
      '成功1050%进行中525%失败210%取消315%',
    );
    const detailsTrigger = screen.getByRole('button', { name: '查看每日明细' });
    expect(detailsTrigger).toHaveAttribute('aria-expanded', 'false');
    expect(
      screen.queryByRole('table', { name: '每日 AI 分析执行精确数据' }),
    ).not.toBeInTheDocument();
    fireEvent.click(detailsTrigger);
    expect(detailsTrigger).toHaveAttribute('aria-expanded', 'true');
    expect(
      within(
        screen.getByRole('table', { name: '每日 AI 分析执行精确数据' }),
      ).getByRole('row', { name: /2026-08-10 20 10 2 3 5/ }),
    ).toBeInTheDocument();
    fireEvent.click(detailsTrigger);
    expect(detailsTrigger).toHaveAttribute('aria-expanded', 'false');
    expect(
      screen.queryByRole('table', { name: '每日 AI 分析执行精确数据' }),
    ).not.toBeInTheDocument();
  });

  it('shares periods across tabs and retains AI data during refresh recovery', async () => {
    const period = deferred<API.AnalysisAnalyticsResponse>();
    const refresh = deferred<API.AnalysisAnalyticsResponse>();
    runtime.getAdminDownloadAnalytics.mockResolvedValue(analytics());
    runtime.getAnalysisAnalytics
      .mockResolvedValueOnce(analysisAnalytics())
      .mockReturnValueOnce(period.promise)
      .mockReturnValueOnce(refresh.promise)
      .mockResolvedValueOnce(analysisAnalytics());
    render(<AdminAnalyticsView />);
    selectAnalyticsTab('AI 分析');
    await screen.findByRole('img', { name: '每日 AI 分析执行趋势图' });
    const select = screen.getByRole('combobox', { name: '统计周期' });
    fireEvent.click(select);
    fireEvent.click(await screen.findByRole('option', { name: '最近 7 天' }));
    await waitFor(() =>
      expect(runtime.getAnalysisAnalytics).toHaveBeenLastCalledWith(
        { days: 7 },
        { signal: expect.any(AbortSignal) },
      ),
    );
    expect(
      screen.getByText('执行次数', { selector: '[data-slot="item-title"]' })
        .nextElementSibling,
    ).toHaveTextContent('20');
    expect(
      screen.queryByRole('status', { name: '正在加载 AI 分析统计' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刷新使用统计' })).toBeDisabled();
    await act(async () =>
      period.resolve(analysisAnalytics({ period_days: 7 })),
    );
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: '刷新使用统计' }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: '刷新使用统计' }));
    await act(async () => refresh.reject(new Error('AI 统计刷新暂不可用')));
    expect(await screen.findByText('AI 分析统计刷新失败')).toBeInTheDocument();
    expect(
      screen.getByRole('img', { name: '每日 AI 分析执行趋势图' }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
    await waitFor(() =>
      expect(runtime.getAnalysisAnalytics).toHaveBeenCalledTimes(4),
    );
    await waitFor(() =>
      expect(screen.queryByText('AI 分析统计刷新失败')).not.toBeInTheDocument(),
    );

    selectAnalyticsTab('下载');
    expect(select).toHaveTextContent('最近 7 天');
    await waitFor(() =>
      expect(runtime.getAdminDownloadAnalytics).toHaveBeenLastCalledWith(
        { days: 7 },
        { signal: expect.any(AbortSignal) },
      ),
    );
    await screen.findByRole('img', { name: '每日下载任务交互趋势图' });
    fireEvent.click(select);
    fireEvent.click(await screen.findByRole('option', { name: '最近 3 个月' }));
    await waitFor(() =>
      expect(runtime.getAdminDownloadAnalytics).toHaveBeenLastCalledWith(
        { days: 90 },
        { signal: expect.any(AbortSignal) },
      ),
    );
    expect(runtime.getAnalysisAnalytics).toHaveBeenCalledTimes(4);
  });

  it('recovers AI initial errors to a true empty state without zero charts', async () => {
    const first = deferred<API.AnalysisAnalyticsResponse>();
    runtime.getAdminDownloadAnalytics.mockResolvedValue(analytics());
    runtime.getAnalysisAnalytics
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(
        analysisAnalytics({
          summary: {
            total: 0,
            succeeded: 0,
            failed: 0,
            cancelled: 0,
            active: 0,
            average_duration_seconds: null,
            completed_duration_count: 0,
          },
          daily: [
            {
              date: '2026-08-10',
              total: 0,
              succeeded: 0,
              failed: 0,
              cancelled: 0,
              active: 0,
            },
          ],
          inputs: [
            { input_kind: 'video', total: 0 },
            { input_kind: 'screenplay', total: 0 },
          ],
        }),
      );
    render(<AdminAnalyticsView />);
    selectAnalyticsTab('AI 分析');
    expect(
      screen.getByRole('status', { name: '正在加载 AI 分析统计' }),
    ).toBeInTheDocument();
    await act(async () => first.reject(new Error('AI 统计暂不可用')));
    expect(await screen.findByText('无法加载 AI 分析统计')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(
      await screen.findByText('当前周期还没有 AI 分析记录'),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole('tabpanel', { name: 'AI 分析' })).queryByRole(
        'img',
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText('执行次数', { selector: '[data-slot="item-title"]' }),
    ).not.toBeInTheDocument();
  });

  it('keeps unavailable success and duration metrics distinct from zero', async () => {
    runtime.getAdminDownloadAnalytics.mockResolvedValue(analytics());
    runtime.getAnalysisAnalytics.mockResolvedValue(
      analysisAnalytics({
        summary: {
          total: 2,
          succeeded: 0,
          failed: 0,
          cancelled: 1,
          active: 1,
          average_duration_seconds: null,
          completed_duration_count: 0,
        },
        daily: [
          {
            date: '2026-08-10',
            total: 2,
            succeeded: 0,
            failed: 0,
            cancelled: 1,
            active: 1,
          },
        ],
        inputs: [
          { input_kind: 'video', total: 1 },
          { input_kind: 'screenplay', total: 1 },
        ],
      }),
    );
    render(<AdminAnalyticsView />);
    selectAnalyticsTab('AI 分析');
    await screen.findByRole('img', { name: '每日 AI 分析执行趋势图' });
    expect(
      screen.getByText('成功率', { selector: '[data-slot="item-title"]' })
        .nextElementSibling,
    ).toHaveTextContent('—');
    expect(
      screen.getByText('平均完成耗时').nextElementSibling,
    ).toHaveTextContent('—');
    expect(screen.getByText('暂无完成耗时')).toBeInTheDocument();
  });
});

function selectAnalyticsTab(name: '下载' | 'AI 分析') {
  fireEvent.mouseDown(screen.getByRole('tab', { name }), {
    button: 0,
    ctrlKey: false,
  });
}

function analysisAnalytics(
  overrides: Partial<API.AnalysisAnalyticsResponse> = {},
): API.AnalysisAnalyticsResponse {
  return {
    period_days: 30,
    start: '2026-07-12',
    end: '2026-08-10',
    summary: {
      total: 20,
      succeeded: 10,
      failed: 2,
      cancelled: 3,
      active: 5,
      average_duration_seconds: 82.4,
      completed_duration_count: 12,
    },
    daily: [
      {
        date: '2026-08-10',
        total: 20,
        succeeded: 10,
        failed: 2,
        cancelled: 3,
        active: 5,
      },
    ],
    inputs: [
      { input_kind: 'video', total: 12 },
      { input_kind: 'screenplay', total: 8 },
    ],
    ...overrides,
  };
}

function analytics(
  overrides: Partial<API.DownloadAnalyticsResponse> = {},
): API.DownloadAnalyticsResponse {
  return {
    period_days: 30,
    start: '2026-07-12',
    end: '2026-08-10',
    summary: {
      total: 48,
      succeeded: 36,
      failed: 5,
      cancelled: 2,
      active: 5,
      unique_users: 12,
      downloaded_bytes: 3 * 1024 * 1024 * 1024,
      average_duration_seconds: 125,
      success_rate: 75,
    },
    daily: [
      {
        date: '2026-08-09',
        total: 20,
        succeeded: 16,
        failed: 2,
        cancelled: 1,
      },
      {
        date: '2026-08-10',
        total: 28,
        succeeded: 20,
        failed: 3,
        cancelled: 1,
      },
    ],
    sources: [
      {
        source_key: 'douyin',
        source_name: '抖音',
        total: 30,
        succeeded: 24,
        failed: 3,
        cancelled: 1,
        active: 2,
        unique_users: 9,
        downloaded_bytes: 2 * 1024 * 1024 * 1024,
        success_rate: 80,
      },
      {
        source_key: 'bilibili',
        source_name: '哔哩哔哩',
        total: 18,
        succeeded: 12,
        failed: 2,
        cancelled: 1,
        active: 3,
        unique_users: 6,
        downloaded_bytes: 1024 * 1024 * 1024,
        success_rate: 66.7,
      },
    ],
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, reject, resolve };
}

vi.mock('@/lib/request-error', async (original) => ({
  ...(await original<typeof import('@/lib/request-error')>()),
  displayError: (reason: unknown) =>
    reason instanceof Error ? reason.message : '请求失败',
}));
vi.mock('@/api/admin', async (original) => ({
  ...(await original<typeof import('@/api/admin')>()),
  getDownloadAnalytics: runtime.getAdminDownloadAnalytics,
  getAnalysisAnalytics: runtime.getAnalysisAnalytics,
}));
