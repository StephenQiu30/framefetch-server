import { act, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import DownloadWorkspace from '@/components/intake/download-workspace';
import { IntakeDraftProvider } from '@/components/intake/intake-draft-provider';
import { QueryProvider } from '@/components/layout/query-provider';
import { TooltipProvider } from '@/components/ui/tooltip';
import { advanceSessionGeneration } from '@/lib/session-events';

vi.mock('@/components/auth/auth-provider', async (importOriginal) => ({
  ...(await importOriginal()),
  useAuth: () => ({ user: { id: 'intent-test-owner', role: 'user' } }),
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

function Routes() {
  const [shown, setShown] = useState(true);
  return (
    <>
      <button type="button" onClick={() => setShown(!shown)}>
        切换测试页面
      </button>
      {shown ? <DownloadWorkspace /> : <div>Other page</div>}
    </>
  );
}

function Application() {
  return (
    <QueryProvider>
      <IntakeDraftProvider>
        <TooltipProvider>
          <Routes />
        </TooltipProvider>
      </IntakeDraftProvider>
    </QueryProvider>
  );
}

describe('identity-owned intake draft', () => {
  it('restores pasted text and selected mode after the route unmounts', () => {
    render(<Application />);
    fireEvent.change(screen.getByLabelText('公开视频地址'), {
      target: {
        value: '分享文案 https://media.example/watch?signature=private-input',
      },
    });
    fireEvent.mouseDown(screen.getByRole('tab', { name: '剧本文档' }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.click(screen.getByText('切换测试页面'));
    fireEvent.click(screen.getByText('切换测试页面'));
    expect(screen.getByRole('tab', { name: '剧本文档' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    fireEvent.mouseDown(screen.getByRole('tab', { name: '链接下载' }), {
      button: 0,
      ctrlKey: false,
    });
    expect(screen.getByLabelText('公开视频地址')).toHaveValue(
      '分享文案 https://media.example/watch?signature=private-input',
    );
    expect(window.location.href).not.toContain('private-input');
    expect(
      JSON.stringify(vi.mocked(localStorage.setItem).mock.calls),
    ).not.toContain('private-input');
  });

  it('clears the previous identity draft before the new identity can render', () => {
    render(<Application />);
    fireEvent.change(screen.getByLabelText('公开视频地址'), {
      target: { value: '上一账号的私有草稿' },
    });
    act(() => advanceSessionGeneration());
    expect(screen.getByLabelText('公开视频地址')).toHaveValue('');
    fireEvent.click(screen.getByText('切换测试页面'));
    fireEvent.click(screen.getByText('切换测试页面'));
    expect(screen.getByLabelText('公开视频地址')).toHaveValue('');
  });

  it('does not share a draft between separate application roots', () => {
    const first = render(<Application />);
    fireEvent.change(screen.getByLabelText('公开视频地址'), {
      target: { value: '当前应用会话草稿' },
    });
    first.unmount();
    render(<Application />);
    expect(screen.getByLabelText('公开视频地址')).toHaveValue('');
  });
});
