'use client';

import { ArrowRightIcon, WarningCircleIcon } from '@phosphor-icons/react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { type FormEvent, useEffect, useRef, useState } from 'react';
import { loginUser as login } from '@/api/auth';
import { AuthField, AuthPageFrame } from '@/components/auth/auth-page-frame';
import { useAuth } from '@/components/auth/auth-provider';
import { PasswordInput } from '@/components/auth/password-input';
import { isValidEmail } from '@/components/auth/register-form-model';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { FieldGroup } from '@/components/ui/field';
import { Form } from '@/components/ui/form';
import { InputGroupInput } from '@/components/ui/input-group';
import { ItemDescription } from '@/components/ui/item';
import { Spinner } from '@/components/ui/spinner';
import { authRedirect } from '@/lib/auth-redirect';
import { displayError } from '@/lib/request-error';
import { withWebSessionMutation } from '@/lib/session-events';

type FieldErrors = Partial<Record<'email' | 'password', string>>;

export function LoginView() {
  const { user, loading, setUser } = useAuth();
  const [redirect, setRedirect] = useState('/');
  const [search, setSearch] = useState('');
  const [errors, setErrors] = useState<FieldErrors>({});
  const [errorMessage, setErrorMessage] = useState<string>();
  const [submitting, setSubmitting] = useState(false);
  const errorRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    const currentSearch = window.location.search;
    const destination = authRedirect(currentSearch);
    setRedirect(destination);
    setSearch(currentSearch);
    if (!loading && user) router.replace(destination);
  }, [loading, router, user]);

  useEffect(() => {
    if (errorMessage) errorRef.current?.focus();
  }, [errorMessage]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loading || submitting) return;
    const data = new FormData(event.currentTarget);
    const email = String(data.get('email') ?? '').trim();
    const password = String(data.get('password') ?? '');
    const nextErrors = validateLogin(email, password);
    setErrors(nextErrors);
    setErrorMessage(undefined);
    if (Object.keys(nextErrors).length) return;

    setSubmitting(true);
    try {
      await withWebSessionMutation(async () => {
        const currentUser = await login({ email, password });
        setUser(currentUser);
      });
      router.replace(redirect);
    } catch (error) {
      setErrorMessage(displayError(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthPageFrame
      description="使用你的帧取账户继续管理下载、文档与分析。"
      title="登录帧取"
      titleId="login-title"
    >
      <Form
        aria-busy={submitting}
        className="flex flex-col gap-7"
        noValidate
        onSubmit={handleSubmit}
      >
        {errorMessage ? (
          <Alert ref={errorRef} tabIndex={-1} variant="destructive">
            <WarningCircleIcon aria-hidden />
            <AlertDescription>{errorMessage}</AlertDescription>
          </Alert>
        ) : null}
        <FieldGroup className="gap-5">
          <AuthField
            error={errors.email}
            idPrefix="login"
            label="邮箱地址"
            name="email"
          >
            <InputGroupInput
              aria-describedby={errors.email ? 'email-error' : undefined}
              aria-invalid={Boolean(errors.email)}
              autoComplete="email"
              id="login-email"
              name="email"
              placeholder="name@example.com"
              type="email"
            />
          </AuthField>
          <AuthField
            error={errors.password}
            idPrefix="login"
            label="密码"
            name="password"
          >
            <PasswordInput
              aria-describedby={errors.password ? 'password-error' : undefined}
              aria-invalid={Boolean(errors.password)}
              autoComplete="current-password"
              id="login-password"
              minLength={8}
              name="password"
              placeholder="至少 8 个字符"
              type="password"
            />
          </AuthField>
        </FieldGroup>
        <Button
          className="w-full"
          disabled={loading || submitting}
          type="submit"
        >
          {submitting ? (
            <Spinner
              aria-hidden
              className="motion-reduce:animate-none"
              data-icon="inline-start"
              role="presentation"
            />
          ) : null}
          {submitting ? '正在登录…' : '登录'}
          {!submitting ? (
            <ArrowRightIcon aria-hidden data-icon="inline-end" />
          ) : null}
        </Button>
      </Form>
      <ItemDescription className="line-clamp-none mt-7">
        还没有账户？{' '}
        <Button asChild variant="link">
          <Link href={`/user/register${search}`}>创建账户</Link>
        </Button>
      </ItemDescription>
    </AuthPageFrame>
  );
}

function validateLogin(email: string, password: string): FieldErrors {
  const errors: FieldErrors = {};
  if (!email) errors.email = '请输入邮箱地址';
  else if (!isValidEmail(email)) errors.email = '请输入有效的邮箱地址';
  if (!password) errors.password = '请输入密码';
  else if (Array.from(password).length < 8)
    errors.password = '密码至少需要 8 个字符';
  else if (Array.from(password).length > 128)
    errors.password = '密码不能超过 128 个字符';
  return errors;
}
