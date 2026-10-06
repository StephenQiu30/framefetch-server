'use client';

import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import ContentReportHistory from '@/components/content/content-report-history';
import ContentSourceReview from '@/components/content/content-source-review';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { ItemDescription, ItemTitle } from '@/components/ui/item';

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
          <article className="space-y-5">
            {result.title ? (
              <ItemTitle className="line-clamp-none">
                <h2>{result.title}</h2>
              </ItemTitle>
            ) : null}
            {result.blocks.map((block) =>
              block.type === 'heading' ? (
                <ItemTitle key={block.id}>
                  <h3>{block.text}</h3>
                </ItemTitle>
              ) : block.type === 'list' ? (
                block.ordered ? (
                  <ol key={block.id} className="list-decimal">
                    {block.items.map((text) => (
                      <li key={`${block.id}-${text}`}>{text}</li>
                    ))}
                  </ol>
                ) : (
                  <ul key={block.id} className="list-disc">
                    {block.items.map((text) => (
                      <li key={`${block.id}-${text}`}>{text}</li>
                    ))}
                  </ul>
                )
              ) : block.type === 'quote' ? (
                <blockquote key={block.id}>{block.text}</blockquote>
              ) : (
                <ItemDescription
                  key={block.id}
                  className="line-clamp-none whitespace-pre-line"
                >
                  {block.text}
                </ItemDescription>
              ),
            )}
          </article>
        )}
      </section>
      {review?.findings.length ? (
        <details>
          <summary className="cursor-pointer">
            {historicalEdit ? '历史审校记录' : '审校意见'}（
            {review.findings.length}）
          </summary>
          <ul className="mt-3 grid gap-4">
            {review.findings.map((finding) => (
              <li
                key={`${finding.block_id}-${finding.category}-${finding.problem}`}
              >
                <ItemDescription className="line-clamp-none">
                  {finding.problem}
                </ItemDescription>
                <ItemDescription className="line-clamp-none mt-1">
                  {finding.correction}
                </ItemDescription>
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
