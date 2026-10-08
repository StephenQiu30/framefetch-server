import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios';

import { apiErrorFrom } from '@/lib/request-error';
import { reportSessionExpired, sessionGeneration } from '@/lib/session-events';

const API_TIMEOUT_MS = 30_000;

enum ApiErrorCode {
  Unauthenticated = 'unauthenticated',
}

const UNAUTHENTICATED_ERROR_CODE: API.ErrorCode = ApiErrorCode.Unauthenticated;

export type RequestOptions = AxiosRequestConfig & {
  getResponse?: boolean;
  skipErrorHandler?: boolean;
};

type SessionRequestConfig = AxiosRequestConfig & {
  sessionGeneration?: number;
};

export const httpClient: AxiosInstance = axios.create({
  timeout: API_TIMEOUT_MS,
  withCredentials: true,
  headers: {
    Accept: 'application/json',
    'X-Client-Platform': 'web',
  },
});

httpClient.interceptors.request.use((config) => {
  const sessionConfig = config as SessionRequestConfig;
  sessionConfig.sessionGeneration ??= sessionGeneration();
  return config;
});

httpClient.interceptors.response.use(
  (response) => {
    assertCurrentSession(response.config as SessionRequestConfig);
    return response;
  },
  async (error: unknown) => {
    if (axios.isCancel(error) || !axios.isAxiosError(error))
      return Promise.reject(error);

    const config = error.config as SessionRequestConfig | undefined;
    if (config) assertCurrentSession(config);
    if (
      config &&
      error.response?.status === 401 &&
      error.response.data?.code === UNAUTHENTICATED_ERROR_CODE
    ) {
      reportSessionExpired(config.sessionGeneration ?? sessionGeneration());
    }

    if (!error.response) {
      return Promise.reject(
        apiErrorFrom(0, null, '网络连接失败，请检查网络后重试。'),
      );
    }
    return Promise.reject(
      apiErrorFrom(error.response.status, error.response.data),
    );
  },
);

function assertCurrentSession(config: SessionRequestConfig): void {
  if (
    config.sessionGeneration !== undefined &&
    config.sessionGeneration !== sessionGeneration()
  ) {
    throw new axios.CanceledError('Session changed');
  }
}

type ResponseData<T> = T extends {
  code: string;
  message: string;
  data: infer D;
}
  ? D
  : T;

export async function request<T>(
  url: string,
  options: RequestOptions = {},
): Promise<ResponseData<T>> {
  if (!url.startsWith('/') || url.startsWith('//')) {
    throw new TypeError('Only same-origin API paths are allowed.');
  }
  const {
    getResponse: _getResponse,
    skipErrorHandler: _skip,
    ...config
  } = options;
  const response = await httpClient.request<T>({ url, ...config });
  const payload = response.data;
  if (
    payload &&
    typeof payload === 'object' &&
    'code' in payload &&
    'message' in payload &&
    'data' in payload
  ) {
    return payload.data as ResponseData<T>;
  }
  return payload as ResponseData<T>;
}
