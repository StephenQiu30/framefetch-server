'use client';

import { useRouter } from 'next/navigation';
import { useAuth } from '@/components/auth/auth-provider';
import { useIntakeDraft } from '@/components/intake/intake-draft-provider';
import { IntentHistory } from '@/components/intake/intent-history';
import { rememberDownloadIntent } from '@/components/intake/use-download-intent';
import { markNavigationPush } from '@/components/layout/navigation-history';

export function IntentHistoryPage() {
  const router = useRouter();
  const { setAttempt, setMode } = useIntakeDraft();
  const { user } = useAuth();

  return (
    <IntentHistory
      onViewResult={(item) => {
        if (item.status === 'action_required' && user) {
          rememberDownloadIntent(user.id, item.id);
          setAttempt({ id: item.id, input: null, submitting: false });
          setMode('link');
          markNavigationPush('/');
          router.push('/');
          return;
        }
        if (!item.inspection_id) return;
        const target = `/downloads/new?inspectionId=${encodeURIComponent(item.inspection_id)}&intentId=${encodeURIComponent(item.id)}`;
        markNavigationPush(target);
        router.push(target);
      }}
    />
  );
}
