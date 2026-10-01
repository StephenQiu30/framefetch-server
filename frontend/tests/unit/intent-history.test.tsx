import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { IntentHistoryPage } from '@/components/intake/intent-history-page';
import { job } from '../fixtures/download-fixtures';
import { intentFixture } from '../fixtures/intent-fixtures';
import { httpRequests, mockHttpResponses } from '../helpers/http';
import { render } from '../helpers/query-render';

const push = vi.fn();
vi.mock('@/components/auth/auth-provider', async (importOriginal) => ({
  ...(await importOriginal()),
  useAuth: () => ({ user: { id: 'history-test-owner', role: 'user' } }),
}));
vi.mock('@/components/analysis/use-analysis-skills', () => ({
  useAnalysisSkills: () => ({ skills: [] }),
}));
vi.mock('next/navigation', async () => {
  const React = await import('react');
  return {
    useRouter: () => ({ push }),
    useSearchParams: () => {
      const [search, setSearch] = React.useState(window.location.search);
      React.useEffect(() => {
        const listener = () => setSearch(window.location.search);
        window.addEventListener('history-test', listener);
        return () => window.removeEventListener('history-test', listener);
      }, []);
      return new URLSearchParams(search);
    },
  };
});
beforeEach(() => {
  push.mockReset();
  window.history.replaceState(null, '', '/history/activity');
  const original = window.history.pushState.bind(window.history);
  vi.spyOn(window.history, 'pushState').mockImplementation((...args) => {
    original(...args);
    window.dispatchEvent(new Event('history-test'));
  });
});

it('keeps pagination read-only and sends a ready result to its dedicated page', async () => {
  const item = {
    ...intentFixture(),
    created_at: '2026-09-23T00:00:00Z',
    title: '之前解析的视频',
    record_type: 'parse',
    status_group: 'completed',
  };
  mockHttpResponses({
    items: [item],
    next_cursor: {
      id: item.id,
      created_at: item.created_at,
      record_type: 'parse',
    },
  });
  render(<IntentHistoryPage />);
  expect(screen.getByRole('heading', { name: '我的处理记录' })).toBeVisible();
  expect(await screen.findByText(item.title)).toBeVisible();
  mockHttpResponses({
    items: [
      {
        ...item,
        id: '66666666-6666-4666-8666-666666666666',
        title: '较早的视频',
      },
    ],
    next_cursor: null,
  });
  expect(
    screen.getByRole('navigation', { name: '解析记录分页' }),
  ).toBeVisible();
  expect(screen.getByRole('button', { name: '第 1 页' })).toHaveAttribute(
    'aria-current',
    'page',
  );
  fireEvent.click(screen.getByRole('button', { name: '第 2 页' }));
  expect(await screen.findByText('较早的视频')).toBeVisible();
  expect(screen.getByRole('button', { name: '第 2 页' })).toHaveAttribute(
    'aria-current',
    'page',
  );
  expect(screen.queryByText('更早的记录')).toBeNull();
  expect(httpRequests()[1].params).toMatchObject({
    before_id: item.id,
    before_created_at: item.created_at,
    before_record_type: 'parse',
    limit: 10,
  });
  fireEvent.click(screen.getByRole('button', { name: '查看结果' }));
  expect(push).toHaveBeenCalledWith(
    '/downloads/new?inspectionId=11111111-1111-4111-8111-111111111111&intentId=66666666-6666-4666-8666-666666666666',
  );
  mockHttpResponses({ items: [item], next_cursor: null });
  fireEvent.click(screen.getByRole('button', { name: '上一页' }));
  expect(await screen.findByText(item.title)).toBeVisible();
  expect(window.location.search).toBe('');
  expect(screen.getByRole('button', { name: '第 1 页' })).toHaveAttribute(
    'aria-current',
    'page',
  );
  expect(httpRequests().every((request) => request.method === 'GET')).toBe(
    true,
  );
});

it('shows numbered pages and resets to page one when the category changes', async () => {
  const first = {
    ...intentFixture(),
    record_type: 'parse',
    status_group: 'completed',
    title: '第一页内容',
    created_at: '2026-09-23T00:00:00Z',
  };
  const second = {
    ...first,
    id: '22222222-2222-4222-8222-222222222222',
    title: '第二页内容',
  };
  const third = {
    ...first,
    id: '33333333-3333-4333-8333-333333333333',
    title: '第三页内容',
  };
  const page = (item: typeof first, more: boolean) => ({
    items: [item],
    next_cursor: more
      ? { id: item.id, created_at: item.created_at, record_type: 'parse' }
      : null,
  });
  mockHttpResponses(page(first, true));
  render(<IntentHistoryPage />);
  await screen.findByText(first.title);

  mockHttpResponses(page(second, true));
  fireEvent.click(screen.getByRole('button', { name: '下一页' }));
  await screen.findByText(second.title);
  mockHttpResponses(page(third, false));
  fireEvent.click(screen.getByRole('button', { name: '下一页' }));
  await screen.findByText(third.title);
  expect(screen.getByText('第 3 页')).toBeVisible();
  expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled();

  mockHttpResponses(page(first, true));
  fireEvent.click(screen.getByRole('button', { name: '第 1 页' }));
  expect(await screen.findByText(first.title)).toBeVisible();
  expect(window.location.search).toBe('');

  mockHttpResponses({ items: [], next_cursor: null });
  fireEvent.click(screen.getByRole('radio', { name: '视频 AI' }));
  expect(await screen.findByText('没有匹配的解析记录')).toBeVisible();
  expect(window.location.search).toBe('?category=video');
});

