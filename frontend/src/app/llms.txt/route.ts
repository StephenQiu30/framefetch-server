import { publicQuestions } from '@/components/intake/public-home-content';
import { absoluteUrl, siteConfig, siteIndexable } from '@/lib/site';

// https://llmstxt.org — a plain-text map for generative search and AI agents.
export function GET() {
  if (!siteIndexable) return new Response('Not Found', { status: 404 });

  const body = `# ${siteConfig.name}

> ${siteConfig.englishDescription}

${siteConfig.description}

FrameFetch only processes content the user is authorized to use: public, free, non-DRM HTTP(S) media, local videos and screenplay documents. It is not a tool for bypassing paywalls, DRM, private or region-locked content. Source code is MIT licensed; infrastructure and external AI model costs are borne by the deployer. There is no official SaaS.

## Pages

- [首页 / Home](${absoluteUrl('/')}): product overview and FAQ
- [使用指南 / Guide](${absoluteUrl('/guide/')}): from media and screenplays to AI analysis reports
- [自托管部署 / Self-hosting](${absoluteUrl('/self-hosting/')}): Docker Compose requirements, steps, ports and production checklist
- [关于 / About](${absoluteUrl('/about/')}): audience, architecture principles, content boundaries and repositories

## Source

- [video-server](${siteConfig.repositoryUrl}): FastAPI API, Next.js web app, workers, isolated media runner, Docker Compose
- [video-app](${siteConfig.mobileRepositoryUrl}): Flutter iOS / Android client for a self-hosted video-server
- [English README](${siteConfig.repositoryUrl}/blob/main/README.en.md)
- [System design](${siteConfig.repositoryUrl}/blob/main/workspace/content/design/README.md)

## FAQ

${publicQuestions.map(({ question, answer }) => `### ${question}\n\n${answer}`).join('\n\n')}
`;

  return new Response(body, {
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Cache-Control': 'public, max-age=3600',
    },
  });
}
