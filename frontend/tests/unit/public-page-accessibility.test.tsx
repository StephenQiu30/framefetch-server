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

  it('keeps guide links in a native list and content in named regions', () => {
    const document = new DOMParser().parseFromString(
      renderToStaticMarkup(<GuidePage />),
      'text/html',
    );
    const links = document.querySelectorAll(
      'nav[aria-label="指南目录"] ul > li > a',
    );
    expect(links.length).toBeGreaterThan(0);
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
});
