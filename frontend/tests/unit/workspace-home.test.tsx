import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { WorkspaceHome } from '@/components/intake/workspace-home';
import { TooltipProvider } from '@/components/ui/tooltip';
import { render } from '../helpers/query-render';

vi.mock('@/components/auth/auth-provider', async (importOriginal) => ({
  ...(await importOriginal()),
  useAuth: () => ({ user: { id: 'intent-test-owner', role: 'user' } }),
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

describe('WorkspaceHome', () => {
  it('shows the direct content intake instead of a workspace explainer', () => {
    render(
      <TooltipProvider>
        <WorkspaceHome />
      </TooltipProvider>,
    );

    expect(screen.getByLabelText('公开视频地址')).toBeInTheDocument();
    expect(
      screen.getByRole('tablist', { name: '选择内容来源' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '链接下载' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '本地视频' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '剧本文档' })).toBeInTheDocument();
    expect(
      screen.queryByRole('link', { name: '新建下载' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('选择素材，')).not.toBeInTheDocument();
  });
});
