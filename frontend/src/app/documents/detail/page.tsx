import { Suspense } from 'react';
import { ProtectedRoute } from '@/components/auth/protected-route';
import { DocumentDetailSkeleton } from '@/components/screenplay/screenplay-document-detail-view';
import ScreenplayDocumentRoute from '@/components/screenplay/screenplay-document-route';

export const metadata = { title: '剧本文档详情' };

export default function DocumentDetailPage() {
  return (
    <ProtectedRoute>
      <Suspense fallback={<DocumentDetailSkeleton />}>
        <ScreenplayDocumentRoute />
      </Suspense>
    </ProtectedRoute>
  );
}
