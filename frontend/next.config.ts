import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  agentRules: false,
  poweredByHeader: false,
  // Cookie-only metadata is cheap; emit it in head for HTML-only search clients.
  htmlLimitedBots: /.*/,
  // API routes are forwarded to FastAPI without a trailing slash. Disabling
  // Next's global redirect preserves POST bodies across every browser,
  // including Safari/WebKit.
  skipTrailingSlashRedirect: true,
  trailingSlash: true,
  output: 'standalone',
  experimental: {
    // A 10 MiB document/image becomes about 14 MiB in its JSON base64 envelope.
    // FastAPI still enforces the smaller per-route limits and validates files.
    proxyClientMaxBodySize: '16mb',
  },
  images: {
    unoptimized: true,
    remotePatterns: [
      { protocol: 'http', hostname: '**' },
      { protocol: 'https', hostname: '**' },
    ],
  },
};

export default nextConfig;
