'use client';

import { UploadSimple } from '@phosphor-icons/react';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useCallback, useState } from 'react';
import { useDocumentImport } from '@/components/intake/use-document-import';
import { ScreenplayUploadForm } from '@/components/screenplay/screenplay-upload-form';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { privateQueryKey } from '@/lib/query-keys';

export function ScreenplayUploadDialog({
  label = '上传剧本',
}: {
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const queries = useQueryClient();
  const openDocument = useCallback(
    (documentId: string) => {
      void queries.invalidateQueries({
        queryKey: privateQueryKey('documents'),
      });
      void queries.invalidateQueries({
        queryKey: privateQueryKey('intent-history'),
      });
      setOpen(false);
      router.push(
        `/documents/detail?documentId=${encodeURIComponent(documentId)}`,
      );
    },
    [queries, router],
  );
  const upload = useDocumentImport(openDocument);

  return (
    <Dialog
      onOpenChange={(next) => {
        if (!upload.busy) setOpen(next);
      }}
      open={open}
    >
      <DialogTrigger asChild>
        <Button className="w-full sm:w-auto">
          <UploadSimple aria-hidden data-icon="inline-start" />
          {label}
        </Button>
      </DialogTrigger>
      <DialogContent
        className="max-h-svh overflow-y-auto overscroll-contain sm:max-w-xl"
        onEscapeKeyDown={(event) => {
          if (upload.busy) event.preventDefault();
        }}
        onInteractOutside={(event) => {
          if (upload.busy) event.preventDefault();
        }}
        showCloseButton={!upload.busy}
      >
        <DialogHeader>
          <DialogTitle>上传剧本文档</DialogTitle>
          <DialogDescription>
            支持 DOCX、PDF、TXT、Markdown 和 Fountain，单文件最大 50
            MB。上传后将自动提取并校验规范化剧本。
          </DialogDescription>
        </DialogHeader>
        <ScreenplayUploadForm
          busy={upload.busy}
          canCancel={upload.canCancel}
          error={upload.error}
          file={upload.file}
          fileInvalid={upload.fileInvalid}
          onCancel={() => void upload.cancel()}
          onFileSelect={upload.selectFile}
          onStart={() => void upload.start()}
          phase={upload.phase}
          progress={upload.progress}
        />
      </DialogContent>
    </Dialog>
  );
}
