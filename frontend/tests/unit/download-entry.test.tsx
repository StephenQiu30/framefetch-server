import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import DownloadWorkspace from '@/components/intake/download-workspace';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/ui/tooltip';
import { inspection } from '../fixtures/download-fixtures';
import { intentFixture } from '../fixtures/intent-fixtures';
import {
  httpRequests,
  mockHttpError,
  mockHttpResponses,
} from '../helpers/http';
import { render } from '../helpers/query-render';

const push = vi.fn();
vi.mock('@/components/auth/auth-provider', async (importOriginal) => ({
  ...(await importOriginal()),
  useAuth: () => ({ user: { id: 'intent-test-owner', role: 'user' } }),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));
vi.mock('@/components/providers/use-provider-statuses', () => ({
  useProviderStatuses: () => ({ data: null, error: null }),
}));
function renderEntry() {
  return render(
    <TooltipProvider>
      <DownloadWorkspace />
      <Toaster position="bottom-right" />
    </TooltipProvider>,
  );
}
function enter(url: string) {
  fireEvent.change(screen.getByLabelText('公开视频地址'), {
    target: { value: url },
  });
  fireEvent.click(screen.getByRole('button', { name: '解析媒体' }));
}
beforeEach(() => {
  push.mockReset();
  window.history.replaceState({}, '', '/');
});

it('recovers an uncertain submission using the same idempotency key and opens the result route', async () => {
  mockHttpError(new Error('response lost'));
  mockHttpResponses(intentFixture(), inspection);
  renderEntry();
  enter('https://youtu.be/owned');
  await waitFor(() =>
    expect(push).toHaveBeenCalledWith(
      `/downloads/new?inspectionId=${inspection.id}&intentId=${intentFixture().id}`,
    ),
  );
  const requests = httpRequests();
  expect(requests.filter((request) => request.method === 'POST')).toHaveLength(
    1,
  );
  expect(requests[1]).toMatchObject({
    method: 'GET',
    url: '/api/download-intents',
    params: { idempotency_key: requests[0].headers?.['Idempotency-Key'] },
  });
});

it('dismisses the loading notice once the parsed result has opened', async () => {
  mockHttpResponses(intentFixture(), inspection);
  renderEntry();
  enter('https://youtu.be/owned');
  await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
  expect(sessionStorage.getItem('framefetch-active-intent')).toBeNull();
  await waitFor(() =>
    expect(
      document.getElementById('parse-intent-status'),
    ).not.toBeInTheDocument(),
  );
});

it('shows active parsing and its cancel action in Sonner', async () => {
  mockHttpResponses(
    intentFixture({ status: 'resolving', inspection_id: null }),
    intentFixture({ status: 'cancelled', inspection_id: null }),
  );
  renderEntry();
  enter('https://youtu.be/owned');
  await waitFor(() =>
    expect(
      document.querySelector('[data-sonner-toast][data-type="loading"]'),
    ).toHaveTextContent('正在读取媒体信息'),
  );
  expect(
    document.getElementById('parse-intent-status'),
  ).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '取消解析' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: '取消解析' }));
  await waitFor(() =>
    expect(httpRequests()).toContainEqual(
      expect.objectContaining({
        method: 'POST',
        url: `/api/download-intents/${intentFixture().id}/cancel`,
      }),
    ),
  );
  expect(push).not.toHaveBeenCalled();
});

it('retires a restored ready task after handing off its result', async () => {
  const ready = intentFixture();
  sessionStorage.setItem(
    'framefetch-active-intent',
    JSON.stringify({ owner: 'intent-test-owner', id: ready.id }),
  );
  mockHttpResponses(ready, inspection);
  const first = renderEntry();
  await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
  expect(sessionStorage.getItem('framefetch-active-intent')).toBeNull();
  const requests = httpRequests().length;
  first.unmount();
  renderEntry();
  expect(screen.getByLabelText('公开视频地址')).toBeVisible();
  expect(httpRequests()).toHaveLength(requests);
  expect(push).toHaveBeenCalledTimes(1);
});

it('keeps an expired inspection on home with a refresh action', async () => {
  mockHttpResponses(intentFixture(), {
    ...inspection,
    expires_at: new Date(Date.now() - 1000).toISOString(),
  });
  renderEntry();
  enter('https://youtu.be/owned');
  expect(await screen.findByRole('button', { name: '更新结果' })).toBeEnabled();
  expect(document.getElementById('parse-intent-status')).toHaveTextContent(
    '解析结果已过期',
  );
  expect(push).not.toHaveBeenCalled();
  expect(document.querySelector('[data-slot="media-result"]')).toBeNull();
});

