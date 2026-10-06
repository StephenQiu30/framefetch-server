'use client';

import {
  ArrowRightIcon,
  CheckIcon,
  WarningCircleIcon,
} from '@phosphor-icons/react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { type FormEvent, useEffect, useRef, useState } from 'react';
import { registerUser as register } from '@/api/auth';
import { AuthField, AuthPageFrame } from '@/components/auth/auth-page-frame';
import { useAuth } from '@/components/auth/auth-provider';
import { PasswordInput } from '@/components/auth/password-input';
import {
  type FieldErrors,
  validateRegistration,
} from '@/components/auth/register-form-model';
import { RegistrationCodeField } from '@/components/auth/registration-code-field';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { FieldGroup } from '@/components/ui/field';
import { Form } from '@/components/ui/form';
import { InputGroupInput } from '@/components/ui/input-group';
import { ItemDescription, ItemTitle } from '@/components/ui/item';
import { Spinner } from '@/components/ui/spinner';
import { authRedirect } from '@/lib/auth-redirect';
import { displayError } from '@/lib/request-error';
import { withWebSessionMutation } from '@/lib/session-events';
import { normalizeUsername, USERNAME_HELP } from '@/lib/username';

export function RegisterView() {
  const { user, loading, setUser } = useAuth();
  const [email, setEmail] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [emailVerified, setEmailVerified] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
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
    if (loading || submitting || sendingCode) return;
    if (!emailVerified) return;
    const data = new FormData(event.currentTarget);
    const values = {
      username: normalizeUsername(String(data.get('username') ?? '')),
      email: String(data.get('email') ?? '').trim(),
      password: String(data.get('password') ?? ''),
      confirmPassword: String(data.get('confirmPassword') ?? ''),
      verificationCode,
    };
    const nextErrors = validateRegistration(values);
    setErrors(nextErrors);
    setErrorMessage(undefined);
    if (Object.keys(nextErrors).length) return;

    setSubmitting(true);
    try {
      await withWebSessionMutation(async () => {
        const currentUser = await register({
          username: values.username,
          email: values.email,
          password: values.password,
          verification_code: values.verificationCode,
        });
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
      description="验证邮箱后创建账户，保存和管理你的下载、文档与分析。"
      title="创建帧取账户"
      titleId="register-title"
    >
      <ol aria-label="注册步骤" className="mb-7 flex items-center gap-6">
        <li
          aria-current={!emailVerified ? 'step' : undefined}
          className="flex items-center gap-2"
        >
          <Badge variant={!emailVerified ? 'default' : 'secondary'}>
            {emailVerified ? <CheckIcon aria-hidden /> : '1'}
          </Badge>
          <ItemTitle>验证邮箱</ItemTitle>
        </li>
        <li
          aria-current={emailVerified ? 'step' : undefined}
          className="flex items-center gap-2"
        >
          <Badge variant={emailVerified ? 'default' : 'secondary'}>2</Badge>
          <ItemTitle>设置密码</ItemTitle>
        </li>
      </ol>
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
            description={USERNAME_HELP}
            error={errors.username}
            idPrefix="register"
            label="用户名"
            name="username"
          >
            <InputGroupInput
              aria-describedby={
                errors.username
                  ? 'username-description username-error'
                  : 'username-description'
              }
              aria-invalid={Boolean(errors.username)}
              autoComplete="username"
              id="register-username"
              name="username"
              placeholder="2–32 个字符"
            />
          </AuthField>
          <AuthField
            error={errors.email}
            idPrefix="register"
            label="邮箱地址"
            name="email"
          >
            <InputGroupInput
              aria-describedby={errors.email ? 'email-error' : undefined}
              aria-invalid={Boolean(errors.email)}
              autoComplete="email"
              id="register-email"
              value={email}
              disabled={submitting || sendingCode}
              onChange={(event) => {
                setEmail(event.target.value);
                setVerificationCode('');
                setEmailVerified(false);
              }}
              name="email"
              placeholder="name@example.com"
              type="email"
            />
          </AuthField>
          <RegistrationCodeField
            key={email.trim().toLowerCase()}
            email={email}
            code={verificationCode}
            onCodeChange={setVerificationCode}
            onSendingChange={setSendingCode}
            onVerifiedChange={setEmailVerified}
            disabled={submitting}
            error={errors.verificationCode}
            verified={emailVerified}
          />
          {emailVerified ? (
            <>
              <ItemDescription className="line-clamp-none" role="status">
                邮箱已验证，现在设置密码完成注册。
              </ItemDescription>
              <FieldGroup className="gap-5">
                <AuthField
                  error={errors.password}
                  idPrefix="register"
                  label="密码"
                  name="password"
                >
                  <PasswordInput
                    aria-describedby={
                      errors.password ? 'password-error' : undefined
                    }
                    aria-invalid={Boolean(errors.password)}
                    autoComplete="new-password"
                    id="register-password"
                    minLength={8}
                    name="password"
                    placeholder="至少 8 个字符"
                    type="password"
                  />
                </AuthField>
                <AuthField
                  error={errors.confirmPassword}
                  idPrefix="register"
                  label="确认密码"
                  name="confirmPassword"
                >
                  <PasswordInput
                    aria-describedby={
                      errors.confirmPassword
                        ? 'confirmPassword-error'
                        : undefined
                    }
                    aria-invalid={Boolean(errors.confirmPassword)}
                    autoComplete="new-password"
                    id="register-confirmPassword"
                    name="confirmPassword"
                    placeholder="再次输入密码"
                    type="password"
                  />
                </AuthField>
              </FieldGroup>
            </>
          ) : null}
        </FieldGroup>
        {emailVerified ? (
          <Button
            className="w-full"
            disabled={loading || submitting || sendingCode}
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
            {submitting ? '正在创建…' : '注册并登录'}
            {!submitting ? (
              <ArrowRightIcon aria-hidden data-icon="inline-end" />
            ) : null}
          </Button>
        ) : null}
      </Form>
      <ItemDescription className="line-clamp-none mt-7">
        已有账户？{' '}
        <Button asChild variant="link">
          <Link href={`/user/login${search}`}>返回登录</Link>
        </Button>
      </ItemDescription>
    </AuthPageFrame>
  );
}
