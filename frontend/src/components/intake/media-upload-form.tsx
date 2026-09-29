'use client';

import { FileVideo, UploadSimple, X } from '@phosphor-icons/react';
import { type FormEvent, useRef } from 'react';

import {
  IntakeControlRow,
  IntakePickerButton,
  IntakeSubmitButton,
} from '@/components/intake/intake-control-row';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { Progress } from '@/components/ui/progress';
import { Spinner } from '@/components/ui/spinner';
import { formatFileSize } from '@/lib/format';
import type { ImportPhase } from '@/lib/upload/import-lifecycle';

const phaseLabels: Record<ImportPhase, string> = {
  idle: '准备上传',
  hashing: '正在计算文件校验值',
  creating: '正在创建上传任务',
  uploading: '正在分片上传',
  completing: '正在提交服务端验证',
  cancelling: '正在取消上传',
};

export function MediaUploadForm({
  busy,
  canCancel,
  file,
  fileInvalid,
  onCancel,
  onFileSelect,
  onStart,
  phase,
  progress,
  declaredOrigin,
}: {
  busy: boolean;
  canCancel: boolean;
  file: File | null;
  fileInvalid: boolean;
  onCancel: () => void;
  onFileSelect: (file: File | null) => void;
  onStart: () => void;
  phase: ImportPhase;
  progress: number;
  declaredOrigin: API.DeclaredOrigin;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onStart();
  };

  return (
    <Form className="flex flex-col gap-4" onSubmit={submit}>
      {declaredOrigin === 'wechat_channels' ? (
        <p className="text-sm leading-6 text-muted-foreground">
          当前文件将记录为“用户提供的视频号来源”，系统不会接收视频号链接、会话或令牌。
        </p>
      ) : null}
      <IntakeControlRow data-invalid={fileInvalid || undefined}>
        <div className="min-w-0 flex-1">
          <IntakePickerButton
            aria-describedby={
              fileInvalid ? 'download-workspace-error' : undefined
            }
            aria-invalid={fileInvalid || undefined}
            className="w-full"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
            size="xl"
            variant="outline"
          >
            <FileVideo aria-hidden data-icon="inline-start" />
            <span className="min-w-0 truncate" title={file?.name}>
              {file
                ? `${file.name} · ${formatFileSize(file.size)}`
                : '选择本地 MP4 视频'}
            </span>
          </IntakePickerButton>
        </div>
        <IntakeSubmitButton disabled={busy} size="xl">
          {busy ? (
            <Spinner aria-hidden data-icon="inline-start" />
          ) : (
            <UploadSimple aria-hidden data-icon="inline-start" />
          )}
          {busy ? '处理中…' : '上传视频'}
        </IntakeSubmitButton>
      </IntakeControlRow>
      <input
        accept="video/mp4,.mp4"
        aria-label="选择本地 MP4 视频文件"
        className="sr-only"
        disabled={busy}
        onChange={(event) => onFileSelect(event.target.files?.[0] ?? null)}
        onClick={(event) => {
          event.currentTarget.value = '';
        }}
        ref={inputRef}
        tabIndex={-1}
        type="file"
      />
      {busy ? (
        <div>
          <div className="mb-3 flex min-h-9 items-center justify-between gap-4">
            <p aria-live="polite" className="text-sm" role="status">
              {phaseLabels[phase]}
            </p>
            <div className="flex items-center gap-3">
              <span
                aria-hidden
                className="text-xs text-muted-foreground tabular-nums"
              >
                {progress}%
              </span>
              {canCancel ? (
                <Button onClick={onCancel} size="sm" variant="ghost">
                  <X aria-hidden data-icon="inline-start" />
                  取消上传
                </Button>
              ) : null}
            </div>
          </div>
          <Progress aria-label={phaseLabels[phase]} value={progress} />
        </div>
      ) : null}
    </Form>
  );
}