it('shows a shared recovery notice when a restored task status cannot refresh', async () => {
  const task = intentFixture({ status: 'resolving', inspection_id: null });
  sessionStorage.setItem(
    'framefetch-active-intent',
    JSON.stringify({ owner: 'intent-test-owner', id: task.id }),
  );
  mockHttpError(new Error('service unavailable'));
  mockHttpResponses(task);
  try {
    renderEntry();
    const retry = await screen.findByRole('button', { name: '恢复任务' });
    const notice = document.getElementById('parse-intent-status');
    expect(notice).toHaveAttribute('data-slot', 'empty');
    expect(notice).toHaveAttribute('role', 'alert');
    expect(notice).toHaveTextContent('任务状态暂时无法更新');
    fireEvent.click(retry);
    await waitFor(() => expect(notice).not.toBeInTheDocument());
    expect(httpRequests().map((request) => request.method)).toEqual([
      'GET',
      'GET',
    ]);
  } finally {
    sessionStorage.removeItem('framefetch-active-intent');
  }
});

it('does not restore a completed download into the homepage', async () => {
  const completed = intentFixture({
    status: 'handed_off',
    inspection_id: null,
    job_id: '33333333-3333-4333-8333-333333333333',
  });
  sessionStorage.setItem(
    'framefetch-active-intent',
    JSON.stringify({ owner: 'intent-test-owner', id: completed.id }),
  );
  mockHttpResponses(completed);
  try {
    renderEntry();
    await waitFor(() => expect(httpRequests()).toHaveLength(1));
    expect(push).not.toHaveBeenCalled();
    expect(document.querySelector('[data-slot="media-result"]')).toBeNull();
  } finally {
    sessionStorage.removeItem('framefetch-active-intent');
  }
});

it('shows parse failures once in Sonner without an inline status panel', async () => {
  mockHttpResponses(
    intentFixture({
      status: 'failed',
      inspection_id: null,
      reason_code: 'provider_unavailable',
    }),
  );
  renderEntry();
  enter('https://youtu.be/owned');
  await waitFor(() =>
    expect(
      document.querySelector('[data-sonner-toast][data-type="error"]'),
    ).toHaveTextContent('本次解析未完成'),
  );
  expect(document.querySelectorAll('[data-sonner-toast]')).toHaveLength(1);
  expect(
    document.getElementById('parse-intent-status'),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '取消解析' })).toBeNull();
  expect(screen.getByRole('button', { name: '解析媒体' })).toBeEnabled();
  expect(screen.getByLabelText('公开视频地址')).toHaveValue(
    'https://youtu.be/owned',
  );
});

it('restores a login wait after the execution deadline and resumes the original intent', async () => {
  const waiting = intentFixture({
    status: 'action_required',
    inspection_id: null,
    next_action: 'login',
    reason_code: 'provider_session_not_ready',
    deadline: new Date(Date.now() - 10000).toISOString(),
    authorization_id: '55555555-5555-4555-8555-555555555555',
    authorization_deadline: new Date(Date.now() + 3600000).toISOString(),
  });
  sessionStorage.setItem(
    'framefetch-active-intent',
    JSON.stringify({ owner: 'intent-test-owner', id: waiting.id }),
  );
  mockHttpResponses(
    waiting,
    intentFixture({ status: 'queued', inspection_id: null }),
  );
  renderEntry();
  const resume = await screen.findByRole('button', {
    name: '已处理，继续解析',
  });
  expect(document.getElementById('parse-intent-status')).toHaveTextContent(
    '等待处理平台登录',
  );
  expect(
    screen.queryByText('等待时间已到，请查询后台任务的最终状态。'),
  ).toBeNull();
  await waitFor(() =>
    expect(
      document.querySelector(
        '[data-sonner-toast][data-type="loading"]:not([data-removed="true"])',
      ),
    ).toBeNull(),
  );
  fireEvent.click(resume);
  await waitFor(() =>
    expect(httpRequests()).toContainEqual(
      expect.objectContaining({
        method: 'POST',
        url: `/api/download-intents/${waiting.id}/resume`,
        data: { authorization_id: waiting.authorization_id },
      }),
    ),
  );
  expect(
    httpRequests().filter(
      (r) => r.url === '/api/download-intents' && r.method === 'POST',
    ),
  ).toHaveLength(0);
});
