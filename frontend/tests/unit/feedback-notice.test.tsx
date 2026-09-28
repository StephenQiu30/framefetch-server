import { render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { FeedbackNotice } from '@/components/layout/feedback-notice';

const errorToast = vi.hoisted(() => vi.fn());
vi.mock('sonner', () => ({ toast: { error: errorToast } }));

it('delivers operation feedback once without adding an inline alert', async () => {
  const notice = (
    <FeedbackNotice
      presentation="toast"
      title="操作未完成"
      description="请重试"
      tone="error"
    />
  );
  const view = render(notice);
  await waitFor(() => expect(errorToast).toHaveBeenCalledTimes(1));
  expect(errorToast).toHaveBeenCalledWith(
    '操作未完成',
    expect.objectContaining({ description: '请重试', id: expect.any(String) }),
  );
  expect(screen.queryByRole('alert')).toBeNull();
  view.rerender(
    <FeedbackNotice
      presentation="toast"
      title="操作未完成"
      description="请重试"
      tone="error"
    />,
  );
  expect(errorToast).toHaveBeenCalledTimes(1);
  view.rerender(
    <FeedbackNotice
      presentation="toast"
      title="操作未完成"
      description="连接已中断"
      tone="error"
    />,
  );
  await waitFor(() => expect(errorToast).toHaveBeenCalledTimes(2));
  expect(errorToast.mock.calls[0][1].id).toBe(errorToast.mock.calls[1][1].id);
});

it('keeps persistent recovery actions and field descriptions inline', () => {
  render(
    <FeedbackNotice
      title="刷新失败"
      description="上次结果仍可查看"
      descriptionId="recovery-description"
      tone="error"
      action={<button type="button">恢复同步</button>}
    />,
  );
  expect(screen.getByRole('alert')).toHaveTextContent('上次结果仍可查看');
  expect(screen.getByRole('button', { name: '恢复同步' })).toBeVisible();
  expect(document.getElementById('recovery-description')).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveAttribute('data-slot', 'empty');
});

it('keeps brief errors in the compact alert treatment', () => {
  render(
    <FeedbackNotice title="操作未完成" description="请检查输入" tone="error" />,
  );
  expect(screen.getByRole('alert')).toHaveAttribute('data-slot', 'alert');
});
