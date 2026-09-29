import { Suspense } from 'react';
import { ProtectedRoute } from '@/components/auth/protected-route';
import DownloadRoute from '@/components/downloads/download-route';
import { PageNavigation } from '@/components/layout/page-navigation';
import { MediaResultSkeleton } from '@/components/media/media-result';

export const metadata = { title: '下载任务' };

export default function DownloadDetailPage() {
  return (
    <ProtectedRoute>
      <Suspense fallback={<DetailSkeleton />}>
        <DownloadRoute />
      </Suspense>
    </ProtectedRoute>
  );
}

function DetailSkeleton() {
  return (
    <div className="inner-page">
      <PageNavigation fallbackHref="/history" />
      <MediaResultSkeleton label="正在读取下载任务" />
    </div>
  );
}
