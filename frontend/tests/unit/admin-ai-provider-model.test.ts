import { describe, expect, it } from 'vitest';

import {
  isLocalCodexProvider,
  providerEngineDefaults,
  providerEngineLabel,
} from '@/components/admin/admin-ai-providers/model';

describe('AI Provider editor model', () => {
  it('keeps local Codex as the default route', () => {
    expect(isLocalCodexProvider('local-codex')).toBe(true);
    expect(isLocalCodexProvider('custom-codex')).toBe(false);
    expect(providerEngineDefaults('codex')).toEqual({
      authMode: 'host_login',
      baseUrl: '',
      model: '',
    });
  });

  it('requires the configured model instead of guessing a CLI default', () => {
    expect(providerEngineDefaults('codex').model).toBe('');
    expect(providerEngineDefaults('claude').model).toBe('');
  });

  it('configures DeepSeek through the Web API profile', () => {
    expect(providerEngineDefaults('deepseek')).toEqual({
      authMode: 'api_key',
      baseUrl: 'https://api.deepseek.com',
      model: 'deepseek-v4-flash-vision-exp',
    });
    expect(providerEngineLabel('deepseek')).toBe('DeepSeek');
  });
});

it('separates direct API routes from local CLI login', () => {
  expect(providerEngineDefaults('openrouter')).toEqual({
    authMode: 'api_key',
    baseUrl: 'https://openrouter.ai/api/v1',
    model: '',
  });
  expect(providerEngineDefaults('openai').authMode).toBe('api_key');
  expect(providerEngineLabel('openrouter')).toBe('OpenRouter');
  expect(providerEngineLabel('openai')).toBe('OpenAI 兼容 API');
});
