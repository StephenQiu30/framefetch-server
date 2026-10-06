import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PublicHome } from '@/components/intake/public-home';

describe('PublicHome', () => {
  it('keeps the public conversion and documentation paths available', () => {
    render(<PublicHome />);

    expect(screen.getByRole('link', { name: /创建本地账户/ })).toHaveAttribute(
      'href',
      '/user/register',
    );
    expect(screen.getByRole('link', { name: /查看源代码/ })).toHaveAttribute(
      'href',
      'https://github.com/StephenQiu30/video-server',
    );
    expect(screen.getByRole('link', { name: /阅读部署说明/ })).toHaveAttribute(
      'href',
      'https://github.com/StephenQiu30/video-server/blob/main/README.md#快速开始',
    );
  });

  it('describes the downloader and its public content boundary', () => {
    render(<PublicHome />);
    expect(
      screen.getByRole('heading', {
        level: 1,
        name: 'FrameFetch 万能视频下载器',
      }),
    ).toBeInTheDocument();
    expect(
      within(
        screen.getByRole('region', { name: '下载、导入与分析' }),
      ).getByText(/检查公开、免费、非 DRM 的视频链接，选择实际可用的格式/),
    ).toBeInTheDocument();
    expect(
      within(
        screen.getByRole('region', { name: '下载、导入与分析' }),
      ).getByText(/导入有权处理的本地视频/),
    ).toBeInTheDocument();
  });

  it('keeps the workflow as an ordered accessible list', () => {
    render(<PublicHome />);

    const workflow = screen.getByRole('list', { name: '使用步骤' });

    expect(workflow.tagName).toBe('OL');
    expect(within(workflow).getAllByRole('listitem')).toHaveLength(4);
  });

  it('keeps the welcome page free of structural card and separator chrome', () => {
    const { container } = render(<PublicHome />);

    expect(
      container.querySelector('[data-slot="card"]'),
    ).not.toBeInTheDocument();
    expect(
      container.querySelector('[data-slot="separator"]'),
    ).not.toBeInTheDocument();
  });
});
