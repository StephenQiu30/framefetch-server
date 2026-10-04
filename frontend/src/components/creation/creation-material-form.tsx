'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useRef, useState } from 'react';
import { getDownloadHistory } from '@/api/downloads';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
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

export function CreationMaterialForm({
  projectId,
  busy,
  onSubmit,
}: {
  projectId: string;
  busy: boolean;
  onSubmit: (input: API.CreationMaterialCreateRequest) => Promise<boolean>;
}) {
  const [kind, setKind] =
    useState<API.CreationMaterialCreateRequest['kind']>('text');
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [rights, setRights] = useState('');
  const [accepted, setAccepted] = useState(false);
  const [sourceId, setSourceId] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [image, setImage] = useState<string>();
  const [document, setDocument] = useState<string>();
  const [filename, setFilename] = useState('');
  const [reading, setReading] = useState(false);
  const [fileError, setFileError] = useState<string>();
  const fileInput = useRef<HTMLInputElement>(null);
  const downloads = useQuery({
    queryKey: privateQueryKey('creation-owned-video'),
    enabled: kind === 'video',
    queryFn: ({ signal }) =>
      getDownloadHistory(
        { page: 1, page_size: 50, status: 'succeeded' },
        { signal },
      ),
  });
  const locked = busy || reading;
  const readable =
    kind === 'video'
      ? Boolean(sourceId)
      : kind === 'image'
        ? Boolean(image)
        : Boolean(
            text.trim() ||
              document ||
              (kind === 'reference' && sourceUrl.trim()),
          );

  async function readFile(file: File | undefined) {
    if (!file) return;
    setFileError(undefined);
    setReading(true);
    try {
      if (kind === 'image') {
        if (
          !['image/png', 'image/jpeg', 'image/webp'].includes(file.type) ||
          file.size > 10 * 1024 * 1024
        )
          throw new Error(
            '请选择不超过 10 MiB 的 PNG、JPEG 或静态 WebP 原图。',
          );
        setImage(await fileBase64(file));
      } else if (/\.(docx|pdf)$/iu.test(file.name)) {
        if (file.size > 10 * 1024 * 1024 || file.name.length > 200)
          throw new Error(
            '请选择文件名不超过 200 字符、不超过 10 MiB 的 DOCX 或 PDF。',
          );
        setDocument(await fileBase64(file));
        setText('');
        setSourceId('');
        setSourceUrl('');
      } else {
        if (
          !/\.(txt|md|markdown|fountain|srt|vtt)$/iu.test(file.name) ||
          file.size > 120_000
        )
          throw new Error(
            '请选择不超过 30,000 字符的 UTF-8 文本、Markdown、Fountain 或字幕文件。',
          );
        let content: string;
        try {
          content = new TextDecoder('utf-8', { fatal: true }).decode(
            await file.arrayBuffer(),
          );
        } catch {
          throw new Error('文件不是有效 UTF-8 文本，请转换编码后导入。');
        }
        if (Array.from(content).length > 30_000)
          throw new Error('材料超过 30,000 字符，请按任务范围拆分。');
        setText(content);
        setDocument(undefined);
      }
      setFilename(file.name);
      setTitle((current) => current || file.name);
    } catch (reason) {
      setFileError(reason instanceof Error ? reason.message : '文件读取失败。');
      setImage(undefined);
      setDocument(undefined);
      setFilename('');
      if (fileInput.current) fileInput.current.value = '';
    } finally {
      setReading(false);
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (
      locked ||
      fileError ||
      !accepted ||
      !readable ||
      !title.trim() ||
      !rights.trim()
    )
      return;
    const input: API.CreationMaterialCreateRequest = {
      project_id: projectId,
      kind,
      title: title.trim(),
      rights_statement: rights.trim(),
      ...(text.trim() && kind !== 'image' && kind !== 'video' ? { text } : {}),
      ...(kind === 'video' ? { download_id: sourceId } : {}),
      ...(kind === 'reference' && sourceUrl.trim()
        ? { source_url: sourceUrl.trim() }
        : {}),
      ...(kind === 'image' && image ? { image_data_base64: image } : {}),
      ...(kind === 'image' && filename ? { data: { filename } } : {}),
      ...(document && filename
        ? { document_filename: filename, document_data_base64: document }
        : {}),
    };
    if (await onSubmit(input)) {
      setTitle('');
      setText('');
      setSourceId('');
      setSourceUrl('');
      setImage(undefined);
      setDocument(undefined);
      setFilename('');
      if (fileInput.current) fileInput.current.value = '';
      setAccepted(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid gap-5">
      <FieldGroup>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field>
            <FieldLabel htmlFor="creation-material-kind">材料类型</FieldLabel>
            <Select
              value={kind}
              disabled={locked}
              onValueChange={(value) => {
                setKind(value as API.CreationMaterialCreateRequest['kind']);
                setSourceId('');
                setSourceUrl('');
                setImage(undefined);
                setDocument(undefined);
                setFilename('');
                setFileError(undefined);
                if (fileInput.current) fileInput.current.value = '';
              }}
            >
              <SelectTrigger id="creation-material-kind">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(kindLabels).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor="creation-material-title">材料标题</FieldLabel>
            <Input
              id="creation-material-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              maxLength={200}
              disabled={locked}
              required
            />
          </Field>
        </div>
        {kind === 'video' ? (
          <Field>
            <FieldLabel htmlFor="creation-owned-source">
              选择自己的已导入文件
            </FieldLabel>
            <Select
              value={sourceId}
              onValueChange={(value) => {
                setSourceId(value);
                setDocument(undefined);
                setFilename('');
                setFileError(undefined);
              }}
              disabled={locked}
            >
              <SelectTrigger
                id="creation-owned-source"
                className="data-placeholder:text-foreground"
              >
                <SelectValue placeholder="从已有文件中选择" />
              </SelectTrigger>
              <SelectContent>
                {downloads.data?.items
                  .filter((item) => item.file_available)
                  .map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.title}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
            <FieldDescription>
              <Link
                href="/downloads/new"
                className="underline underline-offset-4"
              >
                导入新的视频
              </Link>
              ，再返回选择。服务器会重新核对文件归属与可用性。
            </FieldDescription>
            {downloads.error ? (
              <FieldError>{displayError(downloads.error)}</FieldError>
            ) : null}
          </Field>
        ) : null}
        {kind !== 'video' ? (
          <Field>
            <FieldLabel htmlFor="creation-material-file">
              {kind === 'image'
                ? '选择授权图片'
                : '导入本地文档或文字文件（选填）'}
            </FieldLabel>
            <Input
              ref={fileInput}
              id="creation-material-file"
              type="file"
              disabled={locked}
              accept={
                kind === 'image'
                  ? 'image/png,image/jpeg,image/webp'
                  : '.txt,.md,.markdown,.fountain,.srt,.vtt,.docx,.pdf'
              }
              onChange={(event) => void readFile(event.target.files?.[0])}
            />
            {filename ? (
              <FieldDescription>
                {filename} 已读取；
                {document
                  ? '保存时提取文档正文，再核对确认。'
                  : '保存材料后仍需核对确认。'}
              </FieldDescription>
            ) : null}
            {reading ? <p role="status">正在读取本地文件…</p> : null}
            {fileError ? <FieldError>{fileError}</FieldError> : null}
            {(document || fileError) && kind !== 'image' ? (
              <Button
                type="button"
                variant="outline"
                className="w-fit"
                disabled={locked}
                onClick={() => {
                  setDocument(undefined);
                  setFilename('');
                  setFileError(undefined);
                  if (fileInput.current) fileInput.current.value = '';
                }}
              >
                改用粘贴正文
              </Button>
            ) : null}
            {kind !== 'image' ? (
              <FieldDescription>
                DOCX/PDF 不超过 10 MiB，提取正文不超过 30,000 字符；扫描 PDF
                需先转换成可读文字。纯文本使用
                UTF-8；已有剧本文档请上传实际原文件， 再核对提取正文。
              </FieldDescription>
            ) : (
              <FieldDescription>
                PNG、JPEG 或静态 WebP 原图不超过 10 MiB；动图不参与页卡配图。
              </FieldDescription>
            )}
          </Field>
        ) : null}
        {kind !== 'video' && kind !== 'image' && !document ? (
          <Field>
            <FieldLabel htmlFor="creation-material-text">材料正文</FieldLabel>
            <Textarea
              id="creation-material-text"
              rows={8}
              value={text}
              onChange={(event) => setText(event.target.value)}
              disabled={locked}
              maxLength={30_000}
              placeholder="保留原始事实、引用与写作内容；可先整理材料，再确认参与任务的版本。"
            />
          </Field>
        ) : null}
        {kind === 'reference' && !document ? (
          <Field>
            <FieldLabel htmlFor="creation-source-url">
              有权公开网页（选填）
            </FieldLabel>
            <Input
              id="creation-source-url"
              type="url"
              value={sourceUrl}
              onChange={(event) => setSourceUrl(event.target.value)}
              maxLength={2048}
              disabled={locked}
            />
            <FieldDescription>
              只访问明确的公开只读范围；不绕过登录或保护，也不会后台抓取外部图片。
            </FieldDescription>
          </Field>
        ) : null}
        <Field>
          <FieldLabel htmlFor="creation-rights">权利与用途说明</FieldLabel>
          <Input
            id="creation-rights"
            value={rights}
            onChange={(event) => setRights(event.target.value)}
            maxLength={2000}
            disabled={locked}
            required
            placeholder="例如：本人原创，允许用于本次文章与图卡整理。"
          />
        </Field>
        <Field orientation="horizontal">
          <Checkbox
            id="creation-rights-accepted"
            checked={accepted}
            disabled={locked}
            onCheckedChange={(value) => setAccepted(value === true)}
          />
          <FieldLabel htmlFor="creation-rights-accepted">
            我有权使用这些材料，并同意按上述用途处理
          </FieldLabel>
        </Field>
      </FieldGroup>
      <div>
        <Button
          disabled={
            locked ||
            Boolean(fileError) ||
            !accepted ||
            !readable ||
            !title.trim() ||
            !rights.trim()
          }
          type="submit"
        >
          {busy ? '正在保存…' : '保存待确认材料'}
        </Button>
      </div>
    </form>
  );
}

function fileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () =>
      typeof reader.result === 'string'
        ? resolve(reader.result.split(',')[1] ?? '')
        : reject(new Error('文件读取失败。'));
    reader.onerror = () => reject(new Error('文件读取失败。'));
    reader.readAsDataURL(file);
  });
}

export const kindLabels: Record<
  API.CreationMaterialCreateRequest['kind'],
  string
> = {
  text: '文章或创作需求',
  screenplay: '剧本',
  video: '源视频',
  subtitle: '字幕',
  image: '授权图片',
  reference: '参考资料',
};
