import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

export default function AnalysisEditorialReview({
  result,
}: {
  result: API.VideoArticleResultResponse | API.StructuredReportResultResponse;
}) {
  const review = result.review_history?.at(-1);
  if (!review) return null;
  return (
    <aside className="mt-8 grid gap-4" aria-label="审校意见">
      {result.review_status === 'needs_material' ||
      result.review_status === 'needs_review' ? (
        <Alert>
          <AlertTitle>
            {result.review_status === 'needs_material'
              ? '需要补充材料'
              : '审校仍有问题'}
          </AlertTitle>
          <AlertDescription>
            请根据具体问题补充材料或调整要求后，新建任务。
          </AlertDescription>
        </Alert>
      ) : null}
      {review.findings.length ? (
        <details className="text-sm">
          <summary className="cursor-pointer py-2 font-medium">
            审校意见（{review.findings.length}）
          </summary>
          <ul className="mt-3 grid gap-4">
            {review.findings.map((finding) => (
              <li key={`${finding.block_id}-${finding.problem}`}>
                <p className="font-medium">{finding.problem}</p>
                <p className="mt-1 text-muted-foreground">
                  {finding.correction}
                </p>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </aside>
  );
}
