'use client';

import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import {
  useCallback,
  useEffect,
  useEffectEvent,
  useRef,
  useState,
} from 'react';
import { toast } from 'sonner';
import { createSourceDiscovery } from '@/api/sourceDiscoveries';
import { ContentIntakeHero } from '@/components/intake/content-intake-hero';
import { useIntakeDraft } from '@/components/intake/intake-draft-provider';
import {
  IntentStatusCode,
  intentDescription,
  intentTitle,
  isActiveIntentStatus,
} from '@/components/intake/intent-status';
import { LinkDownloadForm } from '@/components/intake/link-download-form';
import { MediaUploadForm } from '@/components/intake/media-upload-form';
import {
  hasPublicInput,
  isWeChatArticleInput,
  PUBLIC_INPUT_REQUIRED,
} from '@/components/intake/public-input';
import { useDocumentImport } from '@/components/intake/use-document-import';
import { useDownloadIntent } from '@/components/intake/use-download-intent';
import { useMediaImport } from '@/components/intake/use-media-import';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { markNavigationPush } from '@/components/layout/navigation-history';
import { ScreenplayUploadForm } from '@/components/screenplay/screenplay-upload-form';
import { Button } from '@/components/ui/button';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';
import { createUuid as createIdempotencyKey } from '@/lib/uuid';

