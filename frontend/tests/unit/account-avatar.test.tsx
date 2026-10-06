import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AccountView } from '@/components/account/account-view';
import { avatarUrl } from '@/lib/avatar';
import { render } from '../helpers/query-render';

const runtime = vi.hoisted(() => ({
  deleteAvatar: vi.fn(),
  setUser: vi.fn(),
  updateUser: vi.fn(),
  uploadAvatar: vi.fn(),
  user: {
    id: 'owner',
    username: 'Stephen',
    email: 'owner@example.com',
    role: 'admin' as const,
    created_at: '2026-09-26T00:00:00Z',
    updated_at: '2026-09-26T00:00:00Z',
    avatar_version: null as string | null,
  },
}));

vi.mock('@/api/users', () => ({
  deleteCurrentUserAvatar: runtime.deleteAvatar,
  updateCurrentUser: runtime.updateUser,
  uploadCurrentUserAvatar: runtime.uploadAvatar,
}));

vi.mock('@/components/auth/auth-provider', async (importOriginal) => ({
  ...(await importOriginal()),
  useAuth: () => ({
    user: runtime.user,
    loading: false,
    setUser: runtime.setUser,
    refreshUser: vi.fn(),
  }),
}));

describe('account avatar', () => {
  beforeEach(() => {
    runtime.user.avatar_version = null;
    runtime.deleteAvatar.mockReset();
    runtime.setUser.mockReset();
    runtime.updateUser.mockReset();
    runtime.uploadAvatar.mockReset();
  });

  it('shows upload entry and validates file type and size inline', () => {
    render(<AccountView />);
    const initials = screen.getByText('ST');
    expect(initials).toHaveClass('text-foreground');
    expect(initials).not.toHaveClass('text-muted-foreground');
    expect(screen.getByRole('button', { name: '上传头像' })).toBeVisible();
    const input = screen.getByLabelText('选择头像图片');
    const openPicker = vi.spyOn(input as HTMLInputElement, 'click');
    fireEvent.click(screen.getByRole('button', { name: '上传头像' }));
    expect(openPicker).toHaveBeenCalledOnce();
    expect(input).toHaveAttribute('type', 'file');
    expect(input).toHaveAttribute('aria-describedby', 'avatar-help');
    fireEvent.change(input, {
      target: {
        files: [new File(['x'], 'bad.svg', { type: 'image/svg+xml' })],
      },
    });
    expect(screen.getByRole('alert')).toHaveTextContent(
      '请选择 JPEG、PNG 或 WebP 图片',
    );
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAttribute(
      'aria-describedby',
      'avatar-help avatar-error',
    );
    fireEvent.change(input, {
      target: {
        files: [
          new File([new Uint8Array(4 * 1024 * 1024 + 1)], 'big.png', {
            type: 'image/png',
          }),
        ],
      },
    });
    expect(screen.getByRole('alert')).toHaveTextContent('不能超过 4 MB');
    expect(runtime.uploadAvatar).not.toHaveBeenCalled();
  });

  it('uploads the selected image and updates the shared identity', async () => {
    const updated = { ...runtime.user, avatar_version: 'revision-1' };
    runtime.uploadAvatar.mockResolvedValue(updated);
    render(<AccountView />);
    const file = new File(['image bytes'], 'avatar.png', { type: 'image/png' });
    fireEvent.change(screen.getByLabelText('选择头像图片'), {
      target: { files: [file] },
    });
    await waitFor(() =>
      expect(runtime.uploadAvatar).toHaveBeenCalledWith(file),
    );
    expect(runtime.setUser).toHaveBeenCalledWith(updated);
    expect(avatarUrl(updated)).toBe('/api/users/me/avatar?version=revision-1');
  });

  it('removes the avatar and restores the initials fallback', async () => {
    runtime.user.avatar_version = 'revision-1';
    runtime.deleteAvatar.mockResolvedValue({
      ...runtime.user,
      avatar_version: null,
    });
    render(<AccountView />);
    fireEvent.click(screen.getByRole('button', { name: '移除头像' }));
    await waitFor(() => expect(runtime.deleteAvatar).toHaveBeenCalledOnce());
    expect(runtime.setUser).toHaveBeenCalledWith(
      expect.objectContaining({ avatar_version: null }),
    );
    expect(avatarUrl({ avatar_version: null })).toBeUndefined();
  });
});
