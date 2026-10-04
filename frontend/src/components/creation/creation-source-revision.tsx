'use client';

import { useQuery } from '@tanstack/react-query';
import { listCreationMaterialRevisions } from '@/api/creation';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { Button } from '@/components/ui/button';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';

export function CreationSourceRevision({
  materialId,
  sha256,
}: {
  materialId: string;
  sha256: string;
}) {
  const revisions = useQuery({
    queryKey: privateQueryKey('creation-source-revisions', materialId),
    queryFn: ({ signal }) =>
      listCreationMaterialRevisions({ material_id: materialId }, { signal }),
  });
  const source = revisions.data?.find((revision) => revision.sha256 === sha256);
  if (revisions.error)
    return (
      <FeedbackNotice
        title="历史来源读取失败"
        description={displayError(revisions.error)}
        tone="error"
        action={
          <Button variant="outline" onClick={() => void revisions.refetch()}>
            重新读取历史来源
          </Button>
        }
      />
    );
  if (revisions.isPending)
    return <p role="status">正在读取依据对应的历史原文…</p>;
  return source ? (
    <div className="grid gap-2">
      <p className="text-sm text-muted-foreground">
        依据对应材料第 {source.number} 版
      </p>
      <p className="whitespace-pre-wrap break-words text-sm leading-6">
        {source.text}
      </p>
    </div>
  ) : (
    <p>没有找到与这条依据指纹一致的材料版本，不能用当前原文替代。</p>
  );
}
