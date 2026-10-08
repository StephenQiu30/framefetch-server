import nextra from 'nextra';
import remarkRepoLinks from './lib/remark-repo-links.mjs';

const withNextra = nextra({
  defaultShowCopyCode: true,
  mdxOptions: { remarkPlugins: [remarkRepoLinks] },
});

export default withNextra({
  output: 'standalone',
  allowedDevOrigins: ['127.0.0.1'],
  outputFileTracingRoot: import.meta.dirname,
  // GitHub 习惯用 README.md 作为目录首页，站点目录地址指向它。
  async redirects() {
    return [{ source: '/:section(prd|design|plan)', destination: '/:section/README', permanent: false }];
  },
});
