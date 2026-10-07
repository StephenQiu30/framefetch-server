import { afterEach, describe, expect, it, vi } from 'vitest';

import { PUT } from '@/app/storage-upload/route';
import {
  internalStorageTarget,
  resolveTarget,
} from '@/app/storage-upload/target';

const signedTarget =
  'https://storage.example/video-artifacts/file?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=signature';

describe('same-origin storage upload route', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it('allows only signed URLs on the configured storage origin', () => {
    vi.stubEnv('MINIO_PUBLIC_ENDPOINT', 'storage.example');
    vi.stubEnv('MINIO_PUBLIC_SECURE', 'true');

    expect(resolveTarget(signedTarget)?.toString()).toBe(signedTarget);
    expect(
      resolveTarget(
        'https://attacker.example/file?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=x',
      ),
    ).toBeNull();
    expect(resolveTarget('https://storage.example/file')).toBeNull();
  });

  it('streams the file to storage and returns only the ETag', async () => {
    vi.stubEnv('MINIO_PUBLIC_ENDPOINT', 'storage.example');
    vi.stubEnv('MINIO_PUBLIC_SECURE', 'true');
    const upstreamFetch = vi.fn().mockResolvedValue(
      new Response(null, {
        headers: { ETag: '0123456789abcdef0123456789abcdef' },
        status: 200,
      }),
    );
    vi.stubGlobal('fetch', upstreamFetch);
    const request = new Request('http://localhost:8101/storage-upload', {
      body: new Blob(['screenplay']),
      headers: {
        'Content-Type': 'text/plain',
        'X-Framefetch-Upload-Target': signedTarget,
      },
      method: 'PUT',
    });

    const response = await PUT(request as never);

    expect(response.status).toBe(200);
    expect(response.headers.get('etag')).toBe(
      '0123456789abcdef0123456789abcdef',
    );
    expect(upstreamFetch).toHaveBeenCalledWith(
      expect.objectContaining({ href: signedTarget }),
      expect.objectContaining({ method: 'PUT', redirect: 'error' }),
    );
  });

  it('rewrites a validated public URL to the configured internal endpoint', () => {
    vi.stubEnv('MINIO_ENDPOINT', 'minio.internal:9000');
    vi.stubEnv('MINIO_INTERNAL_SECURE', 'false');

    expect(internalStorageTarget(new URL(signedTarget)).toString()).toBe(
      signedTarget.replace(
        'https://storage.example',
        'http://minio.internal:9000',
      ),
    );
  });
});
