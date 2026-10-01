'use client';

import { FileText, UploadSimple, X } from '@phosphor-icons/react';
import { type FormEvent, useId, useRef } from 'react';

import {
  IntakeControlRow,
  IntakePickerButton,
  IntakeSubmitButton,
} from '@/components/intake/intake-control-row';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import { Spinner } from '@/components/ui/spinner';
import { formatFileSize } from '@/lib/format';
import type { ImportPhase } from '@/lib/upload/import-lifecycle';

const phaseLabels: Record<ImportPhase, string> = {
  idle: '准备上传',
  hashing: '正在计算文件校验值',
  creating: '正在创建剧本文档',
  uploading: '正在分片上传',
  completing: '正在提交解析验证',
  cancelling: '正在取消上传',
};

type ScreenplayUploadFormProps = {
  busy: boolean;
  canCancel: boolean;
  error: string | null;
  file: File | null;
  fileInvalid: boolean;
  layout?: 'dialog' | 'workspace';
  onCancel: () => void;
  onFileSelect: (file: File | null) => void;
  onStart: () => void;
  phase: ImportPhase;
  progress: number;
};

export function ScreenplayUploadForm({
  busy,
  canCancel,
  error,
  file,
  fileInvalid,
  layout = 'dialog',
  onCancel,
  onFileSelect,
  onStart,
  phase,
  progress,
}: ScreenplayUploadFormProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const descriptionId = useId();
  const workspace = layout === 'workspace';
  const canStart = !busy && !!file && !fileInvalid;
  const describedBy =
    error && fileInvalid
      ? `${descriptionId} screenplay-upload-error`
      : descriptionId;
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (canStart) onStart();
  };

  const filePicker = (
    <IntakePickerButton
      aria-describedby={describedBy}
      aria-invalid={fileInvalid || undefined}
      className="w-full"
      disabled={busy}
      onClick={() => inputRef.current?.click()}
      size={workspace ? 'xl' : undefined}
      variant={workspace ? 'outline' : undefined}
    >
      <FileText aria-hidden data-icon="inline-start" />
      <span className="min-w-0 truncate" title={file?.name}>
        {file
          ? `${file.name} · ${formatFileSize(file.size)}`
          : workspace
            ? '选择剧本文档（PDF、DOCX 等）'
            : '选择剧本文档'}
      </span>
    </IntakePickerButton>
  );
  const fileInput = (
    <Input
      accept=".docx,.pdf,.txt,.md,.markdown,.fountain"
      aria-describedby={describedBy}
      aria-invalid={fileInvalid || undefined}
      aria-label="选择剧本文档文件"
      className="hidden"
      disabled={busy}
      onChange={(event) => onFileSelect(event.target.files?.[0] ?? null)}
      onClick={(event) => {
        event.currentTarget.value = '';
      }}
      ref={inputRef}
      tabIndex={-1}
      type="file"
    />
  );
  const fileDescription = (
    <p
      className={
        workspace
          ? 'text-sm leading-6 text-muted-foreground'
          : 'mt-2 text-xs text-muted-foreground'
      }
      id={descriptionId}
    >
      支持 DOCX、PDF、TXT、Markdown 和 Fountain
      格式。选择文件后，点击“上传剧本”开始导入。
    </p>
  );
  const errorNotice = error ? (
    <FeedbackNotice
      presentation={fileInvalid ? 'inline' : 'toast'}
      className="mt-3"
      descriptionId="screenplay-upload-error"
      title="无法上传剧本"
      description={error}
      tone="error"
    />
  ) : null;
  const progressNotice = busy ? (
    <div className="mt-4">
      <div className="mb-3 flex min-h-9 items-center justify-between gap-4">
        <p aria-live="polite" className="text-sm" role="status">
          {phaseLabels[phase]}
        </p>
        <div className="flex items-center gap-3">
          <span
            aria-hidden
            className="text-xs tabular-nums text-muted-foreground"
          >
            {progress}%
          </span>
          {canCancel ? (
            <Button onClick={onCancel} size="sm" type="button" variant="ghost">
              <X aria-hidden data-icon="inline-start" />
              取消上传
            </Button>
          ) : null}
        </div>
      </div>
      <Progress aria-label={phaseLabels[phase]} value={progress} />
    </div>
  ) : null;

  if (workspace) {
    return (
      <Form className="flex flex-col gap-4" onSubmit={submit}>
        <IntakeControlRow data-invalid={fileInvalid || undefined}>
          <div className="min-w-0 flex-1">{filePicker}</div>
          <IntakeSubmitButton disabled={!canStart}>
            {busy ? (
              <Spinner aria-hidden data-icon="inline-start" />
            ) : (
              <UploadSimple aria-hidden data-icon="inline-start" />
            )}
            {busy ? '处理中…' : '上传剧本'}
          </IntakeSubmitButton>
        </IntakeControlRow>
        {fileDescription}
        {fileInput}
        {errorNotice}
        {progressNotice}
      </Form>
    );
  }

  return (
    <Form className="mt-2" onSubmit={submit}>
      {filePicker}
      {fileInput}
      {fileDescription}
      {errorNotice}
      {progressNotice}
      <Button className="mt-5 w-full" disabled={!canStart} type="submit">
        {busy ? (
          <Spinner aria-hidden data-icon="inline-start" />
        ) : (
          <UploadSimple aria-hidden data-icon="inline-start" />
        )}
        {busy ? '处理中…' : '上传剧本'}
      </Button>
    </Form>
  );
}
