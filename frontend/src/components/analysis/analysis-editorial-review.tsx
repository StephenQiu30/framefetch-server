import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { ItemDescription } from '@/components/ui/item';

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
        <details>
          <summary className="cursor-pointer">
            审校意见（{review.findings.length}）
          </summary>
          <ul className="mt-3 grid gap-4">
            {review.findings.map((finding) => (
              <li key={`${finding.block_id}-${finding.problem}`}>
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
    </aside>
  );
}
