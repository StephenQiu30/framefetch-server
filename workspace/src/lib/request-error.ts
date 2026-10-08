import {
  localizedErrorMessage,
  statusErrorMessage,
} from '@/lib/error-messages';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly title: string,
    readonly detail: string,
  ) {
    super(detail);
    this.name = 'ApiError';
  }
}

export function displayError(error: unknown): string {
  if (!(error instanceof ApiError)) return '发生未知错误，请稍后重试。';
  return (
    localizedErrorMessage(error.code) ??
    (containsChinese(error.detail)
      ? error.detail
      : statusErrorMessage(error.status))
  );
}

export function apiErrorFrom(
  status: number,
  payload: unknown,
  fallbackDetail?: string,
): ApiError {
  const problem = parseErrorResponse(payload);
  if (problem) {
    return new ApiError(status, problem.code, problem.message, problem.message);
  }
  return new ApiError(
    status,
    'request_failed',
    '请求失败',
    fallbackDetail ??
      (status >= 500
        ? '服务暂时不可用，请稍后重试。'
        : '请求未能完成，请检查后重试。'),
  );
}

function parseErrorResponse(value: unknown): API.ErrorResponse | null {
  if (!value || typeof value !== 'object') return null;
  const error = value as Partial<API.ErrorResponse>;
  return typeof error.code === 'string' &&
    typeof error.message === 'string' &&
    error.data === null
    ? (error as API.ErrorResponse)
    : null;
}

function containsChinese(value: string): boolean {
  return /[\u3400-\u9fff]/u.test(value);
}
