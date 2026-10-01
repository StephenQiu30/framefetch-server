export type AiProviderEditorState = {
  mode: 'create' | 'edit' | null;
  key: string;
  displayName: string;
  engine: API.AiProviderEngine;
  authMode: API.AiProviderAuthMode;
  baseUrl: string;
  model: string;
  apiKey: string;
  credentialConfigured: boolean;
  error: string;
  saving: boolean;
};

const LOCAL_CODEX_PROVIDER_KEY = 'local-codex';

export function isLocalCodexProvider(key: string): boolean {
  return key === LOCAL_CODEX_PROVIDER_KEY;
}

export const EMPTY_AI_PROVIDER_EDITOR: AiProviderEditorState = {
  mode: null,
  key: '',
  displayName: '',
  engine: 'codex',
  authMode: 'host_login',
  baseUrl: '',
  model: '',
  apiKey: '',
  credentialConfigured: false,
  error: '',
  saving: false,
};

export function providerEngineDefaults(
  engine: API.AiProviderEngine,
): Pick<AiProviderEditorState, 'authMode' | 'baseUrl' | 'model'> {
  if (engine === 'openrouter' || engine === 'openai') {
    return {
      authMode: 'api_key',
      baseUrl: providerApiBaseUrl(engine),
      model: '',
    };
  }
  if (engine === 'deepseek') {
    return {
      authMode: 'api_key',
      baseUrl: providerApiBaseUrl(engine),
      // The backend vision adapter accepts this model exclusively.
      model: 'deepseek-v4-flash-vision-exp',
    };
  }
  return {
    authMode: 'host_login',
    baseUrl: '',
    model: '',
  };
}

export function providerEngineLabel(engine: API.AiProviderEngine): string {
  return ENGINE_LABELS[engine];
}

const ENGINE_LABELS = {
  codex: 'Codex',
  claude: 'Claude',
  openrouter: 'OpenRouter',
  openai: 'OpenAI 兼容 API',
  deepseek: 'DeepSeek',
} satisfies Record<API.AiProviderEngine, string>;

// Protocol endpoints are shared by the editor defaults and URL hints.
const API_BASE_URLS = {
  codex: 'https://api.openai.com/v1',
  claude: 'https://api.anthropic.com',
  openrouter: 'https://openrouter.ai/api/v1',
  openai: 'https://api.openai.com/v1',
  deepseek: 'https://api.deepseek.com',
} satisfies Record<API.AiProviderEngine, string>;

export function providerApiBaseUrl(engine: API.AiProviderEngine): string {
  return API_BASE_URLS[engine];
}

export function isDirectApiEngine(engine: API.AiProviderEngine): boolean {
  return (
    engine === 'openrouter' || engine === 'openai' || engine === 'deepseek'
  );
}
