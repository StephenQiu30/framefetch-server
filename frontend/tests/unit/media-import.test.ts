import { afterEach, describe, expect, it, vi } from 'vitest';
import { importScreenplayDocument } from '@/lib/upload/document-import';
import { importLocalVideo } from '@/lib/upload/media-import';
import { hashFileSha256, uploadMultipartFile } from '@/lib/upload/media-upload';
import {
  httpRequests,
  mockHttpError,
  mockHttpResponses,
} from '../helpers/http';

const ETAG = '0123456789abcdef0123456789abcdef';

describe('local media import transport', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    FakeXMLHttpRequest.instances = [];
  });

  it('computes SHA-256 incrementally without changing the file', async () => {
    const progress: number[] = [];
    const file = new File(['abc'], 'sample.mp4', { type: 'video/mp4' });

    const digest = await hashFileSha256(
      file,
      (value) => progress.push(value),
      new AbortController().signal,
    );

    expect(digest).toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    );
    expect(progress).toEqual([100]);
    expect(await file.text()).toBe('abc');
  });

  it('uploads signed parts, reads ETag, and submits the exact manifest', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXMLHttpRequest);
    const resource = mediaImportResponse('uploading');
    const completed = mediaImportResponse('verifying');
    mockHttpResponses(resource, uploadSession(), completed);
    const phases: string[] = [];
    const progress: number[] = [];

    const result = await importLocalVideo(
      new File(['abc'], 'sample.mp4', { type: 'video/mp4' }),
      'stable-import-key',
      {
        onPhase: (phase) => phases.push(phase),
        onProgress: (value) => progress.push(value),
        onResource: vi.fn(),
      },
      new AbortController().signal,
      'wechat_channels',
    );

    expect(result).toEqual(completed);
    expect(phases).toEqual(['hashing', 'creating', 'uploading', 'completing']);
    expect(progress.at(-1)).toBe(100);
    expect(FakeXMLHttpRequest.instances[0]).toMatchObject({
      headers: {
        'X-Framefetch-Upload-Target': 'https://storage.example/upload-part-1',
      },
      method: 'PUT',
      url: '/storage-upload',
      timeout: expect.any(Number),
    });
    expect(httpRequests()).toMatchObject([
      {
        data: {
          file_name: 'sample.mp4',
          declared_size_bytes: 3,
          declared_sha256:
            'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
          rights_accepted: true,
          declared_origin: 'wechat_channels',
        },
        headers: { 'Idempotency-Key': 'stable-import-key' },
        method: 'POST',
        url: '/api/media-imports',
      },
      {
        headers: { 'X-Framefetch-Upload-Client': 'local-web' },
        method: 'POST',
        url: `/api/media-imports/${resource.id}/upload-sessions`,
      },
      {
        data: { parts: [{ part_number: 1, etag: ETAG }] },
        method: 'POST',
        url: `/api/media-imports/${resource.id}/complete`,
      },
    ]);
  });

  it('rejects a malformed upload session before sending file bytes', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXMLHttpRequest);

    await expect(
      uploadMultipartFile(
        new File(['abc'], 'sample.mp4', { type: 'video/mp4' }),
        { ...uploadSession(), part_count: 2 },
        vi.fn(),
        new AbortController().signal,
      ),
    ).rejects.toThrow('上传会话无效');
    expect(FakeXMLHttpRequest.instances).toHaveLength(0);
  });

  it.each(['verifying', 'ready'] as const)(
    'recovers an idempotent video already %s without reuploading',
    async (status) => {
      const resource = mediaImportResponse(status);
      mockHttpResponses(resource);
      const result = await importLocalVideo(
        new File(['abc'], 'sample.mp4', { type: 'video/mp4' }),
        'stable-import-key',
        { onPhase: vi.fn(), onProgress: vi.fn(), onResource: vi.fn() },
        new AbortController().signal,
      );
      expect(result).toEqual(resource);
      expect(httpRequests()).toHaveLength(1);
      expect(FakeXMLHttpRequest.instances).toHaveLength(0);
    },
  );

  it.each(['failed', 'cancelled', 'expired'] as const)(
    'does not reopen a terminal video upload: %s',
    async (status) => {
      mockHttpResponses(mediaImportResponse(status));
      await expect(
        importLocalVideo(
          new File(['abc'], 'sample.mp4', { type: 'video/mp4' }),
          'stable-import-key',
          { onPhase: vi.fn(), onProgress: vi.fn(), onResource: vi.fn() },
          new AbortController().signal,
        ),
      ).rejects.toThrow('重新选择文件');
      expect(httpRequests()).toHaveLength(1);
    },
  );

  it('rejects an upload session issued for another resource', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXMLHttpRequest);
    const resource = mediaImportResponse('uploading');
    mockHttpResponses(resource, {
      ...uploadSession(),
      resource_id: '22222222-2222-4222-8222-222222222222',
    });

    await expect(
      importLocalVideo(
        new File(['abc'], 'sample.mp4', { type: 'video/mp4' }),
        'stable-import-key',
        {
          onPhase: vi.fn(),
          onProgress: vi.fn(),
          onResource: vi.fn(),
        },
        new AbortController().signal,
      ),
    ).rejects.toThrow('上传会话与导入任务不匹配');
    expect(FakeXMLHttpRequest.instances).toHaveLength(0);
  });

  it('uploads a screenplay document and submits its source format', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXMLHttpRequest);
    const resource = documentImportResponse('uploading');
    const completed = documentImportResponse('verifying');
    mockHttpResponses(resource, documentUploadSession(), completed);

    const result = await importScreenplayDocument(
      new File(['INT. ROOM - DAY\n\nA story begins.'], 'story.fountain', {
        type: 'text/plain',
      }),
      'stable-document-key',
      {
        onPhase: vi.fn(),
        onProgress: vi.fn(),
        onResource: vi.fn(),
      },
      new AbortController().signal,
    );

    expect(result).toEqual(completed);
    expect(httpRequests()).toMatchObject([
      {
        data: expect.objectContaining({
          file_name: 'story.fountain',
          source_format: 'fountain',
          rights_accepted: true,
        }),
        headers: { 'Idempotency-Key': 'stable-document-key' },
        method: 'POST',
        url: '/api/documents',
      },
      {
        headers: { 'X-Framefetch-Upload-Client': 'local-web' },
        method: 'POST',
        url: `/api/documents/${resource.id}/upload-sessions`,
      },
      {
        data: { parts: [{ part_number: 1, etag: ETAG }] },
        method: 'POST',
        url: `/api/documents/${resource.id}/complete`,
      },
    ]);
  });

  it('lets the server accept a document above its default size limit', async () => {
    const file = new File([new Uint8Array(51 * 1024 ** 2)], 'story.fountain');
    const resource = {
      ...documentImportResponse('verifying'),
      declared_size_bytes: file.size,
    };
    mockHttpResponses(resource);

    const result = await importScreenplayDocument(
      file,
      'configured-document-limit',
      { onPhase: vi.fn(), onProgress: vi.fn(), onResource: vi.fn() },
      new AbortController().signal,
    );

    expect(result).toEqual(resource);
    expect(httpRequests()).toMatchObject([
      { url: '/api/documents', data: { declared_size_bytes: file.size } },
    ]);
    expect(FakeXMLHttpRequest.instances).toHaveLength(0);
  });

  it('stops before uploading when the server rejects a document', async () => {
    const error = new Error('deployment document size limit exceeded');
    mockHttpError(error);

    await expect(
      importScreenplayDocument(
        new File(['story'], 'story.fountain'),
        'configured-document-limit',
        { onPhase: vi.fn(), onProgress: vi.fn(), onResource: vi.fn() },
        new AbortController().signal,
      ),
    ).rejects.toBe(error);

    expect(httpRequests()).toHaveLength(1);
    expect(FakeXMLHttpRequest.instances).toHaveLength(0);
  });

  it('recovers an idempotent document whose completion response was lost', async () => {
    const completed = documentImportResponse('verifying');
    mockHttpResponses(completed);

    const result = await importScreenplayDocument(
      new File(['INT. ROOM - DAY\n\nA story begins.'], 'story.fountain', {
        type: 'text/plain',
      }),
      'stable-document-key',
      {
        onPhase: vi.fn(),
        onProgress: vi.fn(),
        onResource: vi.fn(),
      },
      new AbortController().signal,
    );

    expect(result).toEqual(completed);
    expect(httpRequests()).toHaveLength(1);
    expect(httpRequests()[0]).toMatchObject({
      method: 'POST',
      url: '/api/documents',
    });
  });
});

