'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { getContentSource } from '@/api/analyses';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { Button } from '@/components/ui/button';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
} from '@/components/ui/item';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';

export default function ContentSourceReview({
  analysisId,
  citations,
}: {
  analysisId: string;
  citations: API.ContentCitation[];
}) {
  const [open, setOpen] = useState(false);
  const [expandedMaterials, setExpandedMaterials] = useState<string[]>([]);
  const query = useQuery({
    queryKey: privateQueryKey('content-source', analysisId),
    enabled: open,
    queryFn: ({ signal }) =>
      getContentSource({ analysis_id: analysisId }, { signal }),
  });
  return (
    <Accordion
      type="single"
      collapsible
      value={open ? 'source' : ''}
      onValueChange={(value) => setOpen(value === 'source')}
    >
      <AccordionItem value="source">
        <AccordionTrigger>来源回查</AccordionTrigger>
        <AccordionContent>
          {query.isFetching ? (
            <ItemDescription className="line-clamp-none" role="status">
              正在读取材料…
            </ItemDescription>
          ) : null}
          {query.error ? (
            <FeedbackNotice
              title="材料读取失败"
              description={displayError(query.error)}
              tone="error"
              action={
                <Button onClick={() => void query.refetch()}>重试</Button>
              }
            />
          ) : null}
          {citations.length ? (
            <ItemGroup className="mt-3 gap-4">
              {citations.map((citation) => (
                <Item
                  role="listitem"
                  key={`${citation.block_id}-${citation.material_id}-${citation.segment_id}-${citation.quote}`}
                >
                  <ItemContent>
                    <ItemDescription className="line-clamp-none">
                      {citation.quote}
                    </ItemDescription>
                    <ItemDescription className="line-clamp-none">
                      {query.data?.materials.find(
                        (material) => material.id === citation.material_id,
                      )?.title ?? citation.material_id}{' '}
                      · {citation.segment_id}
                    </ItemDescription>
                  </ItemContent>
                </Item>
              ))}
            </ItemGroup>
          ) : null}
          <Accordion
            type="multiple"
            value={expandedMaterials}
            onValueChange={setExpandedMaterials}
            className="mt-4"
          >
            {query.data?.materials.map((material) => (
              <AccordionItem key={material.id} value={material.id}>
                <AccordionTrigger>
                  {material.title}
                  {material.role === 'author_style' ? ' · 作者范文' : ''}
                </AccordionTrigger>
                <AccordionContent>
                  <ItemDescription className="line-clamp-none whitespace-pre-wrap break-words">
                    {material.text}
                  </ItemDescription>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
