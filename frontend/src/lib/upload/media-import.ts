import { cancelDownload as cancelDownloadRequest } from '@/api/downloads';
import {
  completeMediaImport as completeMediaImportRequest,
  createMediaImport as createMediaImportRequest,
  createMediaUploadSession as createMediaUploadSessionRequest,
} from '@/api/mediaImports';
import { ImportStatusCode } from '@/lib/import-status';
import type { ImportObserver } from '@/lib/upload/import-lifecycle';
import {
  hashFileSha256,
  MediaTransferError,
  uploadMultipartFile,
} from '@/lib/upload/media-upload';

export function validateLocalVideo(file: File): string | null {
  if (file.size <= 0) return '请选择包含内容的 MP4 视频。';
  if (!file.name.toLocaleLowerCase('en-US').endsWith('.mp4')) {
    return '当前只支持上传 MP4 视频。';
  }
  if (file.type && file.type.toLocaleLowerCase('en-US') !== 'video/mp4') {
    return '文件类型与 MP4 不一致，请重新选择。';
  }
  return null;
}

export async function importLocalVideo(
  file: File,
  idempotencyKey: string,
  observer: ImportObserver,
  signal: AbortSignal,
  declaredOrigin: API.DeclaredOrigin = 'user_file',
): Promise<API.MediaImportResponse> {
  observer.onPhase('hashing');
  observer.onProgress(0);
  const declaredSha256 = await hashFileSha256(
    file,
    observer.onProgress,
    signal,
  );

  observer.onPhase('creating');
  const resource = await createMediaImportRequest(
    {
      file_name: file.name,
      declared_size_bytes: file.size,
      declared_sha256: declaredSha256,
      rights_accepted: true,
      declared_origin: declaredOrigin,
    },
    { headers: { 'Idempotency-Key': idempotencyKey } },
  );
  observer.onResource(resource.id);
  if (
    resource.status === ImportStatusCode.Verifying ||
    resource.status === ImportStatusCode.Ready
  ) {
    return resource;
  }
  if (resource.status !== ImportStatusCode.Uploading) {
    throw new MediaTransferError('当前视频不能继续上传，请重新选择文件。');
  }

  const session = await createMediaUploadSessionRequest(
    {
      resource_id: encodeURIComponent(resource.id),
    },
    {
      headers: { 'X-Framefetch-Upload-Client': 'local-web' },
    },
  );
  if (session.resource_id !== resource.id) {
    throw new MediaTransferError('上传会话与导入任务不匹配，请重新开始上传。');
  }
  observer.onPhase('uploading');
  observer.onProgress(0);
  const parts = await uploadMultipartFile(
    file,
    session,
    observer.onProgress,
    signal,
  );

  observer.onPhase('completing');
  observer.onProgress(100);
  return completeMediaImportRequest(
    { resource_id: encodeURIComponent(resource.id) },
    { parts },
  );
}

export async function cancelLocalVideoImport(
  resourceId: string,
): Promise<void> {
  await cancelDownloadRequest({ job_id: encodeURIComponent(resourceId) });
}
