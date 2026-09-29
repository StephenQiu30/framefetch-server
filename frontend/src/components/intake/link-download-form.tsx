'use client';

import { DownloadSimple } from '@phosphor-icons/react';
import type { ClipboardEvent, FormEvent, KeyboardEvent } from 'react';
import {
  IntakeControlRow,
  IntakeSubmitButton,
} from '@/components/intake/intake-control-row';
import { Form } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Spinner } from '@/components/ui/spinner';

export function LinkDownloadForm({
  busy,
  disabled,
  hasResult,
  invalid,
  onInspect,
  onUrlChange,
  url,
}: {
  busy: boolean;
  disabled: boolean;
  hasResult: boolean;
  invalid: boolean;
  onInspect: () => void;
  onUrlChange: (value: string) => void;
  url: string;
}) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onInspect();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
      event.preventDefault();
      onInspect();
    }
  };

  const handlePaste = (event: ClipboardEvent<HTMLInputElement>) => {
    const pasted = event.clipboardData.getData('text');
    if (!/[\r\n]/.test(pasted)) return;
    event.preventDefault();
    const start = event.currentTarget.selectionStart ?? url.length;
    const end = event.currentTarget.selectionEnd ?? start;
    onUrlChange(
      `${url.slice(0, start)}${pasted.replace(/\s+/g, ' ')}${url.slice(end)}`.slice(
        0,
        4096,
      ),
    );
  };

  return (
    <Form onSubmit={submit}>
      <IntakeControlRow data-invalid={invalid || undefined}>
        <div className="min-w-0 flex-1">
          <Input
            aria-describedby={invalid ? 'download-workspace-error' : undefined}
            aria-invalid={invalid || undefined}
            aria-label="公开视频地址"
            autoComplete="url"
            controlSize="xl"
            disabled={disabled}
            id="public-media-input"
            maxLength={4096}
            onChange={(event) => onUrlChange(event.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder="粘贴公开媒体链接或完整分享文案"
            value={url}
          />
        </div>
        <IntakeSubmitButton disabled={disabled}>
          {busy ? (
            <Spinner aria-hidden data-icon="inline-start" />
          ) : (
            <DownloadSimple aria-hidden data-icon="inline-start" />
          )}
          {busy ? '解析中…' : hasResult ? '重新解析' : '解析媒体'}
        </IntakeSubmitButton>
      </IntakeControlRow>
    </Form>
  );
}
