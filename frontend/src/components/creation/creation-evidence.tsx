'use client';

import { useState } from 'react';
import { CreationFrames } from './creation-frames';
import { CreationSourceRevision } from './creation-source-revision';
import { isCreationObject } from './creation-structured-editor';

export function CreationEvidence({
  data,
  materials,
}: {
  data: Record<string, unknown>;
  materials: API.CreationMaterialResponse[];
}) {
  const evidence = Array.isArray(data.evidence) ? data.evidence : [];
  const unverified = Array.isArray(data.unverified) ? data.unverified : [];
  return (
    <div className="grid gap-6">
      <CreationFrames data={data} materials={materials} />
      {unverified.length ? (
        <section aria-label="待核事项" className="grid gap-3">
          <h3 className="font-medium">待核事项</h3>
          <ul className="grid list-disc gap-2 pl-5">
            {unverified.map((item, index) => (
              <li key={typeof item === 'string' ? item : `unverified-${index}`}>
                {typeof item === 'string'
                  ? item
                  : isCreationObject(item) && typeof item.text === 'string'
                    ? item.text
                    : '这项材料需要人工核查。'}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <section aria-label="结果依据" className="grid gap-3">
        <h3 className="font-medium">依据与源材料</h3>
        {evidence.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            本版本没有可回查的事实证据。创作建议与格式处理不会因此被标记为已核实事实。
          </p>
        ) : null}
        {evidence.map((item, index) => {
          if (!isCreationObject(item)) return null;
          const material = materials.find(
            (entry) => entry.id === item.material_id,
          );
          const quote = typeof item.quote === 'string' ? item.quote : '';
          return (
            <EvidenceSource
              key={`${String(item.material_id)}-${String(item.sha256)}-${String(item.start)}-${String(item.end)}-${quote}`}
              material={material}
              item={item}
              label={quote || `依据 ${index + 1}`}
            />
          );
        })}
      </section>
    </div>
  );
}

function EvidenceSource({
  material,
  item,
  label,
}: {
  material: API.CreationMaterialResponse | undefined;
  item: Record<string, unknown>;
  label: string;
}) {
  const [open, setOpen] = useState(false);
  const sha256 = typeof item.sha256 === 'string' ? item.sha256 : undefined;
  const sameVersion =
    sha256 !== undefined && material?.current_revision.sha256 === sha256;
  return (
    <details
      className="min-w-0"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer break-words py-2">
        {label} · {material?.title ?? '源材料'}
      </summary>
      {sameVersion ? (
        <p className="whitespace-pre-wrap break-words text-sm leading-6">
          {material?.current_revision.text}
        </p>
      ) : open && material && sha256 ? (
        <CreationSourceRevision materialId={material.id} sha256={sha256} />
      ) : (
        <p className="text-sm">
          这条依据对应历史或未明确的材料版本，当前原文不能替代其来源。
        </p>
      )}
      {typeof item.start === 'number' && typeof item.end === 'number' ? (
        <p className="mt-2 text-sm text-muted-foreground">
          原文字符 {item.start}–{item.end}
        </p>
      ) : null}
    </details>
  );
}