it('opens failed history in a read-only dialog without restoring it as the current home task', async () => {
  const failed = intentFixture({
    status: 'failed',
    reason_code: 'login_required',
    inspection_id: null,
  });
  mockHttpResponses(
    {
      items: [
        {
          ...failed,
          record_type: 'parse',
          status_group: 'failed',
          title: null,
          created_at: '2026-09-23T00:00:00Z',
        },
      ],
      next_cursor: null,
    },
    failed,
  );
  render(<IntentHistoryPage />);
  const detailButton = await screen.findByRole('button', { name: '查看详情' });
  fireEvent.click(detailButton);
  expect(await screen.findByRole('dialog')).toBeVisible();
  // The status renders in its column and, for narrow screens, inside the
  // content cell; CSS shows exactly one of them.
  expect(screen.getAllByText('本次解析未完成')).toHaveLength(2);
  expect(await screen.findByText(/该内容需要登录/)).toBeVisible();
  expect(httpRequests().map((request) => request.url)).toEqual([
    '/api/download-intents/history/records',
    `/api/download-intents/${failed.id}`,
  ]);
  expect(push).not.toHaveBeenCalled();
  expect(sessionStorage.getItem('framefetch-active-intent')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '关闭' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(detailButton).toHaveFocus();
});

it('shows handed-off download status and progress in a dialog before any navigation', async () => {
  const download = { ...job('running'), progress: 42 };
  const handedOff = intentFixture({
    status: 'handed_off',
    job_id: download.id,
    inspection_id: null,
  });
  mockHttpResponses(
    {
      items: [
        {
          ...handedOff,
          record_type: 'parse',
          status_group: 'completed',
          title: '已进入下载的视频',
          created_at: '2026-09-23T00:00:00Z',
        },
      ],
      next_cursor: null,
    },
    handedOff,
    download,
  );
  render(<IntentHistoryPage />);
  fireEvent.click(await screen.findByRole('button', { name: '查看下载' }));
  expect(await screen.findByText('正在下载')).toBeVisible();
  expect(
    screen.getByRole('progressbar', { name: '下载进度 42%' }),
  ).toBeVisible();
  expect(
    screen.getByRole('link', { name: '打开完整下载任务' }),
  ).toHaveAttribute('href', `/downloads/detail?jobId=${download.id}`);
  expect(httpRequests().map((request) => request.url)).toEqual([
    '/api/download-intents/history/records',
    `/api/download-intents/${handedOff.id}`,
    `/api/downloads/${download.id}`,
  ]);
  expect(push).not.toHaveBeenCalled();
});

it('renders screenplay and video analyses as independent exact-id links', async () => {
  mockHttpResponses({
    items: [
      {
        id: 'analysis-first',
        record_type: 'screenplay_analysis',
        document_id: 'doc',
        title: '剧本第一稿',
        skill_id: 'screenplay-analysis',
        output_language: 'zh-CN',
        result_contract: 'screenplay-analysis',
        status: 'failed',
        status_group: 'failed',
        created_at: '2026-09-24T00:00:00Z',
        source_availability: 'unavailable',
      },
      {
        id: 'analysis-second',
        record_type: 'video_analysis',
        title: '视频拉片',
        skill_id: 'director-breakdown',
        output_language: 'zh-CN',
        status: 'succeeded',
        status_group: 'completed',
        created_at: '2026-09-24T00:00:00Z',
      },
      {
        id: 'doc',
        record_type: 'document_parse',
        document_id: 'doc',
        title: '剧本原文',
        status: 'ready',
        status_group: 'completed',
        created_at: '2026-09-24T00:00:00Z',
      },
    ],
    next_cursor: null,
  });
  render(<IntentHistoryPage />);
  await screen.findByText('剧本第一稿');
  const links = screen.getAllByRole('link', { name: '查看分析' });
  expect(links.map((link) => link.getAttribute('href'))).toEqual([
    '/analyses/detail?analysisId=analysis-first',
    '/analyses/detail?analysisId=analysis-second',
  ]);
  expect(screen.getByRole('link', { name: '查看文档' })).toHaveAttribute(
    'href',
    '/documents/detail?documentId=doc',
  );
  expect(httpRequests().every((request) => request.method === 'GET')).toBe(
    true,
  );
});

it('selects only downloadable parse rows even when another record has the same id', async () => {
  const parse = {
    ...intentFixture(),
    record_type: 'parse',
    status_group: 'completed',
    title: '可下载链接',
    created_at: '2026-09-24T00:00:00Z',
  };
  mockHttpResponses({
    items: [
      parse,
      {
        id: parse.id,
        record_type: 'document_parse',
        document_id: parse.id,
        title: '同编号剧本',
        status: 'ready',
        status_group: 'completed',
        created_at: parse.created_at,
      },
    ],
    next_cursor: null,
  });
  render(<IntentHistoryPage />);
  await screen.findByRole('table', { name: '解析任务列表' });
  expect(screen.queryByRole('button', { name: /批量下载/ })).toBeNull();
  expect(
    screen.getByRole('checkbox', { name: '选择 同编号剧本' }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox', { name: '选择本页可操作记录' }));
  expect(
    screen.getByRole('checkbox', { name: '选择 可下载链接' }),
  ).toBeChecked();
  expect(
    screen.getByRole('checkbox', { name: '选择 同编号剧本' }),
  ).not.toBeChecked();
  expect(screen.getByRole('button', { name: '批量下载（1）' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: '取消选择' }));
  expect(screen.queryByRole('button', { name: /批量下载/ })).toBeNull();
  expect(httpRequests().every((request) => request.method === 'GET')).toBe(
    true,
  );
});
