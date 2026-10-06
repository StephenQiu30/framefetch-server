'use client';

import { ArrowClockwise } from '@phosphor-icons/react';
import { useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import { deleteDocument as deleteScreenplayDocument } from '@/api/documents';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import { SplitLayout } from '@/components/layout/split-layout';
import ScreenplayAnalysisPanel from '@/components/screenplay/screenplay-analysis-panel';
import { ScreenplayDocumentDeleteDialog } from '@/components/screenplay/screenplay-document-delete-dialog';
import {
  documentStatusLabels,
  documentStatusVariant,
} from '@/components/screenplay/screenplay-document-format';
import { ScreenplayDocumentMetadata } from '@/components/screenplay/screenplay-document-metadata';
import { ScreenplayDocumentPreview } from '@/components/screenplay/screenplay-document-preview';
import {
  extractMarkdownHeadings,
  ScreenplayDocumentToc,
} from '@/components/screenplay/screenplay-document-toc';
import { ScreenplayUploadDialog } from '@/components/screenplay/screenplay-upload-dialog';
import { useScreenplayDocument } from '@/components/screenplay/use-screenplay-document';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';
import { ImportStatusCode } from '@/lib/import-status';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';

const metadataSkeletonKeys = [
  'format',
  'language',
  'scenes',
  'characters',
  'size',
  'status',
  'created',
  'expires',
] as const;

const tocSkeletonKeys = [
  'toc-1',
  'toc-2',
  'toc-3',
  'toc-4',
  'toc-5',
  'toc-6',
] as const;

const workspaceClassName = 'mt-8';
const headerActionsClassName =
  'flex w-full flex-col gap-2 sm:w-auto sm:flex-row';
const previewColumnClassName = 'min-w-0 lg:overflow-hidden';
const tocColumnClassName =
  'order-first min-w-0 lg:order-none lg:overflow-hidden';

export default function ScreenplayDocumentDetailView({
  documentId,
  analysisId,
  pollIntervalMs,
}: {
  documentId: string;
  analysisId?: string;
  pollIntervalMs?: number;
}) {
  const router = useRouter();
  const queries = useQueryClient();
  const [deleting, setDeleting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const state = useScreenplayDocument(documentId, pollIntervalMs);
  const headings = useMemo(
    () => extractMarkdownHeadings(state.document?.preview ?? ''),
    [state.document?.preview],
  );
  async function remove() {
    setDeleting(true);
    setActionError(null);
    try {
      await deleteScreenplayDocument({
        document_id: encodeURIComponent(documentId),
      });
      queries.removeQueries({
        queryKey: privateQueryKey('document', documentId),
      });
      void queries.invalidateQueries({
        queryKey: privateQueryKey('documents'),
      });
      void queries.invalidateQueries({
        queryKey: privateQueryKey('intent-history'),
      });
      router.replace('/documents');
    } catch (reason) {
      setActionError(displayError(reason));
      setDeleting(false);
    }
  }
  if (state.loading && !state.document) return <DocumentDetailSkeleton />;
  if (state.error && !state.document) {
    return <DocumentDetailError error={state.error} onRetry={state.refresh} />;
  }

  return (
    <div className="inner-page">
      <PageNavigation fallbackHref="/documents" />
      {state.error || actionError ? (
        <FeedbackNotice
          presentation={state.error ? 'inline' : 'toast'}
          action={
            state.error ? (
              <Button onClick={state.refresh} size="default" variant="outline">
                重新加载
              </Button>
            ) : null
          }
          className="mb-6"
          description={state.error ?? actionError ?? ''}
          title={state.error ? '无法读取剧本文档' : '操作未完成'}
          tone="error"
        />
      ) : null}
      {state.document ? (
        <>
          <PageHeader
            title={
              <span className="[overflow-wrap:anywhere]">
                {state.document.title}
              </span>
            }
            description={
              <span className="[overflow-wrap:anywhere]">
                {state.document.original_filename}
              </span>
            }
            action={
              <div className={headerActionsClassName}>
                {state.document.status === ImportStatusCode.Uploading &&
                state.document.error_code ? (
                  <ScreenplayUploadDialog label="重新上传" />
                ) : null}
                <Button
                  className="w-full sm:w-auto"
                  disabled={state.loading}
                  onClick={state.refresh}
                  type="button"
                  variant="outline"
                >
                  {state.loading ? (
                    <Spinner aria-hidden data-icon="inline-start" />
                  ) : (
                    <ArrowClockwise aria-hidden data-icon="inline-start" />
                  )}
                  刷新
                </Button>
                <ScreenplayDocumentDeleteDialog
                  busy={deleting}
                  onDelete={remove}
                />
              </div>
            }
          />
          <Badge
            aria-live="polite"
            className="mt-4"
            variant={documentStatusVariant(state.document.status)}
          >
            {documentStatusLabels[state.document.status]}
          </Badge>
          <div className="mt-6">
            <Button asChild variant="outline">
              <Link
                href={`/history/activity?document_id=${encodeURIComponent(documentId)}`}
              >
                查看全部解析与分析
              </Link>
            </Button>
          </div>
          <ScreenplayDocumentMetadata document={state.document} />
          <SplitLayout
            className={workspaceClassName}
            columns="sidebar-end"
            scrollable
            data-testid="screenplay-document-workspace"
          >
            <div className={previewColumnClassName}>
              <ScreenplayDocumentPreview
                document={state.document}
                headings={headings}
              />
            </div>
            <div className={tocColumnClassName}>
              <ScreenplayDocumentToc headings={headings} />
            </div>
          </SplitLayout>
          {state.document.status === ImportStatusCode.Ready ? (
            <ScreenplayAnalysisPanel
              documentId={documentId}
              analysisId={analysisId}
              pollIntervalMs={pollIntervalMs}
            />
          ) : null}
        </>
      ) : null}
    </div>
  );
}

export function DocumentDetailSkeleton() {
  return (
    <div aria-busy className="inner-page">
      <span className="sr-only" role="status">
        正在读取剧本文档
      </span>
      <PageNavigation fallbackHref="/documents" />
      <PageHeader
        title="剧本文档"
        description="正在读取剧本文档"
        action={
          <div className={headerActionsClassName}>
            <Skeleton className="h-8 w-full sm:w-16" />
            <Skeleton className="h-8 w-full sm:w-24" />
          </div>
        }
      />
      <div className="mt-6">
        <Skeleton className="h-8 w-52" />
      </div>
      <div className="mt-8">
        <Skeleton className="h-6 w-24" />
        <div className="mt-5 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4 lg:grid-cols-8">
          {metadataSkeletonKeys.map((key) => (
            <div className="flex flex-col gap-2" key={key}>
              <Skeleton className="h-3 w-14" />
              <Skeleton className="h-4 w-20" />
            </div>
          ))}
        </div>
      </div>
      <SplitLayout
        className={workspaceClassName}
        columns="sidebar-end"
        scrollable
      >
        <div
          className={`${previewColumnClassName} lg:grid lg:h-full lg:grid-rows-[auto_minmax(0,1fr)_auto]`}
        >
          <div className="flex items-baseline justify-between gap-4">
            <Skeleton className="h-6 w-28" />
            <Skeleton className="h-4 w-20" />
          </div>
          <div className="mt-4 flex max-h-dvh flex-col gap-6 overflow-hidden">
            {['first', 'second', 'third', 'fourth'].map((key) => (
              <div className="flex flex-col gap-3" key={key}>
                <Skeleton className="h-6 w-3/5" />
                <Skeleton className="h-5 w-full" />
                <Skeleton className="h-5 w-full" />
                <Skeleton className="h-5 w-4/5" />
              </div>
            ))}
          </div>
        </div>
        <div
          className={`${tocColumnClassName} lg:grid lg:h-full lg:grid-rows-[auto_minmax(0,1fr)]`}
        >
          <div>
            <Skeleton className="h-5 w-16" />
          </div>
          <div className="mt-3 flex flex-col gap-3 overflow-y-auto">
            {tocSkeletonKeys.map((key) => (
              <Skeleton className="h-4 w-full" key={key} />
            ))}
          </div>
        </div>
      </SplitLayout>
    </div>
  );
}

function DocumentDetailError({
  error,
  onRetry,
}: {
  error: string;
  onRetry: () => void;
}) {
  return (
    <div className="inner-page">
      <PageNavigation fallbackHref="/documents" />
      <PageHeader title="剧本文档" />
      <PageErrorNotice
        className="mt-8"
        message={error}
        onRetry={onRetry}
        retryLabel="重新加载"
        title="剧本文档暂时不可用"
        titleAs="h2"
      />
    </div>
  );
}
