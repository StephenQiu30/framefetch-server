import {
  AxiosError,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { httpClient, request } from '@/lib/request';
import {
  advanceSessionGeneration,
  onSessionExpired,
} from '@/lib/session-events';

const originalAdapter = httpClient.defaults.adapter;
describe('opaque Web session failures', () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => {
    httpClient.defaults.adapter = originalAdapter;
  });
  it('never refreshes or replays a failed mutation', async () => {
    const expired = vi.fn();
    const unsubscribe = onSessionExpired(expired);
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => {
      throw new AxiosError(
        'Unauthorized',
        'ERR_BAD_REQUEST',
        config,
        undefined,
        response(config, { code: 'unauthenticated' }, 401),
      );
    });
    httpClient.defaults.adapter = adapter;
    try {
      await expect(
        request('/api/downloads', {
          method: 'POST',
          data: { inspection_id: 'job' },
        }),
      ).rejects.toMatchObject({ status: 401 });
      expect(adapter).toHaveBeenCalledOnce();
      expect(expired).toHaveBeenCalledOnce();
    } finally {
      unsubscribe();
    }
  });
  it.each([0, 403, 429, 500, 503, 504])(
    'preserves identity on dependency/network failure %s',
    async (status) => {
      const expired = vi.fn();
      const unsubscribe = onSessionExpired(expired);
      httpClient.defaults.adapter = async (config) => {
        throw new AxiosError(
          'Failed',
          'ERR_BAD_RESPONSE',
          config,
          undefined,
          status
            ? response(config, { code: 'service_unavailable' }, status)
            : undefined,
        );
      };
      try {
        await expect(request('/api/downloads/history')).rejects.toMatchObject({
          status,
        });
        expect(expired).not.toHaveBeenCalled();
      } finally {
        unsubscribe();
      }
    },
  );
  it('preserves identity when login rejects credentials', async () => {
    const expired = vi.fn();
    const unsubscribe = onSessionExpired(expired);
    httpClient.defaults.adapter = async (config) => {
      throw new AxiosError(
        'Failed',
        'ERR_BAD_RESPONSE',
        config,
        undefined,
        response(config, { code: 'invalid_credentials' }, 401),
      );
    };
    try {
      await expect(
        request('/api/auth/login', { method: 'POST' }),
      ).rejects.toMatchObject({ status: 401 });
      expect(expired).not.toHaveBeenCalled();
    } finally {
      unsubscribe();
    }
  });
  it('does not reinterpret a provider 401 as a Web identity failure', async () => {
    const expired = vi.fn();
    const unsubscribe = onSessionExpired(expired);
    httpClient.defaults.adapter = async (config) => {
      throw new AxiosError(
        'Failed',
        'ERR_BAD_RESPONSE',
        config,
        undefined,
        response(config, { code: 'login_required' }, 401),
      );
    };
    try {
      await expect(
        request('/api/inspections', { method: 'POST' }),
      ).rejects.toMatchObject({ status: 401 });
      expect(expired).not.toHaveBeenCalled();
    } finally {
      unsubscribe();
    }
  });
  it.each([200, 401])(
    'discards late responses from a previous identity (%s)',
    async (status) => {
      const expired = vi.fn();
      const unsubscribe = onSessionExpired(expired);
      httpClient.defaults.adapter = async (config) => {
        advanceSessionGeneration();
        const result = response(config, { code: 'unauthenticated' }, status);
        if (status === 401)
          throw new AxiosError(
            'Failed',
            'ERR_BAD_RESPONSE',
            config,
            undefined,
            result,
          );
        return result;
      };
      try {
        await expect(request('/api/downloads/history')).rejects.toMatchObject({
          code: 'ERR_CANCELED',
        });
        expect(expired).not.toHaveBeenCalled();
      } finally {
        unsubscribe();
      }
    },
  );
});
function response(
  config: InternalAxiosRequestConfig,
  data: unknown,
  status: number,
): AxiosResponse {
  return { config, data, headers: {}, status, statusText: 'Response' };
}
