'use client';

import { useEffect, useRef, useState } from 'react';
import {
  sendRegistrationCode as requestRegistrationCode,
  verifyRegistrationCode as requestVerifyRegistrationCode,
} from '@/api/auth';
import { AuthField } from '@/components/auth/auth-page-frame';
import { isValidEmail } from '@/components/auth/register-form-model';
import { Button } from '@/components/ui/button';
import { InputGroupInput } from '@/components/ui/input-group';
import { ItemDescription } from '@/components/ui/item';
import { Spinner } from '@/components/ui/spinner';
import { displayError } from '@/lib/request-error';

export function RegistrationCodeField({
  email,
  code,
  onCodeChange,
  onSendingChange,
  onVerifiedChange,
  disabled,
  error,
  verified,
}: {
  email: string;
  code: string;
  onCodeChange: (code: string) => void;
  onSendingChange: (sending: boolean) => void;
  onVerifiedChange: (verified: boolean) => void;
  disabled: boolean;
  error?: string;
  verified: boolean;
}) {
  const [sending, setSending] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [sent, setSent] = useState(false);
  const [until, setUntil] = useState(0);
  const [remaining, setRemaining] = useState(0);
  const [message, setMessage] = useState('');
  const busy = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    const tick = () =>
      setRemaining(Math.max(0, Math.ceil((until - Date.now()) / 1000)));
    tick();
    if (!until) return;
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [until]);

  async function send() {
    if (busy.current || until > Date.now()) return;
    if (!isValidEmail(email.trim())) {
      setMessage('请先输入有效的邮箱地址。');
      return;
    }
    busy.current = true;
    setSending(true);
    onSendingChange(true);
    setMessage('');
    try {
      const result = await requestRegistrationCode({ email: email.trim() });
      if (!mounted.current) return;
      if (!result.email_sent) {
        setMessage('邮件发送未能确认，请稍后重新获取验证码。');
        return;
      }
      onCodeChange('');
      onVerifiedChange(false);
      setSent(true);
      setUntil(
        Date.now() + Math.max(0, result.retry_after_seconds ?? 0) * 1000,
      );
      const seconds = result.expires_in_seconds;
      const expiry =
        seconds && seconds > 0
          ? `有效期 ${new Intl.NumberFormat('zh-CN').format(seconds % 60 === 0 ? seconds / 60 : seconds)} ${seconds % 60 === 0 ? '分钟' : '秒'}。`
          : '有效期请查看邮件说明。';
      setMessage(`验证码已发送，${expiry}未收到时请检查垃圾邮件。`);
    } catch (failure) {
      if (mounted.current) setMessage(displayError(failure));
    } finally {
      busy.current = false;
      if (mounted.current) {
        setSending(false);
        onSendingChange(false);
      }
    }
  }

  async function verify() {
    if (
      verifying ||
      disabled ||
      verified ||
      !sent ||
      !isValidEmail(email.trim()) ||
      !/^[0-9]{6}$/.test(code)
    ) {
      return;
    }
    setVerifying(true);
    setMessage('');
    try {
      await requestVerifyRegistrationCode({
        email: email.trim(),
        verification_code: code,
      });
      if (!mounted.current) return;
      onVerifiedChange(true);
      setMessage('邮箱已验证，可以设置密码。');
    } catch (failure) {
      if (mounted.current) setMessage(displayError(failure));
    } finally {
      if (mounted.current) setVerifying(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <AuthField
        idPrefix="register"
        name="verificationCode"
        label="邮箱验证码"
        error={error}
      >
        <InputGroupInput
          id="register-verificationCode"
          name="verificationCode"
          value={code}
          onChange={(event) =>
            onCodeChange(event.target.value.replace(/[^0-9]/g, '').slice(0, 6))
          }
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? 'verificationCode-error' : undefined}
          disabled={disabled || verified}
          placeholder="6 位验证码"
        />
      </AuthField>
      <div className="flex flex-wrap gap-3">
        <Button
          type="button"
          disabled={
            disabled ||
            verifying ||
            verified ||
            !sent ||
            !/^[0-9]{6}$/.test(code)
          }
          onClick={() => void verify()}
        >
          {verifying ? <Spinner aria-hidden data-icon="inline-start" /> : null}
          {verified ? '邮箱已验证' : verifying ? '验证中…' : '验证邮箱'}
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={
            disabled ||
            sending ||
            verified ||
            remaining > 0 ||
            !isValidEmail(email.trim())
          }
          onClick={() => void send()}
        >
          {sending ? <Spinner aria-hidden data-icon="inline-start" /> : null}
          {sending
            ? '正在发送…'
            : remaining > 0
              ? `${remaining} 秒后可重发`
              : sent
                ? '重新获取验证码'
                : '获取验证码'}
        </Button>
      </div>
      <ItemDescription role="status" className="line-clamp-none">
        {message}
      </ItemDescription>
    </div>
  );
}
