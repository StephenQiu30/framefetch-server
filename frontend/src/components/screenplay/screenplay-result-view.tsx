import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import AnalysisStructuredReportView from '@/components/analysis/analysis-structured-report-view';
import ScreenplayAnalysisResultView from '@/components/screenplay/screenplay-analysis-result-view';
import ScreenplayRewriteResultView from '@/components/screenplay/screenplay-rewrite-result-view';

export function ScreenplayResultView({
  reportMarkdown,
  result,
}: {
  reportMarkdown?: string | null;
  result: NonNullable<API.AnalysisResponse['result']>;
}) {
  if (result.kind === 'skill_report') {
    return (
      <div className="mt-10">
        <AnalysisReportPreview markdown={reportMarkdown ?? ''} />
      </div>
    );
  }
  if (result.kind === 'screenplay_analysis') {
    return (
      <ScreenplayAnalysisResultView
        reportMarkdown={reportMarkdown}
        result={result}
      />
    );
  }
  if (result.kind === 'screenplay_rewrite') {
    return (
      <ScreenplayRewriteResultView
        reportMarkdown={reportMarkdown}
        result={result}
      />
    );
  }
  if (result.kind === 'structured_report' && result.media == null) {
    return (
      <AnalysisStructuredReportView
        reportMarkdown={reportMarkdown}
        result={result}
      />
    );
  }
  return null;
}