class FakeXMLHttpRequest {
  static instances: FakeXMLHttpRequest[] = [];
  readonly upload: { onprogress: ((event: ProgressEvent) => void) | null } = {
    onprogress: null,
  };
  method = '';
  url = '';
  headers: Record<string, string> = {};
  timeout = 0;
  status = 200;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  onabort: (() => void) | null = null;

  constructor() {
    FakeXMLHttpRequest.instances.push(this);
  }

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }

  getResponseHeader(name: string) {
    return name.toLocaleLowerCase('en-US') === 'etag' ? ETAG : null;
  }

  send(body: Blob) {
    this.upload.onprogress?.({
      lengthComputable: true,
      loaded: body.size,
    } as ProgressEvent);
    this.onload?.();
  }

  abort() {
    this.onabort?.();
  }
}

function uploadSession(): API.MediaUploadSessionResponse {
  return {
    resource_id: '11111111-1111-4111-8111-111111111111',
    attempt: 1,
    part_size_bytes: 5 * 1024 * 1024,
    part_count: 1,
    max_concurrency: 4,
    expires_at: new Date(Date.now() + 60_000).toISOString(),
    parts: [
      {
        part_number: 1,
        url: 'https://storage.example/upload-part-1',
      },
    ],
  };
}

function mediaImportResponse(
  status: API.ImportStatus,
): API.MediaImportResponse {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    download_id: '11111111-1111-4111-8111-111111111111',
    source_format: 'mp4',
    display_name: 'sample.mp4',
    declared_size_bytes: 3,
    status,
    attempt: status === 'uploading' ? 0 : 1,
    error_code: null,
    version: status === 'uploading' ? 0 : 1,
    created_at: '2026-08-14T00:00:00Z',
    updated_at: '2026-08-14T00:00:01Z',
    finished_at: null,
    declared_origin: 'user_file',
  };
}

function documentUploadSession(): API.DocumentUploadSessionResponse {
  return {
    ...uploadSession(),
    resource_id: '33333333-3333-4333-8333-333333333333',
  };
}

function documentImportResponse(
  status: API.ImportStatus,
): API.DocumentImportResponse {
  return {
    id: '33333333-3333-4333-8333-333333333333',
    source_format: 'fountain',
    original_filename: 'story.fountain',
    declared_size_bytes: 32,
    status,
    attempt: status === 'uploading' ? 0 : 1,
    error_code: null,
    version: status === 'uploading' ? 0 : 1,
    created_at: '2026-08-15T00:00:00Z',
    updated_at: '2026-08-15T00:00:01Z',
    finished_at: null,
  };
}
