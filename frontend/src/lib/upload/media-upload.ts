import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex } from '@noble/hashes/utils.js';

const HASH_CHUNK_BYTES = 4 * 1024 * 1024;
const ETAG_PATTERN = /^(?:[0-9a-f]{32}|"[0-9a-f]{32}")$/iu;
const UPLOAD_PROXY_PATH = '/storage-upload';
const UPLOAD_TARGET_HEADER = 'X-Framefetch-Upload-Target';

export class MediaTransferError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'MediaTransferError';
  }
}

export async function hashFileSha256(
  file: File,
  onProgress: (percentage: number) => void,
  signal: AbortSignal,
): Promise<string> {
  const hash = sha256.create();
  try {
    for (let offset = 0; offset < file.size; offset += HASH_CHUNK_BYTES) {
      throwIfAborted(signal);
      const end = Math.min(offset + HASH_CHUNK_BYTES, file.size);
      const chunk = await file.slice(offset, end).arrayBuffer();
      throwIfAborted(signal);
      hash.update(new Uint8Array(chunk));
      onProgress(Math.floor((end / file.size) * 100));
    }
    return bytesToHex(hash.digest());
  } catch (error) {
    hash.destroy();
    throw error;
  }
}

export async function uploadMultipartFile(
  file: File,
  session: MultipartUploadSession,
  onProgress: (percentage: number) => void,
  signal: AbortSignal,
): Promise<API.CompletedPartRequest[]> {
  const parts = validateSession(file, session);
  const controller = new AbortController();
  const abortUploads = () => controller.abort();
  if (signal.aborted) controller.abort();
  else signal.addEventListener('abort', abortUploads, { once: true });
  const completed = new Array<API.CompletedPartRequest>(parts.length);
  const loadedByPart = new Map<number, number>();
  let cursor = 0;

  const report = (partNumber: number, loaded: number) => {
    loadedByPart.set(partNumber, loaded);
    const total = [...loadedByPart.values()].reduce(
      (sum, value) => sum + value,
      0,
    );
    onProgress(Math.min(100, Math.floor((total / file.size) * 100)));
  };
  const worker = async () => {
    while (cursor < parts.length) {
      const index = cursor;
      cursor += 1;
      const target = parts[index];
      const start = (target.part_number - 1) * session.part_size_bytes;
      const body = file.slice(
        start,
        Math.min(start + session.part_size_bytes, file.size),
      );
      const etag = await uploadPart(
        target.url,
        body,
        Date.parse(session.expires_at),
        (loaded) => report(target.part_number, loaded),
        controller.signal,
      );
      report(target.part_number, body.size);
      completed[index] = { part_number: target.part_number, etag };
    }
  };

  try {
    await Promise.all(
      Array.from(
        { length: Math.min(session.max_concurrency, parts.length) },
        () => worker(),
      ),
    );
    return completed;
  } catch (error) {
    controller.abort();
    throw error;
  } finally {
    signal.removeEventListener('abort', abortUploads);
  }
}

function validateSession(
  file: File,
  session: MultipartUploadSession,
): API.UploadPartResponse[] {
  const expectedCount = Math.ceil(file.size / session.part_size_bytes);
  if (
    !Number.isSafeInteger(session.part_size_bytes) ||
    session.part_size_bytes < 5 * 1024 * 1024 ||
    !Number.isSafeInteger(session.part_count) ||
    session.part_count !== expectedCount ||
    session.parts.length !== expectedCount ||
    !Number.isSafeInteger(session.max_concurrency) ||
    session.max_concurrency < 1 ||
    session.max_concurrency > 16 ||
    !Number.isFinite(Date.parse(session.expires_at))
  ) {
    throw new MediaTransferError('上传会话无效，请重新开始上传。');
  }
  const parts = [...session.parts].sort(
    (left, right) => left.part_number - right.part_number,
  );
  for (const [index, part] of parts.entries()) {
    let url: URL;
    try {
      url = new URL(part.url);
    } catch {
      throw new MediaTransferError('上传地址无效，请重新开始上传。');
    }
    if (
      part.part_number !== index + 1 ||
      !['http:', 'https:'].includes(url.protocol) ||
      url.username ||
      url.password
    ) {
      throw new MediaTransferError('上传地址无效，请重新开始上传。');
    }
  }
  return parts;
}

type MultipartUploadSession = Pick<
  API.MediaUploadSessionResponse,
  | 'expires_at'
  | 'max_concurrency'
  | 'part_count'
  | 'part_size_bytes'
  | 'parts'
  | 'resource_id'
>;

function uploadPart(
  url: string,
  body: Blob,
  expiresAt: number,
  onProgress: (loaded: number) => void,
  signal: AbortSignal,
): Promise<string> {
  return new Promise((resolve, reject) => {
    throwIfAborted(signal);
    const remaining = expiresAt - Date.now();
    if (remaining <= 0) {
      reject(new MediaTransferError('上传会话已过期，请重新上传。'));
      return;
    }
    const request = new XMLHttpRequest();
    const abort = () => request.abort();
    const finish = (callback: () => void) => {
      signal.removeEventListener('abort', abort);
      callback();
    };
    request.open('PUT', UPLOAD_PROXY_PATH);
    request.setRequestHeader(UPLOAD_TARGET_HEADER, url);
    request.timeout = remaining;
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded);
    };
    request.onload = () => {
      const etag = request.getResponseHeader('ETag')?.trim() ?? '';
      if (
        request.status >= 200 &&
        request.status < 300 &&
        ETAG_PATTERN.test(etag)
      ) {
        finish(() => resolve(etag));
        return;
      }
      finish(() =>
        reject(new MediaTransferError('视频分片上传失败，请检查网络后重试。')),
      );
    };
    request.onerror = () =>
      finish(() =>
        reject(new MediaTransferError('无法连接文件存储，请检查网络后重试。')),
      );
    request.ontimeout = () =>
      finish(() =>
        reject(new MediaTransferError('上传会话已过期，请重新上传。')),
      );
    request.onabort = () => finish(() => reject(abortError()));
    signal.addEventListener('abort', abort, { once: true });
    request.send(body);
  });
}

function throwIfAborted(signal: AbortSignal): void {
  if (signal.aborted) throw abortError();
}

function abortError(): DOMException {
  return new DOMException('Media upload aborted', 'AbortError');
}
