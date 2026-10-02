'use client';

import { ArrowLeftIcon } from '@phosphor-icons/react';
import Link from 'next/link';
import type { MouseEvent } from 'react';
import { useCanNavigateBack } from '@/components/layout/navigation-history';
import { markNavigationPush } from '@/components/layout/navigation-state';
import { Button } from '@/components/ui/button';

type BackLinkProps = {
  className?: string;
  fallbackHref: string;
  label?: string;
};

export function BackLink({
  className,
  fallbackHref,
  label = '返回上一步',
}: BackLinkProps) {
  const canGoBack = useCanNavigateBack();

  function navigateBack(event: MouseEvent<HTMLAnchorElement>) {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }

    if (!canGoBack || window.history.length <= 1) {
      markNavigationPush(fallbackHref);
      return;
    }

    event.preventDefault();
    window.history.back();
  }

  return (
    <Button asChild className={className} variant="ghost">
      <Link data-navigation-back="" href={fallbackHref} onClick={navigateBack}>
        <ArrowLeftIcon aria-hidden data-icon="inline-start" />
        {label}
      </Link>
    </Button>
  );
}
