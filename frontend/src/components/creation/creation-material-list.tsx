'use client';

import { useState } from 'react';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field';
import { Textarea } from '@/components/ui/textarea';
import { kindLabels } from './creation-material-form';
import { CreationMaterialImage } from './creation-material-image';

export function CreationMaterialList({
  materials,
  selected,
  onSelect,
  busy,
  onSave,
  onConfirm,
}: {
  materials: API.CreationMaterialResponse[];
  selected: string[];
  onSelect: (ids: string[]) => void;
  busy: boolean;
  onSave: (
    material: API.CreationMaterialResponse,
    text: string,
  ) => Promise<void>;
  onConfirm: (material: API.CreationMaterialResponse) => Promise<void>;
}) {
  if (materials.length === 0) {
    return (
      <PageEmptyNotice
        compact
        title="还没有材料"
        description="先保存自己的文字、文件或资料，再核对并确认参与任务的版本。"
      />
    );
  }
  return (
    <div className="grid gap-6">
      {materials.map((material) => (
        <MaterialRow
          key={`${material.id}-${material.current_revision.id}`}
          material={material}
          busy={busy}
          selected={selected.includes(material.current_revision.id)}
          onSelect={(checked) =>
            onSelect(
              checked
                ? [...new Set([...selected, material.current_revision.id])]
                : selected.filter((id) => id !== material.current_revision.id),
            )
          }
          onSave={(text) => onSave(material, text)}
          onConfirm={() => onConfirm(material)}
        />
      ))}
    </div>
  );
}

function MaterialRow({
  material,
  busy,
  selected,
  onSelect,
  onSave,
  onConfirm,
}: {
  material: API.CreationMaterialResponse;
  busy: boolean;
  selected: boolean;
  onSelect: (checked: boolean) => void;
  onSave: (text: string) => Promise<void>;
  onConfirm: () => Promise<void>;
}) {
  const [text, setText] = useState(material.current_revision.text);
  const [open, setOpen] = useState(false);
  const dirty = text !== material.current_revision.text;
  return (
    <article className="grid min-w-0 gap-3">
      <Field orientation="horizontal">
        <Checkbox
          id={`creation-select-${material.id}`}
          disabled={busy || !material.current_revision.confirmed || dirty}
          checked={selected}
          onCheckedChange={(checked) => onSelect(checked === true)}
        />
        <FieldLabel
          htmlFor={`creation-select-${material.id}`}
          className="break-words"
        >
          {material.title}
        </FieldLabel>
        <Badge variant="secondary">
          {material.current_revision.confirmed ? '已确认' : '待确认'}
        </Badge>
      </Field>
      <p className="text-sm text-muted-foreground">
        {kindLabels[material.kind]} · 第 {material.current_revision.number} 版 ·{' '}
        {material.rights_statement}
      </p>
      {material.kind === 'image' &&
      typeof material.current_revision.data.filename === 'string' ? (
        <p className="break-words text-sm">
          图片文件名：{material.current_revision.data.filename}。母稿可用
          Markdown 图片引用此文件名，导出包会保留实际原图。
        </p>
      ) : null}
      <details
        className="min-w-0"
        onToggle={(event) => setOpen(event.currentTarget.open)}
      >
        <summary className="cursor-pointer py-2">核对原文与材料版本</summary>
        <div className="mt-3 grid gap-4">
          {open && material.kind === 'image' ? (
            <CreationMaterialImage
              materialId={material.id}
              title={material.title}
            />
          ) : null}
          {material.source_url ? (
            <p className="break-all text-sm">资料来源：{material.source_url}</p>
          ) : null}
          <Field>
            <FieldLabel htmlFor={`creation-source-${material.id}`}>
              材料正文 · {material.title}
            </FieldLabel>
            <Textarea
              id={`creation-source-${material.id}`}
              rows={6}
              disabled={
                busy || material.kind === 'video' || material.kind === 'image'
              }
              value={text}
              maxLength={100_000}
              onChange={(event) => setText(event.target.value)}
            />
            <FieldDescription>
              修改会保存为新版本，并影响使用旧材料的派生结果；原件和已有人工稿会保留。
            </FieldDescription>
          </Field>
          <p className="break-all text-xs text-muted-foreground">
            材料指纹：{material.current_revision.sha256}
          </p>
          <div className="flex flex-wrap gap-3">
            <Button
              type="button"
              variant="outline"
              disabled={busy || !dirty}
              onClick={() => void onSave(text)}
            >
              保存材料新版本
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy || dirty || material.current_revision.confirmed}
              onClick={() => void onConfirm()}
            >
              确认此材料版本
            </Button>
          </div>
        </div>
      </details>
      {!material.current_revision.confirmed ? (
        <Button
          className="w-fit"
          type="button"
          variant="outline"
          disabled={busy || dirty}
          onClick={() => void onConfirm()}
        >
          核对后确认材料
        </Button>
      ) : null}
    </article>
  );
}
