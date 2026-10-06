import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  ContentIntakeHero,
  type IntakeMode,
} from '@/components/intake/content-intake-hero';

describe('ContentIntakeHero', () => {
  it('renders the controlled intake mode immediately', () => {
    const { rerender } = render(hero('link'));

    expect(screen.getByRole('tabpanel', { name: '链接下载' })).toBeVisible();

    rerender(hero('video'));

    expect(screen.getByRole('tab', { name: '本地视频' })).toHaveAttribute(
      'data-state',
      'active',
    );
    expect(screen.getByRole('tab', { name: '本地视频' })).not.toHaveFocus();
    expect(screen.getByRole('tabpanel', { name: '本地视频' })).toBeVisible();
  });

  it('keeps the source picker above the intake form at every viewport', () => {
    const { container } = render(hero('link'));

    expect(container.querySelector('[data-slot="tabs"]')).toHaveClass(
      'data-horizontal:flex-col',
    );
    expect(container.querySelector('[data-slot="tabs"]')).not.toHaveClass(
      'lg:flex-row',
    );
    expect(container.querySelector('[data-slot="tabs-list"]')).toHaveClass(
      'max-w-full',
    );
    expect(container.querySelector('[data-slot="tabs-list"]')).toHaveAttribute(
      'data-variant',
      'default',
    );
  });
});

function hero(mode: IntakeMode) {
  return (
    <ContentIntakeHero
      disabled={false}
      linkForm={<div>链接表单</div>}
      mode={mode}
      onModeChange={() => undefined}
      screenplayForm={<div>剧本表单</div>}
      videoForm={<div>视频表单</div>}
    />
  );
}
