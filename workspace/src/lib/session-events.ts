import { ApiError } from '@/lib/request-error';

// The identity owner advances this generation on login/logout. Requests carry
// it so a response from an old identity cannot invalidate the current one.
let generation = 0;
const listeners = new Set<() => void>();
const generationListeners = new Set<() => void>();

export function sessionGeneration(): number {
  return generation;
}

export function advanceSessionGeneration(): void {
  generation += 1;
  for (const listener of generationListeners) listener();
}

export function onSessionGenerationChanged(listener: () => void): () => void {
  generationListeners.add(listener);
  return () => {
    generationListeners.delete(listener);
  };
}

export function reportSessionExpired(expectedGeneration: number): void {
  if (expectedGeneration !== generation) return;
  for (const listener of listeners) listener();
}

export function onSessionExpired(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

// Only explicit Cookie writers coordinate. Ordinary reads never acquire a lock
// and no business request is replayed. Production uses HTTPS; localhost is also
// a secure context. Do not silently race Cookie writes in unsupported browsers.
export async function withWebSessionMutation<T>(
  action: () => Promise<T>,
): Promise<T> {
  if (typeof navigator === 'undefined' || !navigator.locks) {
    throw new ApiError(
      503,
      'browser_session_unavailable',
      'Browser session unavailable',
      '请通过 HTTPS 或 localhost 访问，并使用支持 Web Locks 的现代浏览器。',
    );
  }
  const expected = sessionGeneration();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30_000);
  try {
    return await navigator.locks.request(
      'framefetch-web-session-write',
      { signal: controller.signal },
      async () => {
        clearTimeout(timer);
        if (expected !== sessionGeneration()) {
          throw new ApiError(
            409,
            'session_changed',
            'Session changed',
            '登录状态已在其他页面更新，请重试。',
          );
        }
        return action();
      },
    );
  } catch (error) {
    if (controller.signal.aborted) {
      throw new ApiError(
        409,
        'session_busy',
        'Session busy',
        '另一个页面正在完成登录操作，请稍后重试。',
      );
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
