import { Suspense } from 'react';
import { ProtectedRoute } from '@/components/auth/protected-route';
import ContentWorkspace from '@/components/content/content-workspace';

export const metadata = { title: '内容创作' };

export default function ContentPage() {
  return (
    <ProtectedRoute>
      <Suspense fallback={<p role="status">正在读取…</p>}>
        <ContentWorkspace />
      </Suspense>
    </ProtectedRoute>
  );
}
