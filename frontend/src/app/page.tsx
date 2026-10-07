import type { Metadata } from 'next';
import { cookies } from 'next/headers';

import { HomeExperience } from '@/components/intake/home-experience';
import { PublicHome } from '@/components/intake/public-home';
import { publicQuestions } from '@/components/intake/public-home-content';
import { privateRobots, publicMetadata } from '@/lib/public-metadata';
import { absoluteUrl, siteConfig } from '@/lib/site';

const publicHomeMetadata = publicMetadata(
  siteConfig.title,
  siteConfig.description,
  '/',
);
const privateHomeMetadata: Metadata = {
  title: '工作区',
  robots: privateRobots,
};

const webCookieName = process.env.AUTH_WEB_COOKIE_NAME ?? 'video_web_session';

async function hasBrowserSession() {
  return (await cookies()).has(webCookieName);
}

export async function generateMetadata(): Promise<Metadata> {
  return (await hasBrowserSession()) ? privateHomeMetadata : publicHomeMetadata;
}

const structuredData = {
  '@context': 'https://schema.org',
  '@graph': [
    {
      '@type': 'WebSite',
      '@id': absoluteUrl('/#website'),
      url: absoluteUrl('/'),
      name: siteConfig.name,
      alternateName: 'Framefetch',
      description: siteConfig.description,
      inLanguage: 'zh-CN',
    },
    {
      '@type': 'SoftwareApplication',
      '@id': absoluteUrl('/#software'),
      name: siteConfig.name,
      alternateName: 'Framefetch',
      description: siteConfig.englishDescription,
      url: absoluteUrl('/'),
      sameAs: siteConfig.repositoryUrl,
      license: siteConfig.licenseUrl,
      applicationCategory: 'MultimediaApplication',
      applicationSubCategory: 'Media workflow and video analysis',
      operatingSystem: 'Web, Docker, Linux, macOS, Windows',
      featureList: [
        'Authorized public media link inspection and format selection',
        'Reliable asynchronous downloads with checksum verification',
        'Local video and screenplay import (Markdown, Fountain, TXT, PDF, DOCX)',
        'AI storyboard, scene and keyframe analysis',
        'Markdown and DOCX report export',
        'Flutter iOS and Android client',
      ],
      author: { '@id': absoluteUrl('/#maintainer') },
      softwareHelp: { '@type': 'WebPage', url: absoluteUrl('/guide/') },
      subjectOf: { '@id': absoluteUrl('/#source') },
    },
    {
      '@type': 'Person',
      '@id': absoluteUrl('/#maintainer'),
      name: siteConfig.maintainer.name,
      url: siteConfig.maintainer.url,
    },
    {
      '@type': 'SoftwareSourceCode',
      '@id': absoluteUrl('/#source'),
      targetProduct: { '@id': absoluteUrl('/#software') },
      isAccessibleForFree: true,
      name: 'Framefetch source code',
      description: siteConfig.englishDescription,
      codeRepository: siteConfig.repositoryUrl,
      license: siteConfig.licenseUrl,
      programmingLanguage: ['Python', 'TypeScript'],
      runtimePlatform: ['Docker', 'Node.js', 'Python'],
      author: { '@id': absoluteUrl('/#maintainer') },
    },
    {
      '@type': 'SoftwareSourceCode',
      '@id': absoluteUrl('/#mobile-source'),
      targetProduct: { '@id': absoluteUrl('/#software') },
      isAccessibleForFree: true,
      name: 'Framefetch Flutter iOS / Android client',
      codeRepository: siteConfig.mobileRepositoryUrl,
      programmingLanguage: 'Dart',
      runtimePlatform: ['iOS', 'Android'],
      author: { '@id': absoluteUrl('/#maintainer') },
    },
    {
      '@type': 'WebPage',
      '@id': absoluteUrl('/#webpage'),
      url: absoluteUrl('/'),
      name: siteConfig.title,
      description: siteConfig.description,
      inLanguage: 'zh-CN',
      isPartOf: { '@id': absoluteUrl('/#website') },
      about: { '@id': absoluteUrl('/#software') },
      hasPart: { '@id': absoluteUrl('/#questions') },
    },
    {
      '@type': 'FAQPage',
      '@id': absoluteUrl('/#questions'),
      mainEntity: publicQuestions.map(({ id, question, answer }) => ({
        '@type': 'Question',
        '@id': absoluteUrl(`/#${id}`),
        name: question,
        acceptedAnswer: { '@type': 'Answer', text: answer },
      })),
    },
  ],
};

export default async function HomePage() {
  const privateHome = await hasBrowserSession();

  return (
    <>
      {!privateHome ? (
        <script type="application/ld+json">
          {JSON.stringify(structuredData).replace(/</g, '\\u003c')}
        </script>
      ) : null}
      <HomeExperience
        initialPublic={!privateHome}
        publicHome={<PublicHome />}
      />
    </>
  );
}
