'use client';

import { useEffect, useRef, useState } from 'react';
import { createWatermarkTask, listWatermarkTasks } from '@/api/downloads';
import { Button } from '@/components/ui/button';
import { Item, ItemContent, ItemTitle } from '@/components/ui/item';
import { displayError } from '@/lib/request-error';
import { createUuid } from '@/lib/uuid';

const labels: Record<API.WatermarkTaskResponse['status'], string> = {
  queued: '等待自动去水印',
  running: '正在自动去水印',
  succeeded: '处理版已就绪',
  unchanged: '未检出可处理的水印，已保留原片',
  failed: '去水印未完成，原片可正常保存',
  cancelled: '处理已取消，原片可正常保存',
};

export default function WatermarkPanel({ jobId }: { jobId: string }) {
  const [state, setState] = useState<API.WatermarkListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const retryKey = useRef<string | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    void revision;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const next = await listWatermarkTasks(
          { job_id: jobId },
          { signal: controller.signal },
        );
        if (!controller.signal.aborted) {
          setState(next);
          setError(null);
          if (
            next.items.some(
              (t) => t.status === 'queued' || t.status === 'running',
            )
          ) {
            timer = setTimeout(refresh, 5000);
          }
        }
      } catch (reason) {
        if (!controller.signal.aborted) setError(displayError(reason));
      }
    }
    void refresh();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [jobId, revision]);

  const task = state?.items[0];
  if (!task && !error) return null;
  async function retry() {
    setBusy(true);
    setError(null);
    retryKey.current ??= createUuid();
    try {
      await createWatermarkTask(
        { job_id: jobId },
        { headers: { 'Idempotency-Key': retryKey.current } },
      );
      retryKey.current = null;
      setRevision((n) => n + 1);
    } catch (reason) {
      setError(displayError(reason));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Item variant="muted">
      <ItemContent>
        <ItemTitle>自动去水印</ItemTitle>
        <p className="text-sm text-muted-foreground" role="status">
          {task?.error_code === 'unsupported_media'
            ? '暂不支持此视频规格的自动修补，原片可正常保存'
            : task
              ? labels[task.status]
              : '无法读取处理状态'}
          {task?.status === 'queued' && state && !state.available
            ? '，等待处理服务连接。'
            : null}
        </p>
        {error ? (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : null}
        {task?.status === 'succeeded' ? (
          <div className="flex flex-wrap gap-2">
            <Button asChild>
              <a download href={`/api/watermarks/${task.id}/file`}>
                保存处理版
              </a>
            </Button>
            <Button asChild variant="outline">
              <a download href={`/api/downloads/${jobId}/file`}>
                保存原片
              </a>
            </Button>
          </div>
        ) : null}
        {task &&
        (task.status === 'failed' || task.status === 'cancelled') &&
        task.error_code !== 'unsupported_media' &&
        state?.available ? (
          <Button
            disabled={busy}
            variant="outline"
            onClick={() => void retry()}
          >
            {busy ? '正在重试…' : '重试自动处理'}
          </Button>
        ) : null}
      </ItemContent>
    </Item>
  );
}