type BusyAction = 'inspect' | null;
const PARSE_STATUS_TOAST_ID = 'framefetch-parse-status';
export default function DownloadWorkspace() {
  const router = useRouter();
  const queries = useQueryClient();
  const {
    mode,
    setMode,
    input: url,
    setInput: setUrl,
    declaredOrigin: mediaDeclaredOrigin,
    setDeclaredOrigin: setMediaDeclaredOrigin,
    quickParse,
    clearQuickParse,
  } = useIntakeDraft();
  const intent = useDownloadIntent();
  const [busy, setBusy] = useState<BusyAction>(null);
  const [error, setError] = useState<string | null>(null);
  const observedActiveIntentId = useRef<string | null>(null);
  const [urlInvalid, setUrlInvalid] = useState(false);
  useEffect(() => {
    if (!intent.attempt) observedActiveIntentId.current = null;
    else if (intent.snapshot && isActiveIntentStatus(intent.snapshot.status))
      observedActiveIntentId.current = intent.snapshot.id;
  }, [intent.attempt, intent.snapshot]);
  const snapshot = intent.snapshot;
  const showTerminalStatus =
    (!!intent.attempt && intent.attempt.input !== null) ||
    (!!snapshot && observedActiveIntentId.current === snapshot.id);
  const showPendingToast = !!intent.attempt && intent.pending && !intent.error;
  const showSubmittingToast = busy === 'inspect' && !showPendingToast;
  const canCancelToast = showPendingToast && !!snapshot;
  const showFailureToast =
    showTerminalStatus &&
    !intent.error &&
    (snapshot?.status === IntentStatusCode.Failed ||
      snapshot?.status === IntentStatusCode.Expired);
  const showIntentAction =
    mode === 'link' &&
    !!intent.attempt &&
    (intent.resultExpired ||
      !!intent.error ||
      (showTerminalStatus &&
        !showFailureToast &&
        (snapshot?.status === IntentStatusCode.Failed ||
          snapshot?.status === IntentStatusCode.Expired)));
  const intentStatusError =
    !!intent.error ||
    snapshot?.status === IntentStatusCode.Failed ||
    snapshot?.status === IntentStatusCode.Expired;
  const intentStatusTitle = intent.error
    ? '任务状态暂时无法更新'
    : intent.pending && snapshot?.status === IntentStatusCode.Ready
      ? '正在更新解析结果'
      : intent.resultExpired
        ? '解析结果已过期'
        : snapshot?.status === IntentStatusCode.Ready
          ? intent.inspection
            ? '正在打开解析结果'
            : '正在加载解析结果'
          : intentTitle(snapshot?.status);
  const intentStatusDescription =
    intent.error ??
    (intent.pending && snapshot?.status === IntentStatusCode.Ready
      ? '正在更新解析结果，请稍候。'
      : intent.resultExpired
        ? '更新后请重新确认下载规格，无需再次粘贴原链接。'
        : snapshot
          ? intentDescription(snapshot)
          : '正在确认接单，请稍候，无需重复提交。');
  const cancelFromToast = useEffectEvent(() => {
    void intent.cancel();
  });
  useEffect(() => {
    if (showFailureToast) {
      toast.error(intentStatusTitle, {
        id: PARSE_STATUS_TOAST_ID,
        description: intentStatusDescription,
        duration: 8000,
        cancel: undefined,
      });
      return;
    }
    if (!showPendingToast && !showSubmittingToast) {
      toast.dismiss(PARSE_STATUS_TOAST_ID);
      return;
    }
    toast.loading(
      intent.cancelling
        ? '正在取消解析'
        : showPendingToast
          ? intentStatusTitle
          : '正在提交解析请求',
      {
        id: PARSE_STATUS_TOAST_ID,
        description: showPendingToast
          ? intentStatusDescription
          : '请稍候，无需重复提交。',
        duration: Number.POSITIVE_INFINITY,
        cancel:
          canCancelToast && !intent.cancelling
            ? {
                label: '取消解析',
                onClick: () => cancelFromToast(),
              }
            : undefined,
      },
    );
  }, [
    showFailureToast,
    showPendingToast,
    showSubmittingToast,
    canCancelToast,
    intentStatusTitle,
    intentStatusDescription,
    intent.cancelling,
  ]);
  useEffect(
    () => () => {
      toast.dismiss(PARSE_STATUS_TOAST_ID);
    },
    [],
  );
  const discoveryKey = useRef<{ input: string; value: string } | null>(null);
  const openingResultKey = useRef<string | null>(null);
  const handledQuickParseId = useRef<number | null>(null);
  useEffect(() => {
    const snapshot = intent.snapshot;
    const inspection = intent.inspection;
    if (
      quickParse ||
      mode !== 'link' ||
      snapshot?.status !== IntentStatusCode.Ready ||
      !inspection ||
      intent.resultExpired
    )
      return;
    const key = `${snapshot.id}:${inspection.id}`;
    if (openingResultKey.current === key) return;
    openingResultKey.current = key;
    queries.setQueryData(
      privateQueryKey('inspection', inspection.id),
      inspection,
    );
    const target = `/downloads/new?inspectionId=${encodeURIComponent(inspection.id)}&intentId=${encodeURIComponent(snapshot.id)}`;
    markNavigationPush(target);
    // The result route now owns this completed inspection. Keep only unfinished
    // intents in the homepage's refresh-safe recovery slot.
    intent.clear();
    router.push(target);
  }, [
    intent.snapshot,
    intent.inspection,
    intent.resultExpired,
    intent.clear,
    quickParse,
    mode,
    queries,
    router,
  ]);
  const openDownload = useCallback(
    (downloadId: string) => {
      void queries.invalidateQueries({
        queryKey: privateQueryKey('download-history'),
      });
      const target = `/downloads/detail?jobId=${encodeURIComponent(
        downloadId,
      )}`;
      markNavigationPush(target);
      router.push(target);
    },
    [queries, router],
  );
  const openDocument = useCallback(
    (documentId: string) => {
      void queries.invalidateQueries({
        queryKey: privateQueryKey('documents'),
      });
      const target = `/documents/detail?documentId=${encodeURIComponent(
        documentId,
      )}`;
      markNavigationPush(target);
      router.push(target);
    },
    [queries, router],
  );
  const mediaImport = useMediaImport(openDownload, mediaDeclaredOrigin);
  const documentImport = useDocumentImport(openDocument);

  useEffect(() => {
    if (mediaImport.notice) toast.info(mediaImport.notice);
  }, [mediaImport.notice]);

  useEffect(() => {
    if (error && !urlInvalid) {
      toast.error('操作未完成', { description: error });
    }
  }, [error, urlInvalid]);

  function clearLinkResult() {
    if (!intent.pending) {
      intent.clear();
      openingResultKey.current = null;
    }
  }

  function discoveryIdempotencyKey(input: string) {
    if (discoveryKey.current?.input !== input) {
      discoveryKey.current = { input, value: createIdempotencyKey() };
    }
    return discoveryKey.current.value;
  }

  async function inspect(overrideInput?: string) {
    if (busy !== null || (intent.pending && !intent.canResubmit)) return;
    const input = (overrideInput ?? url).trim();
    clearLinkResult();
    if (!hasPublicInput(input)) {
      setUrlInvalid(true);
      setError(PUBLIC_INPUT_REQUIRED);
      return;
    }
    setUrlInvalid(false);
    setBusy('inspect');
    setError(null);
    try {
      if (isWeChatArticleInput(input)) {
        const result = await createSourceDiscovery(
          { kind: 'wechat_official_account_article', url: input },
          {
            headers: { 'Idempotency-Key': discoveryIdempotencyKey(input) },
            timeout: 30_000,
          },
        );
        queries.setQueryData(
          privateQueryKey('source-discovery', result.id),
          result,
        );
        const target = `/downloads/new?discoveryId=${encodeURIComponent(result.id)}`;
        markNavigationPush(target);
        router.push(target);
      } else {
        await intent.submit(input, intent.canResubmit);
      }
    } catch (reason) {
      setError(displayError(reason));
    } finally {
      setBusy(null);
    }
  }

  const inspectFromQuickParse = useEffectEvent((input: string) => {
    void inspect(input);
  });

  useEffect(() => {
    if (!quickParse || handledQuickParseId.current === quickParse.id) return;
    handledQuickParseId.current = quickParse.id;
    clearQuickParse(quickParse.id);
    if (busy !== null || (intent.pending && !intent.canResubmit)) {
      setError('已有解析任务正在处理，请完成或取消后再试。');
      return;
    }
    inspectFromQuickParse(quickParse.input);
  }, [quickParse, clearQuickParse, busy, intent.pending, intent.canResubmit]);

  return (
    <div className="pb-6" data-slot="download-workspace">
      <ContentIntakeHero
        disabled={
          busy !== null ||
          intent.pending ||
          mediaImport.busy ||
          documentImport.busy
        }
        linkForm={
          <LinkDownloadForm
            busy={busy === 'inspect' || (intent.pending && !intent.canResubmit)}
            disabled={busy !== null || (intent.pending && !intent.canResubmit)}
            hasResult={false}
            invalid={urlInvalid}
            onInspect={() => void inspect()}
            onUrlChange={(value) => {
              setUrl(value);
              clearLinkResult();
              setUrlInvalid(false);
              setError(null);
            }}
            url={url}
          />
        }
        mode={mode}
        onModeChange={(nextMode) => {
          setMode(nextMode);
          if (nextMode === 'video') setMediaDeclaredOrigin('user_file');
        }}
        screenplayForm={
          <ScreenplayUploadForm
            busy={documentImport.busy}
            canCancel={documentImport.canCancel}
            error={documentImport.error}
            file={documentImport.file}
            fileInvalid={documentImport.fileInvalid}
            layout="workspace"
            onCancel={() => void documentImport.cancel()}
            onFileSelect={documentImport.selectFile}
            onStart={() => void documentImport.start()}
            phase={documentImport.phase}
            progress={documentImport.progress}
          />
        }
        videoForm={
          <MediaUploadForm
            busy={mediaImport.busy}
            canCancel={mediaImport.canCancel}
            file={mediaImport.file}
            fileInvalid={mediaImport.fileInvalid}
            onCancel={() => void mediaImport.cancel()}
            onFileSelect={mediaImport.selectFile}
            onStart={() => void mediaImport.start()}
            phase={mediaImport.phase}
            progress={mediaImport.progress}
            declaredOrigin={mediaDeclaredOrigin}
          />
        }
      />
      {showIntentAction ? (
        <FeedbackNotice
          action={
            (intent.resultExpired && !intent.pending) ||
            intent.error ||
            (snapshot && intent.pending) ? (
              <>
                {intent.resultExpired && !intent.pending ? (
                  <Button
                    onClick={() => void intent.refresh()}
                    size="sm"
                    variant="outline"
                  >
                    更新结果
                  </Button>
                ) : intent.error ? (
                  <Button
                    onClick={() => void intent.retry()}
                    size="sm"
                    variant="outline"
                  >
                    恢复任务
                  </Button>
                ) : null}
                {snapshot && intent.pending ? (
                  <Button
                    disabled={intent.cancelling}
                    onClick={() => void intent.cancel()}
                    size="sm"
                    variant="outline"
                  >
                    {intent.cancelling ? '正在取消…' : '取消解析'}
                  </Button>
                ) : null}
              </>
            ) : undefined
          }
          className="mt-6"
          description={intentStatusDescription}
          id="parse-intent-status"
          role={intentStatusError ? 'alert' : 'status'}
          title={intentStatusTitle}
          tone={intentStatusError ? 'error' : 'info'}
        />
      ) : null}
      {(
        mode === 'link'
          ? error && urlInvalid
          : mode === 'video'
            ? mediaImport.error
            : null
      ) ? (
        <FeedbackNotice
          presentation={
            mode === 'video' && !mediaImport.fileInvalid ? 'toast' : 'inline'
          }
          className="mt-8"
          description={mode === 'link' ? error : mediaImport.error}
          descriptionId="download-workspace-error"
          title="操作未完成"
          tone="error"
        />
      ) : null}
    </div>
  );
}
