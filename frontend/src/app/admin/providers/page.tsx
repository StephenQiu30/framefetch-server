import { AdminProviderCatalogView } from '@/components/admin/admin-provider-catalog-view';
import { ProtectedRoute } from '@/components/auth/protected-route';

export const metadata = { title: '平台目录' };

export default function AdminProvidersPage() {
  return (
    <ProtectedRoute requireAdmin>
      <div className="inner-page">
        <AdminProviderCatalogView />
      </div>
    </ProtectedRoute>
  );
}
