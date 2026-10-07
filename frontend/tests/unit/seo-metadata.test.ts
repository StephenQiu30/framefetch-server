import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import manifest from '@/app/manifest';
import { resolveSiteUrl } from '@/lib/site';

beforeEach(() => vi.resetModules());
afterEach(() => vi.unstubAllEnvs());

describe('public SEO metadata', () => {
  it('publishes only public canonical pages when deployment opts into indexing', async () => {
    vi.stubEnv('SITE_INDEXABLE', 'true');
    vi.stubEnv('SITE_URL', 'https://framefetch.example');
    const { default: robots } = await import('@/app/robots');
    const { default: sitemap } = await import('@/app/sitemap');
    const { publicMetadata } = await import('@/lib/public-metadata');
    expect(robots().rules).toEqual([
      { userAgent: '*', allow: '/', disallow: ['/api', '/health'] },
      { userAgent: 'OAI-SearchBot', allow: '/', disallow: ['/api', '/health'] },
    ]);
    expect(robots().sitemap).toBe('https://framefetch.example/sitemap.xml');
    expect(sitemap()).toEqual([
      { url: 'https://framefetch.example/' },
      { url: 'https://framefetch.example/guide/' },
      { url: 'https://framefetch.example/self-hosting/' },
      { url: 'https://framefetch.example/about/' },
    ]);
    const metadata = publicMetadata('Guide', 'Description', '/guide/');
    expect(metadata.alternates?.canonical).toBe(
      'https://framefetch.example/guide/',
    );
    expect(metadata.robots).toMatchObject({ index: true, follow: true });
    expect(metadata.robots).not.toHaveProperty('nosnippet');
    expect(metadata.openGraph).toMatchObject({
      url: 'https://framefetch.example/guide/',
      description: 'Description',
    });
  });

  it.each([undefined, 'false', 'TRUE'])(
    'does not advertise a private deployment (%s)',
    async (setting) => {
      vi.stubEnv('SITE_INDEXABLE', setting);
      const { default: robots } = await import('@/app/robots');
      const { default: sitemap } = await import('@/app/sitemap');
      const { publicMetadata } = await import('@/lib/public-metadata');
      expect(sitemap()).toEqual([]);
      expect(robots().sitemap).toBeUndefined();
      expect(publicMetadata('Home', 'Description', '/').robots).toMatchObject({
        index: false,
        nosnippet: true,
      });
      // Crawlers can still retrieve HTML to see noindex, including after de-indexing.
      expect(robots().rules).toContainEqual({
        userAgent: '*',
        allow: '/',
        disallow: ['/api', '/health'],
      });
    },
  );

  it('serves llms.txt only for an indexable public site', async () => {
    vi.stubEnv('SITE_INDEXABLE', 'true');
    vi.stubEnv('SITE_URL', 'https://framefetch.example');
    const { GET } = await import('@/app/llms.txt/route');
    const response = GET();
    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toContain('text/plain');
    const body = await response.text();
    expect(body).toMatch(/^# 帧取 Framefetch\n\n> /);
    for (const path of ['/', '/guide/', '/self-hosting/', '/about/']) {
      expect(body).toContain(`(https://framefetch.example${path})`);
    }
    expect(body).toContain('### 帧取 Framefetch 是什么？');

    vi.resetModules();
    vi.stubEnv('SITE_INDEXABLE', 'false');
    const { GET: privateGet } = await import('@/app/llms.txt/route');
    expect(privateGet().status).toBe(404);
  });

  it('classifies only marketing pages as public', async () => {
    const { isPublicPage } = await import('@/lib/site');
    for (const path of ['/', '/guide', '/guide/', '/self-hosting/', '/about'])
      expect(isPublicPage(path)).toBe(true);
    for (const path of ['/history', '/account/', '/user/login', '/guides/'])
      expect(isPublicPage(path)).toBe(false);
  });

  it('rejects invalid or credential-bearing canonical origins', () => {
    expect(resolveSiteUrl(undefined).origin).toBe('http://127.0.0.1:8101');
    expect(
      resolveSiteUrl('https://framefetch.example/path?q=1#fragment').toString(),
    ).toBe('https://framefetch.example/');
    for (const value of [
      'framefetch.example',
      'ftp://framefetch.example',
      'https://user:password@framefetch.example',
    ]) {
      expect(() => resolveSiteUrl(value)).toThrow(
        'SITE_URL must be an absolute HTTP(S) URL',
      );
    }
  });

  it('describes an installable Framefetch web application', () => {
    expect(manifest()).toMatchObject({
      short_name: '帧取',
      start_url: '/',
      scope: '/',
      display: 'standalone',
    });
  });

  it('keeps private pages noindex by default', () => {
    const rootLayout = readFileSync(
      resolve(process.cwd(), 'src/app/layout.tsx'),
      'utf8',
    );
    expect(rootLayout).toContain('index: false');
    expect(rootLayout).not.toContain('description: siteConfig.description');
  });
});
