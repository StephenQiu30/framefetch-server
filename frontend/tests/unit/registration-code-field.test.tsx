import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import {
  sendRegistrationCode as requestRegistrationCode,
  verifyRegistrationCode as requestVerifyRegistrationCode,
} from '@/api/auth';
import { RegistrationCodeField } from '@/components/auth/registration-code-field';
import { ApiError } from '@/lib/request-error';

function field(email = 'member@example.com') {
  return render(
    <RegistrationCodeField
      email={email}
      code=""
      onCodeChange={vi.fn()}
      onSendingChange={vi.fn()}
      onVerifiedChange={vi.fn()}
      disabled={false}
      verified={false}
    />,
  );
}

describe('registration email proof', () => {
  it('confirms SMTP acceptance and disables resend during the server cooldown', async () => {
    vi.mocked(requestRegistrationCode).mockResolvedValue({
      email_sent: true,
      retry_after_seconds: 60,
      expires_in_seconds: 600,
    });
    field();
    fireEvent.click(screen.getByRole('button', { name: '获取验证码' }));
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('验证码已发送'),
    );
    expect(requestRegistrationCode).toHaveBeenCalledWith({
      email: 'member@example.com',
    });
    expect(
      await screen.findByRole('button', { name: /秒后可重发/ }),
    ).toBeDisabled();
  });
  it('shows a send failure without claiming success', async () => {
    vi.mocked(requestRegistrationCode).mockRejectedValue(
      new ApiError(503, 'email_send_failed', 'Failed', 'Failed'),
    );
    field();
    fireEvent.click(screen.getByRole('button', { name: '获取验证码' }));
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('邮件发送未能确认'),
    );
    expect(screen.getByRole('button', { name: '获取验证码' })).toBeEnabled();
  });

  it.each([
    [180, '3 分钟'],
    [95, '95 秒'],
  ])('uses the server validity of %i seconds', async (expires, label) => {
    vi.mocked(requestRegistrationCode).mockResolvedValue({
      email_sent: true,
      retry_after_seconds: 35,
      expires_in_seconds: expires,
    });
    field();
    fireEvent.click(screen.getByRole('button', { name: '获取验证码' }));
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(`有效期 ${label}`),
    );
    expect(
      await screen.findByRole('button', { name: '35 秒后可重发' }),
    ).toBeDisabled();
  });

  it('does not invent expiry or cooldown when the server omits them', async () => {
    vi.mocked(requestRegistrationCode).mockResolvedValue({ email_sent: true });
    field();
    fireEvent.click(screen.getByRole('button', { name: '获取验证码' }));
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(
        '有效期请查看邮件说明',
      ),
    );
    expect(
      screen.getByRole('button', { name: '重新获取验证码' }),
    ).toBeEnabled();
  });
  it('checks the email before sending', async () => {
    vi.mocked(requestRegistrationCode).mockClear();
    field('bad-email');
    fireEvent.click(screen.getByRole('button', { name: '获取验证码' }));
    expect(screen.getByRole('button', { name: '获取验证码' })).toBeDisabled();
    expect(requestRegistrationCode).not.toHaveBeenCalled();
  });

  it('verifies the code before exposing the password step', async () => {
    vi.mocked(requestRegistrationCode).mockResolvedValue({
      email_sent: true,
      retry_after_seconds: 60,
      expires_in_seconds: 600,
    });
    vi.mocked(requestVerifyRegistrationCode).mockResolvedValue({
      verified: true,
    });
    const onCodeChange = vi.fn();
    const onVerifiedChange = vi.fn();
    render(
      <RegistrationCodeField
        email="member@example.com"
        code="123456"
        onCodeChange={onCodeChange}
        onSendingChange={vi.fn()}
        onVerifiedChange={onVerifiedChange}
        disabled={false}
        verified={false}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '获取验证码' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '验证邮箱' })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: '验证邮箱' }));
    await waitFor(() =>
      expect(requestVerifyRegistrationCode).toHaveBeenCalledWith({
        email: 'member@example.com',
        verification_code: '123456',
      }),
    );
    expect(onVerifiedChange).toHaveBeenCalledWith(true);
  });
});

vi.mock('@/api/auth', async (original) => ({
  ...(await original<typeof import('@/api/auth')>()),
  sendRegistrationCode: vi.fn(),
  verifyRegistrationCode: vi.fn(),
}));
