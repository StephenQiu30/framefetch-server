import type { Metadata } from 'next';
import '@/styles/globals.css';
import { notFound } from 'next/navigation';
import { Toaster } from '@/components/ui/sonner';
import { DocumentEditor } from '@/components/workspace/document-editor';

export const metadata: Metadata = {
  title: '编辑文档',
  robots: { index: false },
};

type EditPageProps = { searchParams: Promise<{ path?: string }> };

export default async function EditPage({ searchParams }: EditPageProps) {
  const { path } = await searchParams;
  if (!path?.endsWith('.md')) notFound();
  return (
    <main className="mx-auto w-full max-w-4xl px-4">
      <DocumentEditor
        path={path}
        webUrl={process.env.WEB_URL ?? 'http://127.0.0.1:8101'}
      />
      <Toaster />
    </main>
  );
}
