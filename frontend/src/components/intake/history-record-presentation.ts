import {
  analysisStatusVariant,
  isActiveAnalysisStatus,
  statusLabels,
} from '@/components/analysis/analysis-panel-model';
import {
  intentStatusVariant,
  intentTitle,
} from '@/components/intake/intent-status';
import {
  documentStatusLabels,
  documentStatusVariant,
} from '@/components/screenplay/screenplay-document-format';

export type HistoryRecord = API.HistoryRecordPageResponse['items'][number];
export function isAnalysisRecord(
  item: HistoryRecord,
): item is
  | API.VideoAnalysisHistoryRecordResponse
  | API.ScreenplayAnalysisHistoryRecordResponse
  | API.ContentCreationHistoryRecordResponse {
  return (
    item.record_type === 'video_analysis' ||
    item.record_type === 'screenplay_analysis' ||
    item.record_type === 'content_creation'
  );
}
export function historyRecordLabel(item: HistoryRecord) {
  if (item.record_type === 'parse') return '链接解析';
  if (item.record_type === 'document_parse') return '剧本基础解析';
  if (item.record_type === 'content_creation') return '内容创作';
  if (item.record_type === 'video_analysis') return '视频 AI 分析';
  return item.result_contract === 'screenplay-rewrite'
    ? '剧本 AI 改写'
    : '剧本 AI 分析';
}
export function historyRecordStatus(item: HistoryRecord) {
  if (isAnalysisRecord(item))
    return item.cancel_requested_at && isActiveAnalysisStatus(item.status)
      ? '正在取消'
      : `${statusLabels[item.status]}${isActiveAnalysisStatus(item.status) ? ` · ${item.progress}%` : ''}`;
  return item.record_type === 'document_parse'
    ? documentStatusLabels[item.status]
    : intentTitle(item.status);
}
export function historyRecordVariant(item: HistoryRecord) {
  if (isAnalysisRecord(item)) return analysisStatusVariant(item.status);
  return item.record_type === 'document_parse'
    ? documentStatusVariant(item.status)
    : intentStatusVariant(item.status);
}
export function historyRecordHref(
  item: Exclude<HistoryRecord, API.ParseHistoryRecordResponse>,
) {
  return item.record_type === 'document_parse'
    ? `/documents/detail?documentId=${encodeURIComponent(item.document_id)}`
    : `/analyses/detail?analysisId=${encodeURIComponent(item.id)}`;
}
export function historyPollingInterval(items: HistoryRecord[]) {
  if (items.some((item) => item.status_group === 'processing')) return 3000;
  return false;
}
