import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import { Head, Search } from 'nextra/components';
import { getPageMap } from 'nextra/page-map';
import { Footer, Layout, Navbar } from 'nextra-theme-docs';
import type { ReactNode } from 'react';
import 'nextra-theme-docs/style.css';

const geistSans = Geist({ variable: '--font-geist-sans', subsets: ['latin'] });
const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});
const repository = 'https://github.com/StephenQiu30/framefetch-server';

export const metadata: Metadata = {
  title: { default: '帧取工作区', template: '%s · 帧取工作区' },
  description: '帧取的知识库、产品文稿与系统设计',
  icons: { icon: [{ url: '/logo.svg', type: 'image/svg+xml' }] },
};

const logo = (
  <span className="x:flex x:items-center x:gap-2">
    {/* biome-ignore lint/performance/noImgElement: static brand asset shared with Web */}
    <img src="/logo.svg" alt="" width={24} height={24} />
    <span className="x:font-medium">帧取工作区</span>
  </span>
);

export default async function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <html
      lang="zh-CN"
      dir="ltr"
      suppressHydrationWarning
      className={`${geistSans.className} ${geistSans.variable} ${geistMono.variable}`}
    >
      <Head color={{ hue: 0, saturation: 0 }} />
      <body data-design="borderless">
        <Layout
          navbar={<Navbar logo={logo} logoLink="/" projectLink={repository} />}
          pageMap={await getPageMap()}
          docsRepositoryBase={`${repository}/blob/main/workspace`}
          editLink="在 GitHub 查看源文件"
          feedback={{ content: null }}
          toc={{ title: '本页目录', backToTop: '回到顶部' }}
          footer={<Footer>帧取 · 单人自托管视频工作站</Footer>}
          search={
            <Search
              placeholder="搜索文档…"
              emptyResult="没有找到相关内容"
              loading="正在搜索…"
              errorText="无法加载搜索索引，请先运行 pnpm build。"
            />
          }
          themeSwitch={{ dark: '深色', light: '浅色', system: '跟随系统' }}
          copyPageButton={false}
        >
          {children}
        </Layout>
      </body>
    </html>
  );
}
