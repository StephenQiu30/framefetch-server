import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
} from '@/components/ui/item';

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
        <Accordion type="single" collapsible>
          <AccordionItem value="review">
            <AccordionTrigger>
              审校意见（{review.findings.length}）
            </AccordionTrigger>
            <AccordionContent>
              <ItemGroup className="gap-4">
                {review.findings.map((finding) => (
                  <Item
                    role="listitem"
                    key={`${finding.block_id}-${finding.problem}`}
                  >
                    <ItemContent>
                      <ItemDescription className="line-clamp-none">
                        {finding.problem}
                      </ItemDescription>
                      <ItemDescription className="line-clamp-none">
                        {finding.correction}
                      </ItemDescription>
                    </ItemContent>
                  </Item>
                ))}
              </ItemGroup>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      ) : null}
    </aside>
  );
}
