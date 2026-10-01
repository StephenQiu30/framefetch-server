import { AdminAnalyticsView } from '@/components/admin/admin-analytics-view';
import { ProtectedRoute } from '@/components/auth/protected-route';

export const metadata = { title: '使用统计' };

export default function AdminAnalyticsPage() {
  return (
    <ProtectedRoute requireAdmin>
      <div className="inner-page">
        <AdminAnalyticsView />
      </div>
    </ProtectedRoute>
  );
}
