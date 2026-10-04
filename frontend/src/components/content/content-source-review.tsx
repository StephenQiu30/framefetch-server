'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useState } from 'react';
import { getContentSource } from '@/api/analyses';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { Button } from '@/components/ui/button';
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
  const query = useQuery({
    queryKey: privateQueryKey('content-source', analysisId),
    enabled: open,
    queryFn: ({ signal }) =>
      getContentSource({ analysis_id: analysisId }, { signal }),
  });
  return (
    <details
      className="text-sm"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer py-2 font-medium">来源回查</summary>
      {query.isFetching ? <p role="status">正在读取材料…</p> : null}
      {query.error ? (
        <FeedbackNotice
          title="材料读取失败"
          description={displayError(query.error)}
          tone="error"
          action={<Button onClick={() => void query.refetch()}>重试</Button>}
        />
      ) : null}
      <ul className="mt-3 grid gap-4">
        {citations.map((citation) => (
          <li
            key={`${citation.block_id}-${citation.material_id}-${citation.segment_id}-${citation.quote}`}
          >
            <p>{citation.quote}</p>
            <p className="mt-1 text-muted-foreground">
              {query.data?.materials.find(
                (material) => material.id === citation.material_id,
              )?.title ?? citation.material_id}{' '}
              · {citation.segment_id}
            </p>
          </li>
        ))}
      </ul>
      {query.data?.materials.map((material) => (
        <details className="mt-4" key={material.id}>
          <summary className="cursor-pointer">
            {material.title}
            {material.role === 'author_style' ? ' · 作者范文' : ''}
          </summary>
          <p className="mt-3 whitespace-pre-wrap break-words leading-7">
            {material.text}
          </p>
        </details>
      ))}
      <Button asChild variant="ghost" className="mt-4">
        <Link href="/content">打开内容工作台</Link>
      </Button>
    </details>
  );
}
