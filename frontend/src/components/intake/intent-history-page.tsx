'use client';

import { useRouter } from 'next/navigation';
import { IntentHistory } from '@/components/intake/intent-history';
import { markNavigationPush } from '@/components/layout/navigation-history';

export function IntentHistoryPage() {
  const router = useRouter();

  return (
    <IntentHistory
      onViewResult={(item) => {
        if (!item.inspection_id) return;
        const target = `/downloads/new?inspectionId=${encodeURIComponent(item.inspection_id)}&intentId=${encodeURIComponent(item.id)}`;
        markNavigationPush(target);
        router.push(target);
      }}
    />
  );
}
