import { useCallback, useEffect, useRef, useState } from 'react';
import {
  displayImportError,
  type ImportPhase,
  isImportAbort,
} from '@/lib/upload/import-lifecycle';
import {
  cancelLocalVideoImport,
  importLocalVideo,
  validateLocalVideo,
} from '@/lib/upload/media-import';
import { createUuid as createIdempotencyKey } from '@/lib/uuid';

type ActiveRun = {
  controller: AbortController;
  resourceId: string | null;
};

type StableKey = { payload: string; value: string };

export function useMediaImport(
  onComplete: (downloadId: string) => void,
  declaredOrigin: API.DeclaredOrigin = 'user_file',
  removeWatermark = false,
) {
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<ImportPhase>('idle');
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [fileInvalid, setFileInvalid] = useState(false);
  const activeRef = useRef<ActiveRun | null>(null);
  const keyRef = useRef<StableKey | null>(null);

  useEffect(
    () => () => {
      const active = activeRef.current;
      activeRef.current = null;
      active?.controller.abort();
    },
    [],
  );

  const selectFile = useCallback((next: File | null) => {
    setFile(next);
    setNotice(null);
    setFileInvalid(false);
    keyRef.current = null;
    if (!next) {
      setError(null);
      return;
    }
    const validationError = validateLocalVideo(next);
    setError(validationError);
    if (validationError) setFileInvalid(true);
  }, []);

  const start = useCallback(async () => {
    if (!file) {
      setFileInvalid(true);
      setError('请先选择一个 MP4 视频。');
      return;
    }
    const validationError = validateLocalVideo(file);
    if (validationError) {
      setFileInvalid(true);
      setError(validationError);
      return;
    }

    const run: ActiveRun = {
      controller: new AbortController(),
      resourceId: null,
    };
    activeRef.current = run;
    setError(null);
    setNotice(null);
    setFileInvalid(false);
    try {
      const payload = `${file.name}:${file.size}:${file.lastModified}:${file.type}:${declaredOrigin}:${removeWatermark}`;
      if (keyRef.current?.payload !== payload) {
        keyRef.current = { payload, value: createIdempotencyKey() };
      }
      const result = await importLocalVideo(
        file,
        keyRef.current.value,
        {
          onPhase: (next) => {
            if (activeRef.current === run) setPhase(next);
          },
          onProgress: (next) => {
            if (activeRef.current === run) setProgress(next);
          },
          onResource: (resourceId) => {
            run.resourceId = resourceId;
          },
        },
        run.controller.signal,
        declaredOrigin,
        removeWatermark,
      );
      if (activeRef.current === run) onComplete(result.download_id);
    } catch (reason) {
      if (activeRef.current === run && !isImportAbort(reason)) {
        setError(displayImportError(reason));
      }
    } finally {
      if (activeRef.current === run) {
        activeRef.current = null;
        setPhase('idle');
      }
    }
  }, [declaredOrigin, removeWatermark, file, onComplete]);

  const cancel = useCallback(async () => {
    const active = activeRef.current;
    if (!active) return;
    activeRef.current = null;
    active.controller.abort();
    setError(null);
    setPhase(active.resourceId ? 'cancelling' : 'idle');
    try {
      if (active.resourceId) await cancelLocalVideoImport(active.resourceId);
      setNotice('上传已取消，未完成的分片将由服务端清理。');
      keyRef.current = null;
    } catch (reason) {
      setError(displayImportError(reason));
    } finally {
      setPhase('idle');
      setProgress(0);
    }
  }, []);

  return {
    busy: phase !== 'idle',
    canCancel: phase === 'hashing' || phase === 'uploading',
    cancel,
    error,
    file,
    fileInvalid,
    notice,
    phase,
    progress,
    selectFile,
    start,
  };
}
