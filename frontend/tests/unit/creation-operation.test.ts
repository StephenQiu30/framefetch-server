import { describe, expect, it } from 'vitest';
import {
  completeCreationOperation,
  creationIdempotencyKey,
} from '@/components/creation/creation-operation';
import { ApiError } from '@/lib/request-error';

describe('creation durable submission intent', () => {
  it('retains the same operation through request uncertainty without persisting material text', () => {
    const body = {
      text: '不应进入会话存储的作者原文',
      revision_id: 'known-revision',
    };
    const key = creationIdempotencyKey('task', body);
    expect(creationIdempotencyKey('task', body)).toBe(key);
    expect(
      sessionStorage.getItem('framefetch-creation-intent:task'),
    ).not.toContain(body.text);
    expect(sessionStorage.getItem('framefetch-creation-intent:task')).toContain(
      'fingerprint',
    );
  });

  it('starts a new explicitly requested operation after a known successful response', () => {
    const key = creationIdempotencyKey('task', { text: '相同内容' });
    completeCreationOperation('task');
    expect(creationIdempotencyKey('task', { text: '相同内容' })).not.toBe(key);
  });

  it('stops when the stored submission record cannot be decoded', () => {
    sessionStorage.setItem('framefetch-creation-intent:task', 'broken-json');
    expect(() => creationIdempotencyKey('task', { text: '相同内容' })).toThrow(
      ApiError,
    );
  });
});
