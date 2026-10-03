'use client';

import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import ContentEditor from '@/components/content/content-editor';
import ContentSourceReview from '@/components/content/content-source-review';
import ContentVersions from '@/components/content/content-versions';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

export default function ContentResultView({
  result,
  markdown,
  analysisId,
  reportId,
  editable,
  manualRevision = false,
  onSaved,
}: {
  analysisId: string;
  reportId: string | null;
  editable: boolean;
  manualRevision?: boolean;
  onSaved: () => Promise<unknown>;
  result: API.ContentDocumentResult;
  markdown?: string | null;
}) {
  const review = result.review_history.at(-1);
  return (
    <div className="mt-8 grid gap-6">
      {result.review_status !== 'passed' ? (
        <Alert>
          <AlertTitle>
            {manualRevision
              ? '人工修订版，请核对修改内容'
              : result.review_status === 'needs_material'
                ? '请补充材料后再采用'
                : '稿件仍有待修改之处'}
          </AlertTitle>
          <AlertDescription>
            {manualRevision
              ? '新版本已保存，原自动审校结论已失效。'
              : '下方审阅意见列出了具体问题。可修改正文，或补充材料后重新生成。'}
          </AlertDescription>
        </Alert>
      ) : null}
      {editable && reportId ? (
        <ContentEditor
          key={reportId}
          analysisId={analysisId}
          reportId={reportId}
          result={result}
          onSaved={onSaved}
        />
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
      <details className="text-sm">
        <summary className="cursor-pointer py-2 font-medium">
          审阅意见
          {review?.findings.length ? `（${review.findings.length}）` : ''}
        </summary>
        {review?.findings.length ? (
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
        ) : (
          <p className="mt-3 text-muted-foreground">本轮审阅未提出修改项。</p>
        )}
      </details>
      <ContentVersions analysisId={analysisId} currentReportId={reportId} />
      <ContentSourceReview
        analysisId={analysisId}
        citations={result.evidence_index}
      />
    </div>
  );
}
