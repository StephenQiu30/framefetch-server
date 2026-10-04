'use client';

import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex } from '@noble/hashes/utils.js';
import Image from 'next/image';
import { isCreationObject } from './creation-structured-editor';

export function CreationFrames({
  data,
  materials,
}: {
  data: Record<string, unknown>;
  materials: API.CreationMaterialResponse[];
}) {
  const inputs = Array.isArray(data.frames) ? data.frames.slice(0, 12) : [];
  const frames = inputs.flatMap((item) => {
    const frame = validatedFrame(item);
    return frame ? [frame] : [];
  });
  const references = Array.isArray(data.media_evidence)
    ? data.media_evidence.slice(0, 200).filter(isCreationObject)
    : [];
  if (!inputs.length && !references.length) return null;
  return (
    <section aria-label="抽样帧与视频依据" className="grid gap-5">
      <h3 className="font-medium">抽样帧与视频依据</h3>
      <p className="text-sm text-muted-foreground">
        以下是此次处理实际提供的抽样帧缩略图。帧号、时间和材料指纹保留在本版本中；抽样画面不能代表全片，模型的观察和推断仍需人工核查。
      </p>
      {frames.length < inputs.length ? (
        <p role="alert" className="text-sm">
          部分帧预览未通过
          PNG、大小或指纹校验，已停止展示。请核查原材料和任务结果。
        </p>
      ) : null}
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {frames.map((frame) => (
          <figure
            key={frame.id}
            id={`creation-frame-${frame.id}`}
            className="grid min-w-0 content-start gap-3"
          >
            <Image
              src={frame.url}
              alt={`${materials.find((item) => item.id === frame.materialId)?.title ?? '源视频'} ${frameTime(frame.timestamp)} 的实际抽样帧`}
              width={frame.width}
              height={frame.height}
              unoptimized
              className="h-auto max-w-full"
            />
            <figcaption className="grid gap-2 text-sm">
              <span className="break-words">
                {materials.find((item) => item.id === frame.materialId)
                  ?.title ?? '源材料未在当前列表中'}{' '}
                · {frameTime(frame.timestamp)}
              </span>
              <details className="min-w-0">
                <summary className="cursor-pointer">查看帧与来源指纹</summary>
                <p className="mt-2 break-all text-xs text-muted-foreground">
                  帧号：{frame.id}
                  <br />
                  材料版本：{frame.materialHash}
                  <br />
                  原始帧：{frame.frameHash}
                </p>
              </details>
            </figcaption>
          </figure>
        ))}
      </div>
      {references.length ? (
        <ul className="grid gap-4">
          {references.map((reference) => {
            const frame = frames.find(
              (item) =>
                item.id === reference.frame_id &&
                item.materialId === reference.material_id &&
                item.materialHash === reference.sha256 &&
                item.timestamp === reference.timestamp_ms,
            );
            const claim =
              typeof reference.claim === 'string'
                ? reference.claim
                : '视频依据需要核查。';
            return (
              <li
                key={`${String(reference.frame_id)}-${String(reference.material_id)}-${String(reference.status)}-${claim}`}
                className="grid gap-2 text-sm"
              >
                <p className="whitespace-pre-wrap break-words">{claim}</p>
                <p className="text-muted-foreground">
                  {referenceLabels[String(reference.status)] ?? '待核候选'}
                </p>
                {frame ? (
                  <a
                    href={`#creation-frame-${frame.id}`}
                    className="w-fit underline underline-offset-4"
                  >
                    回看对应抽样帧 · {frameTime(frame.timestamp)}
                  </a>
                ) : (
                  <p>
                    该引用未匹配可安全显示的具体帧，不能用其他画面替代依据。
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}

function validatedFrame(value: unknown) {
  if (
    !isCreationObject(value) ||
    typeof value.id !== 'string' ||
    value.id.length === 0 ||
    value.id.length > 120 ||
    typeof value.material_id !== 'string' ||
    typeof value.timestamp_ms !== 'number' ||
    !Number.isSafeInteger(value.timestamp_ms) ||
    value.timestamp_ms < 0 ||
    typeof value.preview_data_base64 !== 'string' ||
    value.preview_data_base64.length > 64_000 ||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u.test(
      value.preview_data_base64,
    ) ||
    value.preview_media_type !== 'image/png' ||
    typeof value.preview_width !== 'number' ||
    !Number.isInteger(value.preview_width) ||
    value.preview_width < 1 ||
    value.preview_width > 256 ||
    typeof value.preview_height !== 'number' ||
    !Number.isInteger(value.preview_height) ||
    value.preview_height < 1 ||
    value.preview_height > 256 ||
    typeof value.material_revision_sha256 !== 'string' ||
    !/^[a-f0-9]{64}$/u.test(value.material_revision_sha256) ||
    typeof value.frame_sha256 !== 'string' ||
    !/^[a-f0-9]{64}$/u.test(value.frame_sha256) ||
    typeof value.preview_sha256 !== 'string' ||
    !/^[a-f0-9]{64}$/u.test(value.preview_sha256)
  )
    return undefined;
  try {
    const bytes = Uint8Array.from(
      atob(value.preview_data_base64),
      (character) => character.charCodeAt(0),
    );
    const signature = [137, 80, 78, 71, 13, 10, 26, 10];
    if (
      bytes.length < 24 ||
      bytes.length > 48_000 ||
      signature.some((byte, index) => bytes[index] !== byte) ||
      String.fromCharCode(...bytes.slice(12, 16)) !== 'IHDR' ||
      new DataView(bytes.buffer).getUint32(16) !== value.preview_width ||
      new DataView(bytes.buffer).getUint32(20) !== value.preview_height ||
      bytesToHex(sha256(bytes)) !== value.preview_sha256
    )
      return undefined;
    return {
      id: value.id,
      materialId: value.material_id,
      materialHash: value.material_revision_sha256,
      timestamp: value.timestamp_ms,
      frameHash: value.frame_sha256,
      width: value.preview_width,
      height: value.preview_height,
      url: `data:image/png;base64,${value.preview_data_base64}`,
    };
  } catch {
    return undefined;
  }
}

function frameTime(value: number): string {
  const hours = Math.floor(value / 3_600_000);
  const minutes = Math.floor((value % 3_600_000) / 60_000);
  const seconds = Math.floor((value % 60_000) / 1000);
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(value % 1000).padStart(3, '0')}`;
}

const referenceLabels: Record<string, string> = {
  observation: '观察候选 · 需人工核查',
  inference: '推断候选 · 需人工核查',
  suggestion: '创作建议 · 需人工判断',
  unverified: '未核实 · 需补充依据',
};
