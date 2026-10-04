'use client';

import { useEffect, useState } from 'react';
import { exportCreationRevision } from '@/api/creation';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { Button } from '@/components/ui/button';
import { displayError } from '@/lib/request-error';
import { CreationSafePreview } from './creation-safe-preview';

export function CreationExports({
  task,
  formats,
  unsaved,
}: {
  task: API.CreationTaskResponse;
  formats: string[];
  unsaved: boolean;
}) {
  const [pending, setPending] = useState<string>();
  const [error, setError] = useState<string>();
  const [html, setHtml] = useState<string>();
  const revision = task.revision;
  useEffect(() => {
    if (revision?.id) setHtml(undefined);
  }, [revision?.id]);
  if (!revision) return null;

  async function exportFile(format: string, preview = false) {
    if (pending || !revision || unsaved || !revision.confirmed) return;
    setPending(preview ? 'preview' : format);
    setError(undefined);
    try {
      const file = await exportCreationRevision(
        { task_id: task.id, revision_id: revision.id, format },
        { responseType: 'blob' },
      );
      if (preview) {
        setHtml(await file.text());
      } else {
        const url = URL.createObjectURL(file);
        const link = document.createElement('a');
        link.href = url;
        link.download = `${task.skill_id}-revision-${revision.number}.${format === 'cards' ? 'zip' : format}`;
        document.body.append(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      }
    } catch (reason) {
      setError(displayError(reason));
    } finally {
      setPending(undefined);
    }
  }

  return (
    <section aria-label="实际文件交付" className="grid gap-4">
      <h3 className="font-medium">交付文件</h3>
      <p className="text-sm text-muted-foreground">
        文件绑定已保存的第 {revision.number}{' '}
        版确认稿。导出失败只重做导出，不重新执行模型。
        {!revision.confirmed
          ? ' 当前仍是候选稿，请先核查并确认采用，再交付文件。'
          : ''}
        {unsaved ? ' 当前修改还未保存，先保存后再导出。' : ''}
      </p>
      <div className="flex flex-wrap gap-3">
        {formats.map((format) => (
          <Button
            key={format}
            type="button"
            variant="outline"
            disabled={Boolean(pending) || unsaved || !revision.confirmed}
            onClick={() => void exportFile(format)}
          >
            {pending === format
              ? '正在生成文件…'
              : `导出${formatLabels[format] ?? format.toUpperCase()}`}
          </Button>
        ))}
        {formats.includes('html') ? (
          <Button
            type="button"
            variant="outline"
            disabled={Boolean(pending) || unsaved || !revision.confirmed}
            onClick={() => void exportFile('html', true)}
          >
            {pending === 'preview' ? '正在准备预览…' : '查看安全 HTML 预览'}
          </Button>
        ) : null}
      </div>
      {error ? (
        <FeedbackNotice
          title="文件交付未完成"
          description={error}
          tone="error"
          action={
            <Button variant="outline" onClick={() => setError(undefined)}>
              返回选择导出
            </Button>
          }
        />
      ) : null}
      {html !== undefined ? <CreationSafePreview html={html} /> : null}
    </section>
  );
}

const formatLabels: Record<string, string> = {
  md: ' Markdown',
  docx: ' DOCX',
  csv: ' CSV',
  srt: ' SRT',
  vtt: ' VTT',
  html: ' HTML',
  zip: '资源包',
  cards: '实际卡片包',
};
