'use client';

import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import ContentReportHistory from '@/components/content/content-report-history';
import ContentSourceReview from '@/components/content/content-source-review';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

export default function ContentResultView({
  result,
  markdown,
  analysisId,
  reportId,
  historicalEdit = false,
}: {
  analysisId: string;
  reportId: string | null;
  historicalEdit?: boolean;
  result: API.ContentDocumentResult;
  markdown?: string | null;
}) {
  const review = result.review_history.at(-1);
  return (
    <div className="mt-8 grid gap-6">
      {historicalEdit || result.review_status !== 'passed' ? (
        <Alert>
          <AlertTitle>
            {historicalEdit
              ? '历史保存稿'
              : result.review_status === 'needs_material'
                ? '请补充材料后再采用'
                : '审校发现问题'}
          </AlertTitle>
          <AlertDescription>
            {historicalEdit
              ? '这份历史稿件经过人工改动，原自动审校结论不适用于改动后的正文。'
              : '具体问题见下方审校意见。需要继续处理时，返回来源并重新选择 Skill。'}
          </AlertDescription>
        </Alert>
      ) : null}
      <section aria-label="正文">
        {markdown ? (
          <AnalysisReportPreview markdown={markdown} />
        ) : (
          <article className="space-y-5 text-base leading-8">
            {result.title ? (
              <h2 className="text-2xl font-medium">{result.title}</h2>
            ) : null}
            {result.blocks.map((block) =>
              block.type === 'heading' ? (
                <h3 key={block.id} className="text-xl font-medium">
                  {block.text}
                </h3>
              ) : block.type === 'list' ? (
                block.ordered ? (
                  <ol key={block.id} className="list-decimal pl-6">
                    {block.items.map((text) => (
                      <li key={`${block.id}-${text}`}>{text}</li>
                    ))}
                  </ol>
                ) : (
                  <ul key={block.id} className="list-disc pl-6">
                    {block.items.map((text) => (
                      <li key={`${block.id}-${text}`}>{text}</li>
                    ))}
                  </ul>
                )
              ) : block.type === 'quote' ? (
                <blockquote
                  key={block.id}
                  className="pl-4 text-muted-foreground"
                >
                  {block.text}
                </blockquote>
              ) : (
                <p key={block.id} className="whitespace-pre-line">
                  {block.text}
                </p>
              ),
            )}
          </article>
        )}
      </section>
      {review?.findings.length ? (
        <details className="text-sm">
          <summary className="cursor-pointer py-2 font-medium">
            {historicalEdit ? '历史审校记录' : '审校意见'}（
            {review.findings.length}）
          </summary>
          <ul className="mt-3 grid gap-4">
            {review.findings.map((finding) => (
              <li
                key={`${finding.block_id}-${finding.category}-${finding.problem}`}
              >
                <p className="font-medium">{finding.problem}</p>
                <p className="mt-1 text-muted-foreground">
                  {finding.correction}
                </p>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <ContentReportHistory
        analysisId={analysisId}
        currentReportId={reportId}
      />
      <ContentSourceReview
        analysisId={analysisId}
        citations={result.evidence_index}
      />
    </div>
  );
}
