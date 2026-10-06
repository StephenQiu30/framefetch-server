import { ArrowClockwise, DownloadSimple } from '@phosphor-icons/react';
import AnalysisDeleteDialog from '@/components/analysis/analysis-delete-dialog';
import { AnalysisReportStatusCode } from '@/components/analysis/analysis-panel-model';
import AnalysisReportDownloadLink from '@/components/analysis/analysis-report-download-link';
import AnalysisStorageNotice from '@/components/analysis/analysis-storage-notice';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { ScreenplayResultView } from '@/components/screenplay/screenplay-result-view';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ItemDescription, ItemTitle } from '@/components/ui/item';
import { Spinner } from '@/components/ui/spinner';

export function ScreenplayCompletedAnalysis({
  action,
  job,
  onDelete,
  onRetry,
  onNewAnalysis,
}: {
  action: string | null;
  job: API.AnalysisResponse;
  onDelete: () => Promise<void>;
  onRetry: () => Promise<void>;
  onNewAnalysis: () => void;
}) {
  const legacyReport = job.result?.kind === 'skill_report';
  if (
    !job.result ||
    (!legacyReport &&
      !['screenplay_analysis', 'screenplay_rewrite'].includes(
        job.result.kind,
      ) &&
      !(
        job.input_kind === 'screenplay' &&
        job.result.kind === 'structured_report' &&
        job.result.media == null
      ))
  ) {
    return null;
  }
  const formats = new Set(
    job.report?.status === AnalysisReportStatusCode.Available
      ? job.report.artifacts.map((artifact) => artifact.format)
      : [],
  );
  const reportAvailable = formats.has('markdown') && formats.has('docx');
  const title =
    job.result.kind === 'skill_report' ||
    job.result.kind === 'screenplay_analysis' ||
    job.result.kind === 'structured_report'
      ? job.result.title
      : '剧本改写已完成';
  return (
    <>
      <div className="flex flex-col gap-6">
        <div className="min-w-0 w-full">
          <ItemTitle className="line-clamp-none">
            <h2 className="w-full" id="screenplay-analysis-title">
              {title}
            </h2>
          </ItemTitle>
          <ItemDescription className="line-clamp-none mt-3">
            {legacyReport
              ? '历史 Skill 报告 · 仅展示已保存的报告正文'
              : job.result.kind === 'screenplay_rewrite'
                ? 'AI 改写 · 完整正文请在下方查看或导出'
                : job.result.kind === 'structured_report'
                  ? '文档整理 · 请对照上方已上传的原文核查结构与引用'
                  : 'AI 剧本故事审稿 · 请对照上方已上传的剧本原文核查结论'}
          </ItemDescription>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant="default">已完成</Badge>
          <span className="tabular-nums">第 {job.run_no} 次执行</span>
          {reportAvailable ? (
            <>
              <Button asChild variant="outline">
                <AnalysisReportDownloadLink
                  download={`screenplay-analysis-${job.id}.md`}
                  analysisId={job.id}
                  format="md"
                >
                  <DownloadSimple aria-hidden data-icon="inline-start" />
                  导出 Markdown
                </AnalysisReportDownloadLink>
              </Button>
              <Button asChild>
                <AnalysisReportDownloadLink
                  download={`screenplay-analysis-${job.id}.docx`}
                  analysisId={job.id}
                  format="docx"
                >
                  <DownloadSimple aria-hidden data-icon="inline-start" />
                  导出 DOCX
                </AnalysisReportDownloadLink>
              </Button>
            </>
          ) : null}
          <Button
            disabled={
              Boolean(action) ||
              legacyReport ||
              job.error_code === 'analysis_outcome_unknown'
            }
            onClick={() => void onRetry()}
            variant="outline"
          >
            {action === 'retry' ? (
              <Spinner aria-hidden data-icon="inline-start" />
            ) : (
              <ArrowClockwise aria-hidden data-icon="inline-start" />
            )}
            {action === 'retry' ? '正在重新执行' : '重新执行'}
          </Button>
          <Button
            disabled={Boolean(action)}
            onClick={onNewAnalysis}
            variant="outline"
          >
            使用最新 Skill 新建任务
          </Button>
          <AnalysisDeleteDialog
            disabled={Boolean(action)}
            busy={action === 'delete'}
            onDelete={onDelete}
          />
        </div>
      </div>
      {!reportAvailable ? (
        <FeedbackNotice
          className="mt-8"
          description={
            legacyReport
              ? '历史报告仅保留已保存的正文；请使用最新 Skill 新建任务以分析这份文档。'
              : '结构化结果仍可查看；重新执行后会生成新的 Markdown 和 DOCX。'
          }
          title="报告已清理或暂时不可用"
          tone="error"
        />
      ) : null}
      <div className="mt-5">
        <AnalysisStorageNotice />
      </div>
      <ScreenplayResultView
        reportMarkdown={job.report_markdown}
        result={job.result}
      />
    </>
  );
}
