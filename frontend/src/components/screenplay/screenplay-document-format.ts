import { ImportStatusCode } from '@/lib/import-status';

type DocumentStatusPresentation = {
  label: string;
  variant: 'secondary' | 'default' | 'destructive';
  previewMessage: string;
};

const documentStatusPresentation = {
  [ImportStatusCode.Uploading]: {
    label: '等待上传',
    variant: 'secondary',
    previewMessage: '文件上传完成后，这里会显示提取结果。',
  },
  [ImportStatusCode.Verifying]: {
    label: '正在解析',
    variant: 'secondary',
    previewMessage: '正在解析剧本文本，请稍后刷新。',
  },
  [ImportStatusCode.Ready]: {
    label: '可以核对',
    variant: 'default',
    previewMessage: '文档已解析，但当前没有可显示的预览。',
  },
  [ImportStatusCode.Failed]: {
    label: '解析失败',
    variant: 'destructive',
    previewMessage: '解析失败，未生成规范化剧本文本。',
  },
  [ImportStatusCode.Cancelled]: {
    label: '已取消',
    variant: 'secondary',
    previewMessage: '导入已取消，未生成剧本文本。',
  },
  [ImportStatusCode.Expired]: {
    label: '已过期',
    variant: 'secondary',
    previewMessage: '文档已过期，预览不再可用。',
  },
} satisfies Record<API.ImportStatus, DocumentStatusPresentation>;

export const documentStatusLabels = {
  [ImportStatusCode.Uploading]:
    documentStatusPresentation[ImportStatusCode.Uploading].label,
  [ImportStatusCode.Verifying]:
    documentStatusPresentation[ImportStatusCode.Verifying].label,
  [ImportStatusCode.Ready]:
    documentStatusPresentation[ImportStatusCode.Ready].label,
  [ImportStatusCode.Failed]:
    documentStatusPresentation[ImportStatusCode.Failed].label,
  [ImportStatusCode.Cancelled]:
    documentStatusPresentation[ImportStatusCode.Cancelled].label,
  [ImportStatusCode.Expired]:
    documentStatusPresentation[ImportStatusCode.Expired].label,
} satisfies Record<API.ImportStatus, string>;

export const documentFormatLabels: Record<API.DocumentSourceFormat, string> = {
  docx: 'DOCX',
  pdf: 'PDF',
  txt: '纯文本',
  markdown: 'Markdown',
  fountain: 'Fountain',
  srt: 'SRT 字幕',
  vtt: 'WebVTT 字幕',
};

const errorLabels: Record<API.ImportErrorCode, string> = {
  import_storage_unavailable: '文档存储暂时不可用，请稍后刷新。',
  upload_session_expired: '上传会话已过期。',
  upload_incomplete: '文件没有完整上传。',
  import_size_mismatch: '文件大小与上传声明不一致。',
  import_sha256_mismatch: '文件完整性校验未通过。',
  video_import_invalid: '上传内容不是受支持的视频。',
  document_format_unsupported: '该文档格式不受支持。',
  document_encrypted: '加密或受保护的文档无法解析。',
  document_archive_unsafe: '文档包含不安全的压缩包或外部内容。',
  document_text_unavailable: '没有提取到可用的剧本文本。',
  document_structure_invalid: '剧本文本结构无法安全解析。',
};

export function documentStatusVariant(
  status: API.ImportStatus,
): DocumentStatusPresentation['variant'] {
  return documentStatusPresentation[status].variant;
}

export function documentPreviewStatusMessage(status: API.ImportStatus): string {
  return documentStatusPresentation[status].previewMessage;
}

export function documentErrorLabel(
  document: API.DocumentDetailResponse,
): string | null {
  return document.error_code ? errorLabels[document.error_code] : null;
}

export function languageLabel(value: string | null): string {
  if (value === 'zh-CN') return '中文';
  if (value === 'en-US') return '英文';
  if (value === 'mixed') return '中英混合';
  if (value === 'unknown') return '未识别';
  return '等待解析';
}

export function qualityWarningLabel(value: string): string {
  if (value === 'scene_heading_missing') {
    return '未识别到明确场景标题，正文已作为单一场景处理。';
  }
  return '文档存在需要人工核对的结构问题。';
}

export function formatDocumentDate(value: string): string {
  return dateFormatter.format(new Date(value));
}

export function formatDocumentSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'medium',
  timeStyle: 'short',
});
