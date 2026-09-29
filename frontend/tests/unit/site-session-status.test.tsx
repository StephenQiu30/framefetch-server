import { screen, within } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { SiteSessionStatus } from '@/components/admin/site-session-status';
import { render } from '../helpers/query-render';

vi.mock('@/api/admin', () => ({
  getAdminProviderRuntime: vi.fn().mockResolvedValue({
    items: [
      {
        provider_key: 'youtube',
        session_site: 'youtube.com',
        login_state: 'signed_in',
      },
      {
        provider_key: 'douyin',
        session_site: 'douyin.com',
        login_state: 'unavailable',
      },
    ],
  }),
}));

it('shows source readability without claiming verification or automatic maintenance', async () => {
  render(<SiteSessionStatus />);
  const youtube = (await screen.findByText('youtube.com')).closest('tr');
  const douyin = screen.getByText('douyin.com').closest('tr');
  expect(youtube).not.toBeNull();
  expect(douyin).not.toBeNull();
  expect(
    within(youtube as HTMLElement).getByText('登录态来源可读'),
  ).toBeVisible();
  expect(within(douyin as HTMLElement).getByText('暂时无法读取')).toBeVisible();
  expect(youtube).not.toHaveTextContent('登录状态已验证');
  expect(douyin).toHaveTextContent('读取权限');
  expect(screen.queryByText('下次检查')).not.toBeInTheDocument();
  expect(screen.queryByText('自动维护中')).not.toBeInTheDocument();
});
