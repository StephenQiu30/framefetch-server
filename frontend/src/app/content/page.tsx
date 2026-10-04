import { Suspense } from 'react';
import { ProtectedRoute } from '@/components/auth/protected-route';
import CreationWorkspace from '@/components/creation/creation-workspace';

export const metadata = { title: '内容创作' };

export default function ContentPage() {
  return (
    <ProtectedRoute>
      <Suspense fallback={<p role="status">正在读取…</p>}>
        <CreationWorkspace />
      </Suspense>
    </ProtectedRoute>
  );
}
