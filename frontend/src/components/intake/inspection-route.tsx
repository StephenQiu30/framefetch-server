'use client';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter, useSearchParams } from 'next/navigation';
import { useRef, useState } from 'react';
import {
  createDownloadIntent,
  refreshDownloadIntent,
} from '@/api/downloadIntents';
import { createDownload } from '@/api/downloads';
import { getInspection } from '@/api/inspections';
import { getSourceDiscovery } from '@/api/sourceDiscoveries';
import { useAuth } from '@/components/auth/auth-provider';
import InspectionWorkspace from '@/components/intake/inspection-workspace';
import { useIntakeDraft } from '@/components/intake/intake-draft-provider';
import {
  SourceDiscoverySkeleton,
  SourceDiscoveryWorkspace,
} from '@/components/intake/source-discovery-workspace';
import { rememberDownloadIntent } from '@/components/intake/use-download-intent';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { markNavigationPush } from '@/components/layout/navigation-state';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageNavigation } from '@/components/layout/page-navigation';
import { SplitLayout } from '@/components/layout/split-layout';
import { AspectRatio } from '@/components/ui/aspect-ratio';
import { Item, ItemContent } from '@/components/ui/item';
import { Skeleton } from '@/components/ui/skeleton';
import { privateQueryKey } from '@/lib/query-keys';
import { ApiError, displayError } from '@/lib/request-error';
import { createUuid } from '@/lib/uuid';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default function InspectionRoute() {
  const params = useSearchParams();
  const router = useRouter();
  const queries = useQueryClient();
  const { user } = useAuth();
  const { setAttempt, setDeclaredOrigin, setMode } = useIntakeDraft();
  const inspectionId = params.get('inspectionId');
  const discoveryId = params.get('discoveryId');
  const intentId = params.get('intentId');
  const validInspectionId =
    inspectionId && uuid.test(inspectionId) ? inspectionId : null;
  const validDiscoveryId =
    discoveryId && uuid.test(discoveryId) ? discoveryId : null;
  const validIntentId = intentId && uuid.test(intentId) ? intentId : null;
  const [formatChoice, setFormatChoice] = useState<{
    inspectionId: string;
    formatId: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyItemRef, setBusyItemRef] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const idempotency = useRef<{ payload: string; key: string } | null>(null);
  const inspection = useQuery({
    queryKey: privateQueryKey('inspection', validInspectionId),
    enabled: !!validInspectionId,
    queryFn: ({ signal }) =>
      getInspection({ inspection_id: validInspectionId ?? '' }, { signal }),
    staleTime: 5 * 60_000,
  });
  const discovery = useQuery({
    queryKey: privateQueryKey('source-discovery', validDiscoveryId),
    enabled: !!validDiscoveryId && !validInspectionId,
    queryFn: ({ signal }) =>
      getSourceDiscovery({ discovery_id: validDiscoveryId ?? '' }, { signal }),
    staleTime: 5 * 60_000,
  });

  async function refreshExpired() {
    if (!validIntentId) return;
    setBusy(true);
    setError(null);
    try {
      const result = await refreshDownloadIntent({ intent_id: validIntentId });
      queries.setQueryData(
        privateQueryKey('download-intent', 'id', validIntentId),
        result,
      );
      if (user?.id) rememberDownloadIntent(user.id, validIntentId);
      setAttempt({ id: validIntentId, input: null, submitting: false });
      router.replace('/');
    } catch (reason) {
      setError(displayError(reason));
    } finally {
      setBusy(false);
    }
  }

  async function selectItem(item: API.SourceDiscoveryItemResponse) {
    if (
      !discovery.data ||
      busy ||
      !user?.id ||
      item.status !== 'ready' ||
      item.decision_hint !== 'candidate' ||
      Date.parse(discovery.data.expires_at) <= Date.now()
    )
      return;
    setBusy(true);
    setBusyItemRef(item.item_ref);
    setError(null);
    const payload = `${discovery.data.id}:${item.item_ref}`;
    if (idempotency.current?.payload !== payload)
      idempotency.current = { payload, key: createUuid() };
    const requestKey = idempotency.current.key;
    let submitted = false;
    try {
      rememberDownloadIntent(user.id, { key: requestKey });
      submitted = true;
      const result = await createDownloadIntent(
        {
          source: {
            kind: 'discovered_item',
            discovery_id: discovery.data.id,
            item_ref: item.item_ref,
          },
        },
        {
          headers: { 'Idempotency-Key': requestKey },
          timeout: 30_000,
        },
      );
      queries.setQueryData(
        privateQueryKey('download-intent', 'id', result.id),
        result,
      );
      if (user?.id) rememberDownloadIntent(user.id, result.id);
      setAttempt({ id: result.id, input: null, submitting: false });
      router.replace('/');
    } catch (reason) {
      const definitive =
        reason instanceof ApiError &&
        reason.status >= 400 &&
        reason.status < 500 &&
        reason.status !== 408;
      if (definitive || !submitted) {
        if (submitted) rememberDownloadIntent(user.id, null);
        setError(displayError(reason));
      } else {
        setAttempt({ key: requestKey, input: null, submitting: false });
        router.replace('/');
      }
    } finally {
      setBusy(false);
      setBusyItemRef(null);
    }
  }

  async function createJob() {
    const result = inspection.data;
    if (!result || busy) return;
    const selectedId =
      formatChoice?.inspectionId === result.id &&
      result.formats.some((item) => item.id === formatChoice.formatId)
        ? formatChoice.formatId
        : result.formats[0]?.id;
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    const payload = `${result.id}:${selectedId}`;
    if (idempotency.current?.payload !== payload)
      idempotency.current = { payload, key: createUuid() };
    try {
      const job = await createDownload(
        { inspection_id: result.id, format_id: selectedId },
        { headers: { 'Idempotency-Key': idempotency.current.key } },
      );
      queries.setQueryData(privateQueryKey('download', job.id), job);
      void queries.invalidateQueries({
        queryKey: privateQueryKey('download-history'),
      });
      const target = `/downloads/detail?jobId=${encodeURIComponent(job.id)}`;
      markNavigationPush(target);
      router.push(target);
    } catch (reason) {
      if (
        reason instanceof ApiError &&
        reason.code === 'resource_expired' &&
        validIntentId
      ) {
        await refreshExpired();
      } else {
        setError(displayError(reason));
      }
    } finally {
      setBusy(false);
    }
  }

  const result = inspection.data;
  const selectedId =
    result &&
    formatChoice?.inspectionId === result.id &&
    result.formats.some((item) => item.id === formatChoice.formatId)
      ? formatChoice.formatId
      : (result?.formats[0]?.id ?? '');
  const expired = result && Date.parse(result.expires_at) <= Date.now();
  const query = validInspectionId ? inspection : discovery;

  return (
    <div className="inner-page" data-slot="inspection-route">
      <PageNavigation fallbackHref="/" />
      {error ? (
        <FeedbackNotice
          presentation="toast"
          className="mb-6"
          title="操作未完成"
          description={error}
          tone="error"
        />
      ) : null}
      {!validInspectionId && !validDiscoveryId ? (
        <PageErrorNotice
          title="无法打开解析结果"
          message="结果地址无效，请返回首页重新解析。"
        />
      ) : query.isPending ? (
        validInspectionId ? (
          <InspectionSkeleton />
        ) : (
          <SourceDiscoverySkeleton />
        )
      ) : query.error && !query.data ? (
        <PageErrorNotice
          title={
            query.error instanceof ApiError &&
            query.error.code === 'resource_expired'
              ? '解析结果已过期'
              : '无法读取解析结果'
          }
          message={
            query.error instanceof ApiError &&
            query.error.code === 'resource_expired' &&
            validIntentId
              ? '更新解析结果后可继续选择下载规格。'
              : displayError(query.error)
          }
          onRetry={
            query.error instanceof ApiError &&
            query.error.code === 'resource_expired' &&
            validIntentId
              ? () => void refreshExpired()
              : () => void query.refetch()
          }
          retryLabel={
            query.error instanceof ApiError &&
            query.error.code === 'resource_expired' &&
            validIntentId
              ? '更新结果'
              : '重试'
          }
        />
      ) : result ? (
        expired ? (
          <PageErrorNotice
            title="解析结果已过期"
            message={
              validIntentId
                ? '更新解析结果后可继续选择下载规格。'
                : '请返回首页重新解析该链接。'
            }
            onRetry={validIntentId ? () => void refreshExpired() : undefined}
            retryLabel="更新结果"
          />
        ) : (
          <InspectionWorkspace
            busy={busy}
            inspection={result}
            onChange={(formatId) =>
              setFormatChoice({ inspectionId: result.id, formatId })
            }
            onCreate={() => void createJob()}
            onUseUpload={() => {
              setDeclaredOrigin('wechat_channels');
              setMode('video');
              markNavigationPush('/');
              router.push('/');
            }}
            selectedId={selectedId}
          />
        )
      ) : discovery.data ? (
        <SourceDiscoveryWorkspace
          busyItemRef={busyItemRef}
          discovery={discovery.data}
          onSelect={(item) => void selectItem(item)}
        />
      ) : null}
    </div>
  );
}

export function InspectionSkeleton() {
  return (
    <SplitLayout aria-label="正在读取解析结果" columns="primary" role="status">
      <div aria-hidden className="flex flex-col gap-6">
        <AspectRatio ratio={16 / 9}>
          <Skeleton className="size-full" />
        </AspectRatio>
        <Skeleton className="aspect-[12/1] w-3/4" />
        <Skeleton className="aspect-[16/1] w-full" />
      </div>
      <div aria-hidden className="flex flex-col gap-6 lg:contain-size">
        <Item variant="muted" className="min-h-0 flex-1">
          <ItemContent className="gap-4">
            {['first', 'second', 'third'].map((key) => (
              <Skeleton className="aspect-[8/1] w-full" key={key} />
            ))}
          </ItemContent>
        </Item>
        <Skeleton className="aspect-[8/1] w-full" />
      </div>
    </SplitLayout>
  );
}
