'use client';

import Image from 'next/image';
import { useEffect, useState } from 'react';
import { getCreationMaterialImage } from '@/api/creation';
import { displayError } from '@/lib/request-error';

export function CreationMaterialImage({
  materialId,
  title,
}: {
  materialId: string;
  title: string;
}) {
  const [url, setUrl] = useState<string>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | undefined;
    setError(undefined);
    setUrl(undefined);
    void getCreationMaterialImage(
      { material_id: materialId },
      { signal: controller.signal, responseType: 'blob' },
    )
      .then((blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(displayError(reason));
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [materialId]);
  return error ? (
    <p role="alert">图片读取失败：{error}</p>
  ) : url ? (
    <div className="relative h-96 w-full">
      <Image
        src={url}
        alt={title}
        fill
        unoptimized
        sizes="(min-width: 1024px) 50vw, 100vw"
        className="object-contain"
      />
    </div>
  ) : (
    <p role="status">正在读取已保存的原图…</p>
  );
}
