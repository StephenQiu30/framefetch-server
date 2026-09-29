'use client';

import AnalysisArticleResultView from '@/components/analysis/analysis-article-result-view';
import AnalysisResultView from '@/components/analysis/analysis-result-view';
import AnalysisStructuredReportView from '@/components/analysis/analysis-structured-report-view';

type AnyAnalysisResult = NonNullable<API.AnalysisResponse['result']>;

export type VideoAnalysisResult = Extract<
  AnyAnalysisResult,
  { kind: 'video_visual_analysis' | 'video_article' | 'structured_report' }
>;

const VIDEO_RESULT_KINDS: ReadonlySet<AnyAnalysisResult['kind']> = new Set([
  'video_visual_analysis',
  'video_article',
  'structured_report',
]);

/** Video results have timecoded evidence and video report exports. */
export function isVideoAnalysisResult(
  result: AnyAnalysisResult | null | undefined,
): result is VideoAnalysisResult {
  return result != null && VIDEO_RESULT_KINDS.has(result.kind);
}

/** The one place that maps a video result contract to its view. */
export default function AnalysisVideoResult({
  onSelectTime,
  reportMarkdown,
  result,
  skillId,
}: {
  onSelectTime?: (milliseconds: number) => void;
  reportMarkdown?: string | null;
  result: VideoAnalysisResult;
  skillId?: string;
}) {
  switch (result.kind) {
    case 'video_article':
      return (
        <AnalysisArticleResultView
          onSelectTime={onSelectTime}
          reportMarkdown={reportMarkdown}
          result={result}
        />
      );
    case 'structured_report':
      return (
        <AnalysisStructuredReportView
          onSelectTime={onSelectTime}
          reportMarkdown={reportMarkdown}
          result={result}
        />
      );
    case 'video_visual_analysis':
      return (
        <AnalysisResultView
          onSelectTime={onSelectTime}
          defaultView={skillId === 'scene-extraction' ? 'scenes' : 'shots'}
          reportMarkdown={reportMarkdown}
          result={result}
        />
      );
  }
}
