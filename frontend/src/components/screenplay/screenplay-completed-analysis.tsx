import { DownloadSimple } from '@phosphor-icons/react';

import AnalysisDeleteDialog from '@/components/analysis/analysis-delete-dialog';
import { AnalysisReportStatusCode } from '@/components/analysis/analysis-panel-model';
import AnalysisReportDownloadLink from '@/components/analysis/analysis-report-download-link';
import AnalysisStorageNotice from '@/components/analysis/analysis-storage-notice';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { ScreenplayResultView } from '@/components/screenplay/screenplay-result-view';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

export function ScreenplayCompletedAnalysis({
  action,
  job,
  onDelete,
}: {
  action: string | null;
  job: API.AnalysisResponse;
  onDelete: () => Promise<void>;
}) {
  if (
    !job.result ||
    !['screenplay_analysis', 'screenplay_rewrite'].includes(job.result.kind)
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
    job.result.kind === 'screenplay_analysis'
      ? job.result.title
      : '剧本改写已完成';
  return (
    <>
      <div className="flex flex-col gap-6">
        <div className="min-w-0 w-full">
          <h2
            className="w-full text-xl font-semibold tracking-tight"
            id="screenplay-analysis-title"
          >
            {title}
          </h2>
          <p className="mt-3 text-sm text-muted-foreground">
            {job.result.kind === 'screenplay_rewrite'
              ? 'AI 改写 · 完整正文请在下方查看或导出'
              : 'AI 剧本故事审稿 · 请对照上方已上传的剧本原文核查结论'}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant="default">已完成</Badge>
          <span className="text-sm text-muted-foreground tabular-nums">
            第 {job.run_no} 次执行
          </span>
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
          description="结构化结果仍可查看；新任务请在内容工作台创建。"
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
