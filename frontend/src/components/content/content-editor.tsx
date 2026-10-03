'use client';

import { useRef, useState } from 'react';
import { reviseContent } from '@/api/analyses';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { Button } from '@/components/ui/button';
import { Field, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { displayError } from '@/lib/request-error';
import { createUuid } from '@/lib/uuid';

export default function ContentEditor({
  analysisId,
  reportId,
  result,
  onSaved,
}: {
  analysisId: string;
  reportId: string;
  result: API.ContentDocumentResult;
  onSaved: () => Promise<unknown>;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(result.title);
  const [blocks, setBlocks] = useState(result.blocks);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const pending = useRef(false);
  const operation = useRef<{ body: string; key: string } | undefined>(
    undefined,
  );
  const changed =
    JSON.stringify({ title, blocks }) !==
    JSON.stringify({ title: result.title, blocks: result.blocks });

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (pending.current || !changed) return;
    pending.current = true;
    setBusy(true);
    setError(undefined);
    const changedIds = new Set(
      blocks
        .filter(
          (block) =>
            JSON.stringify(block) !==
            JSON.stringify(result.blocks.find((old) => old.id === block.id)),
        )
        .map((block) => block.id),
    );
    const input: API.ContentRevisionRequest = {
      base_report_id: reportId,
      draft: {
        document_type: result.document_type,
        language: result.language,
        title,
        blocks,
        evidence_index: result.evidence_index.filter(
          (citation) => !changedIds.has(citation.block_id),
        ),
      },
    };
    const body = JSON.stringify(input);
    const request =
      operation.current?.body === body
        ? operation.current
        : { body, key: createUuid() };
    operation.current = request;
    try {
      await reviseContent({ analysis_id: analysisId }, input, {
        headers: { 'Idempotency-Key': request.key },
      });
      setEditing(false);
      await onSaved();
    } catch (reason) {
      setError(displayError(reason));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  if (!editing)
    return (
      <Button
        variant="outline"
        className="self-start"
        onClick={() => {
          setTitle(result.title);
          setBlocks(result.blocks);
          setEditing(true);
        }}
      >
        修改正文
      </Button>
    );
  return (
    <form
      className="grid max-w-3xl gap-5"
      onSubmit={save}
      aria-label="修改正文"
    >
      <p className="text-sm text-muted-foreground">
        保存为新版本，原稿与原导出文件保留。人工修改后需要重新核对，原审阅结论不再适用。
      </p>
      {title !== null ? (
        <Field>
          <FieldLabel htmlFor="revision-title">标题</FieldLabel>
          <Input
            id="revision-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={200}
            required
            disabled={busy}
          />
        </Field>
      ) : null}
      {blocks.map((block, index) => (
        <Field key={block.id}>
          <FieldLabel htmlFor={`revision-${block.id}`}>
            第 {index + 1} 段
            {block.type === 'heading'
              ? ' · 小标题'
              : block.type === 'list'
                ? ' · 列表，每行一项'
                : ''}
          </FieldLabel>
          <Textarea
            id={`revision-${block.id}`}
            disabled={busy}
            required
            value={block.type === 'list' ? block.items.join('\n') : block.text}
            maxLength={block.type === 'heading' ? 200 : 12000}
            rows={block.type === 'heading' ? 2 : 5}
            onChange={(event) => {
              const value = event.target.value;
              setBlocks((current) =>
                current.map((item) =>
                  item.id === block.id
                    ? item.type === 'list'
                      ? { ...item, items: value.split('\n') }
                      : { ...item, text: value }
                    : item,
                ),
              );
            }}
          />
        </Field>
      ))}
      <div className="flex gap-3">
        <Button type="submit" disabled={busy || !changed}>
          {busy ? '正在保存…' : '保存新版本'}
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={busy}
          onClick={() => setEditing(false)}
        >
          取消
        </Button>
      </div>
      {error ? (
        <FeedbackNotice
          title="修订稿保存失败"
          tone="error"
          description={error}
        />
      ) : null}
    </form>
  );
}
