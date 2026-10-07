import type { Metadata } from 'next';

import { absoluteUrl, siteConfig, siteIndexable } from '@/lib/site';

export const privateRobots: Metadata['robots'] = {
  index: false,
  follow: false,
  nosnippet: true,
};

export function publicMetadata(
  title: string,
  description: string,
  path: string,
): Metadata {
  return {
    title: { absolute: title },
    description,
    applicationName: siteConfig.name,
    alternates: { canonical: absoluteUrl(path) },
    openGraph: {
      type: 'website',
      locale: 'zh_CN',
      url: absoluteUrl(path),
      siteName: siteConfig.name,
      title,
      description,
      images: [
        {
          url: absoluteUrl('/opengraph-image/'),
          width: 1200,
          height: 630,
          alt: 'Framefetch — self-hosted video parsing and AI analysis',
        },
      ],
    },
    twitter: {
      card: 'summary_large_image',
      title,
      description,
      images: [absoluteUrl('/opengraph-image/')],
    },
    robots: siteIndexable
      ? {
          index: true,
          follow: true,
          googleBot: {
            index: true,
            follow: true,
            'max-image-preview': 'large',
            'max-snippet': -1,
            'max-video-preview': -1,
          },
        }
      : privateRobots,
  };
}
