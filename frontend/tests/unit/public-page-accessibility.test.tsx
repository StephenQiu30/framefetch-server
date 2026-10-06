import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import AboutPage from '@/app/about/page';
import GuidePage from '@/app/guide/page';
import SelfHostingPage from '@/app/self-hosting/page';
import { PublicHome } from '@/components/intake/public-home';

describe('public page list semantics', () => {
  it.each([
    ['homepage', PublicHome],
    ['about', AboutPage],
    ['guide', GuidePage],
    ['self-hosting', SelfHostingPage],
  ])('gives every declared list on %s actual list items', (_name, Page) => {
    const document = new DOMParser().parseFromString(
      renderToStaticMarkup(<Page />),
      'text/html',
    );

    for (const list of document.querySelectorAll('[role="list"]')) {
      expect(list.children.length).toBeGreaterThan(0);
      for (const child of list.children) {
        expect(child.getAttribute('role')).toBe('listitem');
      }
    }
  });

  it('composes the guide directory with shadcn navigation and named regions', () => {
    const document = new DOMParser().parseFromString(
      renderToStaticMarkup(<GuidePage />),
      'text/html',
    );
    const navigation = document.querySelector('nav[aria-label="指南目录"]');
    expect(navigation).toHaveAttribute('data-slot', 'navigation-menu');
    expect(navigation).toHaveAttribute('data-orientation', 'vertical');
    const links =
      navigation?.querySelectorAll(
        '[data-slot="navigation-menu-list"] > [data-slot="navigation-menu-item"] > a[data-slot="navigation-menu-link"]',
      ) ?? [];
    expect(links).toHaveLength(5);
    for (const link of links) {
      const target = document.getElementById(
        link.getAttribute('href')?.slice(1) ?? '',
      );
      expect(target?.tagName).toBe('SECTION');
      expect(target?.hasAttribute('role')).toBe(false);
      expect(
        document.getElementById(target?.getAttribute('aria-labelledby') ?? ''),
      ).not.toBeNull();
    }
  });

  it.each([GuidePage, SelfHostingPage])(
    'uses shadcn navigation for further reading with real link destinations',
    (Page) => {
      const document = new DOMParser().parseFromString(
        renderToStaticMarkup(<Page />),
        'text/html',
      );
      const navigation = document.querySelector('nav[aria-label="延伸阅读"]');
      expect(navigation).toHaveAttribute('data-slot', 'navigation-menu');
      const links =
        navigation?.querySelectorAll('[data-slot="navigation-menu-link"]') ??
        [];
      expect(links.length).toBeGreaterThan(0);
      for (const link of links) {
        expect(link.tagName).toBe('A');
        expect(link.getAttribute('href')).toBeTruthy();
      }
    },
  );
});
