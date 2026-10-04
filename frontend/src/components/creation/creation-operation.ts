import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex } from '@noble/hashes/utils.js';
import { ApiError } from '@/lib/request-error';
import { createUuid } from '@/lib/uuid';

const prefix = 'framefetch-creation-intent:';

/** Persist only a digest and operation ID, never the user's material body. */
export function creationIdempotencyKey(scope: string, input: unknown): string {
  const fingerprint = bytesToHex(
    sha256(new TextEncoder().encode(JSON.stringify(input))),
  );
  try {
    const stored = sessionStorage.getItem(`${prefix}${scope}`);
    if (stored) {
      const prior: unknown = JSON.parse(stored);
      if (
        prior &&
        typeof prior === 'object' &&
        'fingerprint' in prior &&
        'key' in prior &&
        prior.fingerprint === fingerprint &&
        typeof prior.key === 'string'
      )
        return prior.key;
    }
    const key = createUuid();
    sessionStorage.setItem(
      `${prefix}${scope}`,
      JSON.stringify({ fingerprint, key }),
    );
    return key;
  } catch {
    throw new ApiError(
      409,
      'creation_session_storage_unavailable',
      '无法保留提交标记',
      '浏览器无法保留本次提交标记。请恢复会话存储后再提交，避免结果不明的请求被重复创建。',
    );
  }
}

export function completeCreationOperation(scope: string): void {
  sessionStorage.removeItem(`${prefix}${scope}`);
}
