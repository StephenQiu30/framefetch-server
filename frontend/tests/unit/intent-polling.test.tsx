import { act } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useDownloadIntent } from '@/components/intake/use-download-intent';
import { ApiError } from '@/lib/request-error';
import { intentFixture } from '../fixtures/intent-fixtures';
import {
  httpRequests,
  mockHttpError,
  mockHttpResponses,
} from '../helpers/http';
import { renderHook } from '../helpers/query-render';

vi.mock('@/components/auth/auth-provider', async (importOriginal) => ({
  ...(await importOriginal()),
  useAuth: () => ({ user: { id: 'poll-test-owner', role: 'user' } }),
}));

beforeEach(() => {
  vi.useFakeTimers();
  sessionStorage.setItem(
    'framefetch-active-intent',
    JSON.stringify({ owner: 'poll-test-owner', id: intentFixture().id }),
  );
});
afterEach(() => {
  sessionStorage.removeItem('framefetch-active-intent');
  vi.useRealTimers();
});

it('reads a delayed terminal write after the original deadline without POST', async () => {
  const active = intentFixture({
    status: 'resolving',
    inspection_id: null,
    deadline: new Date(Date.now() - 1_000).toISOString(),
  });
  mockHttpResponses(active, { ...active, version: 3, status: 'expired' });
  const hook = renderHook(useDownloadIntent);
  await act(() => vi.advanceTimersByTimeAsync(1));
  expect(hook.result.current.snapshot?.status).toBe('resolving');
  await act(() => vi.advanceTimersByTimeAsync(5_010));
  expect(hook.result.current.snapshot?.status).toBe('expired');
  await act(() => vi.advanceTimersByTimeAsync(10_000));
  expect(httpRequests().map((request) => request.method)).toEqual([
    'GET',
    'GET',
  ]);
  expect(
    httpRequests().every((request) => request.url?.endsWith(active.id)),
  ).toBe(true);
});

it('reconciles a temporary read failure automatically and stops on cancellation', async () => {
  mockHttpError(new ApiError(503, 'request_failed', '暂不可用', '暂不可用'));
  mockHttpResponses(
    intentFixture({ status: 'cancelled', inspection_id: null }),
  );
  const hook = renderHook(useDownloadIntent);
  await act(() => vi.advanceTimersByTimeAsync(1));
  await act(() => vi.advanceTimersByTimeAsync(5_010));
  expect(hook.result.current.snapshot?.status).toBe('cancelled');
  await act(() => vi.advanceTimersByTimeAsync(10_000));
  expect(httpRequests().map((request) => request.method)).toEqual([
    'GET',
    'GET',
  ]);
});

it('does not keep querying an unavailable owner resource', async () => {
  mockHttpError(new ApiError(404, 'resource_not_found', '不存在', '不存在'));
  renderHook(useDownloadIntent);
  await act(() => vi.advanceTimersByTimeAsync(20_000));
  expect(httpRequests().map((request) => request.method)).toEqual(['GET']);
});

it('keeps reading while cancellation waits for confirmation', async () => {
  mockHttpResponses(
    intentFixture({ status: 'cancelling', inspection_id: null }),
    intentFixture({ status: 'cancelled', version: 3, inspection_id: null }),
  );
  const hook = renderHook(useDownloadIntent);
  await act(() => vi.advanceTimersByTimeAsync(1));
  expect(hook.result.current.pending).toBe(true);
  expect(hook.result.current.cancelling).toBe(true);
  await act(async () => {
    await hook.result.current.cancel();
    await hook.result.current.refresh();
    await hook.result.current.submit('https://youtu.be/replacement', true);
  });
  expect(httpRequests().map((request) => request.method)).toEqual(['GET']);
  await act(() => vi.advanceTimersByTimeAsync(2_010));
  expect(hook.result.current.snapshot?.status).toBe('cancelled');
  expect(hook.result.current.pending).toBe(false);
});

it('does not refresh a cancelled intent', async () => {
  mockHttpResponses(
    intentFixture({ status: 'cancelled', inspection_id: null }),
  );
  const hook = renderHook(useDownloadIntent);
  await act(() => vi.advanceTimersByTimeAsync(1));
  await act(async () => hook.result.current.refresh());
  expect(httpRequests().map((request) => request.method)).toEqual(['GET']);
});
