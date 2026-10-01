import { describe, expect, it } from 'vitest';

import { ApiError, apiErrorFrom, displayError } from '@/lib/request-error';

describe('request errors', () => {
  it('converts unified error responses into ApiError', () => {
    const error = apiErrorFrom(409, {
      code: 'idempotency_conflict',
      data: null,
      message: '同一请求键不能用于不同负载。',
    });

    expect(error).toMatchObject({
      code: 'idempotency_conflict',
      detail: '同一请求键不能用于不同负载。',
      status: 409,
      title: '同一请求键不能用于不同负载。',
    });
  });

  it('uses safe fallback messages for unknown failures', () => {
    const error = apiErrorFrom(502, { title: 'Incomplete' });
    expect(error.detail).toBe('服务暂时不可用，请稍后重试。');
    expect(displayError(new Error('secret upstream detail'))).toBe(
      '发生未知错误，请稍后重试。',
    );
    expect(displayError(apiError(0, 'x', 'x', '安全信息'))).toBe('安全信息');
    expect(
      displayError(apiError(502, 'unknown_upstream', 'Bad gateway', 'Failed')),
    ).toBe('上游服务暂时不可用，请稍后重试。');
  });

  it('localizes the stable backend validation error', () => {
    expect(
      displayError(
        apiError(
          422,
          'invalid_request',
          'Invalid request',
          'The request parameters are invalid.',
        ),
      ),
    ).toBe('提交内容不符合要求，请检查各字段后重试。');
  });

  it.each([
    ['invalid_credentials', '邮箱或密码错误，请重新输入。'],
    ['transient', '连接媒体平台时发生临时故障，请稍后重试。'],
    ['import_disabled', '当前部署未开放本地视频上传。'],
    ['challenge', '平台要求验证，当前无法继续读取媒体。'],
    [
      'identity_unavailable',
      '平台登录材料暂不可用，请检查部署主机的登录状态后重新解析。',
    ],
    ['rate_limited', '操作过于频繁，请稍后再试。'],
    ['context_changed', '媒体执行上下文已变化，请重新解析链接并确认下载规格。'],
    [
      'duration_limit_exceeded',
      '该平台支持下载，但当前内容超出单次处理的安全边界。',
    ],
    ['analysis_cli_not_authenticated', 'AI 分析服务未登录，请完成登录后重试。'],
    [
      'reserved_ai_provider_mutation',
      '本机 Codex 是系统兜底线路，只能修改显示名称和模型。',
    ],
  ])('localizes the stable %s error', (code, expected) => {
    expect(
      displayError(apiError(400, code, 'English title', 'English detail')),
    ).toBe(expected);
  });
});

function apiError(status: number, code: string, title: string, detail: string) {
  return new ApiError(status, code, title, detail);
}
