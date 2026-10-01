'use client';

import { ArrowClockwise } from '@phosphor-icons/react';
import { useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import { deleteDocument as deleteScreenplayDocument } from '@/api/documents';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
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

const workspaceClassName = 'mt-10 lg:mt-12';
const headerClassName =
  'flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between sm:gap-8';
const headerActionsClassName =
  'flex w-full flex-col gap-2 sm:w-auto sm:flex-row';
const previewColumnClassName = 'min-w-0 lg:min-h-0 lg:overflow-hidden';
const tocColumnClassName =
  'order-first min-w-0 lg:order-none lg:min-h-0 lg:overflow-hidden';

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
              <Button onClick={state.refresh} size="sm" variant="outline">
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
          <header className={headerClassName}>
            <div className="min-w-0">
              <Badge
                aria-live="polite"
                variant={documentStatusVariant(state.document.status)}
              >
                {documentStatusLabels[state.document.status]}
              </Badge>
              <h1 className="mt-4 break-words text-2xl font-semibold tracking-tight sm:text-3xl">
                {state.document.title}
              </h1>
              <p className="mt-3 break-all text-sm text-muted-foreground">
                {state.document.original_filename}
              </p>
            </div>
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
          </header>
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
      <header className={headerClassName}>
        <div className="min-w-0 flex-1">
          <Skeleton className="h-6 w-24" />
          <Skeleton className="mt-4 h-8 w-2/5 sm:h-9" />
          <Skeleton className="mt-3 h-5 w-1/3" />
        </div>
        <div className={headerActionsClassName}>
          <Skeleton className="h-8 w-full sm:w-16" />
          <Skeleton className="h-8 w-full sm:w-24" />
        </div>
      </header>
      <div className="mt-6">
        <Skeleton className="h-8 w-52" />
      </div>
      <div className="mt-8 py-5 sm:mt-10 sm:py-6">
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
          <div className="mt-4 flex max-h-dvh min-h-0 flex-col gap-6 overflow-hidden px-5 py-6 sm:px-8 sm:py-8">
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
          <div className="pb-3">
            <Skeleton className="h-5 w-16" />
          </div>
          <div className="mt-3 flex min-h-0 flex-col gap-3 overflow-y-auto">
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
      <PageErrorNotice
        message={error}
        onRetry={onRetry}
        retryLabel="重新加载"
        title="剧本文档暂时不可用"
        titleAs="h1"
      />
    </div>
  );
}
