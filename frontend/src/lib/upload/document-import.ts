import {
  cancelDocumentImport,
  completeDocumentImport,
  createDocumentImport,
  createDocumentUploadSession,
} from '@/api/documents';
import { ImportStatusCode } from '@/lib/import-status';
import type { ImportObserver } from '@/lib/upload/import-lifecycle';
import {
  hashFileSha256,
  MediaTransferError,
  uploadMultipartFile,
} from '@/lib/upload/media-upload';

const formats = new Map<string, API.DocumentSourceFormat>([
  ['.docx', 'docx'],
  ['.fountain', 'fountain'],
  ['.srt', 'srt'],
  ['.vtt', 'vtt'],
  ['.markdown', 'markdown'],
  ['.md', 'markdown'],
  ['.pdf', 'pdf'],
  ['.txt', 'txt'],
]);

export function validateScreenplayDocument(file: File): string | null {
  if (file.size <= 0) return '请选择包含内容的剧本文档。';
  // The deployment's document_import_max_bytes is enforced when creating
  // the import, before an upload session can be issued.
  if (!documentSourceFormat(file.name)) {
    return '支持 DOCX、PDF、TXT、Markdown、Fountain、SRT 和 WebVTT 文件。';
  }
  return null;
}

export async function importScreenplayDocument(
  file: File,
  idempotencyKey: string,
  observer: ImportObserver,
  signal: AbortSignal,
): Promise<API.DocumentImportResponse> {
  const sourceFormat = documentSourceFormat(file.name);
  const validationError = validateScreenplayDocument(file);
  if (!sourceFormat || validationError) {
    throw new MediaTransferError(validationError ?? '剧本文档格式无效。');
  }

  observer.onPhase('hashing');
  observer.onProgress(0);
  const declaredSha256 = await hashFileSha256(
    file,
    observer.onProgress,
    signal,
  );

  observer.onPhase('creating');
  const resource = await createDocumentImport(
    {
      file_name: file.name,
      source_format: sourceFormat,
      declared_size_bytes: file.size,
      declared_sha256: declaredSha256,
      rights_accepted: true,
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
    throw new MediaTransferError('当前剧本文档不能继续上传，请重新选择文件。');
  }

  const session = await createDocumentUploadSession(
    {
      document_id: encodeURIComponent(resource.id),
    },
    {
      headers: { 'X-FrameFetch-Upload-Client': 'local-web' },
    },
  );
  if (session.resource_id !== resource.id) {
    throw new MediaTransferError('上传会话与剧本文档不匹配，请重新开始。');
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
  return completeDocumentImport(
    { document_id: encodeURIComponent(resource.id) },
    { parts },
  );
}

export async function cancelScreenplayDocumentImport(
  documentId: string,
): Promise<void> {
  await cancelDocumentImport({ document_id: encodeURIComponent(documentId) });
}

function documentSourceFormat(name: string): API.DocumentSourceFormat | null {
  const normalized = name.toLocaleLowerCase('en-US');
  for (const [extension, format] of formats) {
    if (normalized.endsWith(extension)) return format;
  }
  return null;
}
