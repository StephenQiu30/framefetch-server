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

it.each([
  {
    code: 'identity_unavailable',
    cause: 'identity_cookie_rules_unverified',
    expected: '该平台的身份规则尚未接通，当前无法解析；可导入已有本地视频。',
  },
  {
    code: 'runtime_unavailable',
    cause: 'browser_not_implemented',
    expected: '该平台的解析尚未接通，当前无法解析；可导入已有本地视频。',
  },
  ...['extension_disconnected', 'credential_missing', 'session_missing'].map(
    (cause) => ({
      code: 'identity_unavailable' as const,
      cause,
      expected: '平台登录材料暂不可用，请检查部署主机的登录状态后重新解析。',
    }),
  ),
] as const)(
  'explains $cause in the failure notice',
  async ({ code, cause, expected }) => {
    mockHttpResponses(
      intentFixture({
        status: 'failed',
        inspection_id: null,
        reason_code: code,
        failure: {
          code,
          failure_class: code,
          layer: 'L3',
          stage: 'resolve',
          gate: '③',
          evidence: { kind: 'runtime', cause_code: cause },
          summary: 'upstream detail must not be shown',
        },
      }),
    );
    renderEntry();
    enter('https://weixin.qq.com/sph/A9znfitafp');
    await waitFor(() =>
      expect(
        document.querySelector('[data-sonner-toast][data-type="error"]'),
      ).toHaveTextContent(expected),
    );
    expect(screen.queryByText('upstream detail must not be shown')).toBeNull();
    expect(push).not.toHaveBeenCalled();
  },
);
