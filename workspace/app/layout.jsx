import { Footer, Layout, Navbar } from 'nextra-theme-docs';
import { Head } from 'nextra/components';
import { getPageMap } from 'nextra/page-map';
import 'nextra-theme-docs/style.css';

export const metadata = {
  title: { default: '帧取工作区', template: '%s · 帧取工作区' },
  description: '帧取服务端的产品需求、系统设计与执行计划',
};

const repository = 'https://github.com/StephenQiu30/framefetch-server';

export default async function RootLayout({ children }) {
  return (
    <html lang="zh-CN" dir="ltr" suppressHydrationWarning>
      <Head />
      <body>
        <Layout
          navbar={<Navbar logo={<b>帧取工作区</b>} projectLink={repository} />}
          pageMap={await getPageMap()}
          docsRepositoryBase={`${repository}/blob/main/workspace`}
          editLink="在 GitHub 上编辑此页"
          feedback={{ content: null }}
          toc={{ title: '本页目录', backToTop: '回到顶部' }}
          footer={<Footer>帧取 · 单人自托管视频工作站</Footer>}
        >
          {children}
        </Layout>
      </body>
    </html>
  );
}
