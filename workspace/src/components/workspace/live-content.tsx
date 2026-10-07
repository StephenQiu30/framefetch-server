'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect } from 'react';

export function LiveContent({ revision }: { revision: string }) {
  const router = useRouter();
  const pathname = usePathname();
  useEffect(() => {
    // 编辑期间不刷新，避免干扰未保存的文档；回到阅读页会读取当前内容。
    if (pathname === '/edit') return;
    let current = revision;
    let pending = false;
    const controller = new AbortController();
    const check = async () => {
      if (pending || document.visibilityState !== 'visible') return;
      pending = true;
      try {
        const response = await fetch('/content-revision', {
          cache: 'no-store',
          signal: controller.signal,
        });
        if (!response.ok) return;
        const next = ((await response.json()) as { revision: string }).revision;
        if (next !== current && !controller.signal.aborted) {
          current = next;
          window.dispatchEvent(new Event('workspace-content-changed'));
          router.refresh();
        }
      } catch {
        // 临时断线后下次轮询重试，保留已展示的内容。
      } finally {
        pending = false;
      }
    };
    const timer = setInterval(() => void check(), 2000);
    document.addEventListener('visibilitychange', check);
    return () => {
      clearInterval(timer);
      controller.abort();
      document.removeEventListener('visibilitychange', check);
    };
  }, [revision, pathname, router]);
  return null;
}
