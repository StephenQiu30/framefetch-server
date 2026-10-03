'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { createContentAnalysis, getContentSource } from '@/api/analyses';
import { listHistoryRecords } from '@/api/downloadIntents';
import { historyRecordStatus } from '@/components/intake/history-record-presentation';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageHeader } from '@/components/layout/page-header';
import { Button } from '@/components/ui/button';
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';
import { createUuid } from '@/lib/uuid';

const types = {
  article: '公众号文章',
  post: '短帖子',
  guide: '说明文档',
} as const;

export default function ContentWorkspace() {
  const router = useRouter();
  const sourceId = useSearchParams().get('sourceAnalysisId');
  const applied = useRef<string | null>(null);
  const original = useQuery({
    queryKey: privateQueryKey('content-source', sourceId),
    enabled: Boolean(sourceId),
    queryFn: ({ signal }) =>
      getContentSource({ analysis_id: sourceId ?? '' }, { signal }),
  });
  const [documentType, setDocumentType] =
    useState<API.ContentBrief['document_type']>('article');
  const [purpose, setPurpose] = useState('');
  const [audience, setAudience] = useState('');
  const [voice, setVoice] = useState('');
  const [materials, setMaterials] = useState<API.ContentMaterial[]>([
    { id: 'material-1', title: '', text: '', role: 'source' },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const requestRef = useRef<{ body: string; key: string } | undefined>(
    undefined,
  );
  const pending = useRef(false);
  const sequence = useRef(1);
  const history = useQuery({
    queryKey: privateQueryKey('content-history'),
    queryFn: ({ signal }) =>
      listHistoryRecords(
        { record_type: ['content_creation'], limit: 10 },
        { signal, paramsSerializer: { indexes: null } },
      ),
  });

  useEffect(() => {
    if (!sourceId || !original.data || applied.current === sourceId) return;
    applied.current = sourceId;
    setMaterials(original.data.materials);
    setPurpose(original.data.brief.purpose);
    setAudience(original.data.brief.audience ?? '');
    setVoice(original.data.brief.voice ?? '');
    setDocumentType(original.data.brief.document_type);
    sequence.current = 8;
  }, [sourceId, original.data]);

  function changeMaterial(id: string, values: Partial<API.ContentMaterial>) {
    setMaterials((current) =>
      current.map((item) => (item.id === id ? { ...item, ...values } : item)),
    );
  }
  const ready =
    purpose.trim() &&
    materials.every((item) => item.title.trim() && item.text.trim()) &&
    materials.some((item) => item.role === 'source');

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!ready || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError(undefined);
    const input: API.ContentAnalysisRequest = {
      source: {
        materials,
        brief: {
          document_type: documentType,
          purpose: purpose.trim(),
          ...(audience.trim() ? { audience: audience.trim() } : {}),
          ...(voice.trim() ? { voice: voice.trim() } : {}),
        },
      },
      output_language: 'zh-CN',
    };
    const body = JSON.stringify(input);
    const operation =
      requestRef.current?.body === body
        ? requestRef.current
        : { body, key: createUuid() };
    requestRef.current = operation;
    try {
      const job = await createContentAnalysis(input, {
        headers: { 'Idempotency-Key': operation.key },
      });
      router.push(`/analyses/detail?analysisId=${encodeURIComponent(job.id)}`);
    } catch (reason) {
      setError(displayError(reason));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="inner-page">
      <PageHeader
        title="内容创作"
        description="把材料写成文章、帖子或说明文档。提供已有事实和写作目的，也可以加入作者范文。"
      />
      {original.error ? (
        <FeedbackNotice
          title="原材料读取失败"
          description={displayError(original.error)}
          tone="error"
          action={<Button onClick={() => void original.refetch()}>重试</Button>}
        />
      ) : null}
      {original.isFetching && sourceId ? (
        <p role="status">正在读取原材料…</p>
      ) : null}
      <form className="mt-8 grid gap-8" onSubmit={submit}>
        <FieldGroup className="max-w-3xl">
          <Field>
            <FieldLabel htmlFor="content-type">用途</FieldLabel>
            <Select
              value={documentType}
              onValueChange={(value) =>
                setDocumentType(value as API.ContentBrief['document_type'])
              }
              disabled={busy}
            >
              <SelectTrigger id="content-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(types).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor="content-purpose">希望读者了解什么</FieldLabel>
            <Textarea
              id="content-purpose"
              value={purpose}
              onChange={(event) => setPurpose(event.target.value)}
              maxLength={2000}
              required
              disabled={busy}
              placeholder="例如：介绍这次试用的观察，让读者了解杯盖旋紧后的表现。"
            />
          </Field>
          <div className="grid gap-5 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="content-audience">读者（选填）</FieldLabel>
              <Input
                id="content-audience"
                value={audience}
                onChange={(event) => setAudience(event.target.value)}
                maxLength={400}
                disabled={busy}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="content-voice">表达偏好（选填）</FieldLabel>
              <Input
                id="content-voice"
                value={voice}
                onChange={(event) => setVoice(event.target.value)}
                maxLength={800}
                disabled={busy}
                placeholder="例如：简洁，保留我的口语表达"
              />
            </Field>
          </div>
        </FieldGroup>
        {materials.map((item, index) => (
          <FieldSet key={item.id} className="max-w-3xl">
            <FieldLegend>材料 {index + 1}</FieldLegend>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor={`${item.id}-title`}>材料名称</FieldLabel>
                <Input
                  id={`${item.id}-title`}
                  value={item.title}
                  onChange={(event) =>
                    changeMaterial(item.id, { title: event.target.value })
                  }
                  maxLength={200}
                  required
                  disabled={busy}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor={`${item.id}-role`}>材料用途</FieldLabel>
                <Select
                  value={item.role ?? 'source'}
                  onValueChange={(value) =>
                    changeMaterial(item.id, {
                      role: value as API.ContentMaterial['role'],
                    })
                  }
                  disabled={busy}
                >
                  <SelectTrigger id={`${item.id}-role`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="source">事实材料</SelectItem>
                    <SelectItem value="author_style">作者范文</SelectItem>
                  </SelectContent>
                </Select>
                <FieldDescription>
                  作者范文用于参考表达，文章中的事实来自事实材料。
                </FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor={`${item.id}-text`}>材料内容</FieldLabel>
                <Textarea
                  id={`${item.id}-text`}
                  value={item.text}
                  onChange={(event) =>
                    changeMaterial(item.id, { text: event.target.value })
                  }
                  rows={7}
                  maxLength={40000}
                  required
                  disabled={busy}
                />
              </Field>
            </FieldGroup>
            {materials.length > 1 ? (
              <Button
                type="button"
                variant="ghost"
                className="self-start"
                disabled={busy}
                onClick={() =>
                  setMaterials((current) =>
                    current.filter((value) => value.id !== item.id),
                  )
                }
              >
                移除材料 {index + 1}
              </Button>
            ) : null}
          </FieldSet>
        ))}
        <div className="flex flex-wrap gap-3">
          <Button
            type="button"
            variant="outline"
            disabled={busy || materials.length >= 8}
            onClick={() => {
              do {
                sequence.current += 1;
              } while (
                materials.some(
                  (item) => item.id === `material-${sequence.current}`,
                )
              );
              setMaterials((current) => [
                ...current,
                {
                  id: `material-${sequence.current}`,
                  title: '',
                  text: '',
                  role: 'source',
                },
              ]);
            }}
          >
            添加材料
          </Button>
          <Button type="submit" disabled={busy || !ready}>
            {busy ? '正在提交…' : '开始创作'}
          </Button>
        </div>
        {error ? (
          <FeedbackNotice
            title="创作请求未完成"
            description={error}
            tone="error"
          />
        ) : null}
      </form>
      <section className="mt-12" aria-label="最近创作">
        <h2 className="text-xl font-medium">最近创作</h2>
        {history.isPending ? (
          <p className="mt-4" role="status">
            正在读取…
          </p>
        ) : null}
        {history.error ? (
          <FeedbackNotice
            title="创作记录读取失败"
            description={displayError(history.error)}
            tone="error"
            action={
              <Button onClick={() => void history.refetch()}>重试</Button>
            }
          />
        ) : null}
        {history.data?.items.length === 0 ? (
          <PageEmptyNotice
            title="还没有创作记录"
            description="提交材料后，可以在这里继续查看。"
          />
        ) : null}
        <ul className="mt-4 grid gap-4">
          {history.data?.items.map((item) => (
            <li key={item.id}>
              <Link
                className="focus-ring text-base underline-offset-4 hover:underline"
                href={`/analyses/detail?analysisId=${encodeURIComponent(item.id)}`}
              >
                {item.title ?? '内容创作'}
              </Link>
              <p className="mt-1 text-sm text-muted-foreground">
                {historyRecordStatus(item)}
              </p>
            </li>
          ))}
        </ul>
        <Button asChild variant="ghost" className="mt-4">
          <Link href="/history/activity">查看全部处理记录</Link>
        </Button>
      </section>
    </div>
  );
}
