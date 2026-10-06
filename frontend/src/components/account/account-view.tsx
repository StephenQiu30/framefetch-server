'use client';

import { FloppyDisk, UploadSimpleIcon, XIcon } from '@phosphor-icons/react';
import {
  type ChangeEvent,
  type FormEvent,
  useEffect,
  useRef,
  useState,
} from 'react';
import { toast } from 'sonner';
import { updateUserAccess } from '@/api/admin';
import {
  deleteCurrentUserAvatar,
  updateCurrentUser,
  uploadCurrentUserAvatar,
} from '@/api/users';
import { ReadOnlyField } from '@/components/account/read-only-field';
import { useAuth } from '@/components/auth/auth-provider';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import { SplitLayout } from '@/components/layout/split-layout';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from '@/components/ui/field';
import { Form } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { ItemDescription, ItemTitle } from '@/components/ui/item';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';
import { avatarUrl } from '@/lib/avatar';
import { displayError } from '@/lib/request-error';
import {
  normalizeUsername,
  USERNAME_HELP,
  usernameLength,
  validateUsername,
} from '@/lib/username';

type Notice = { text: string } | null;
const MAX_AVATAR_UPLOAD_BYTES = 4 * 1024 * 1024;
const AVATAR_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);
const formClassName = 'mt-8';
const summaryClassName = 'flex min-w-0 flex-col gap-4 self-start';
const identityClassName = 'flex flex-col items-start gap-3';

export function AccountView() {
  const { user, loading, setUser, refreshUser } = useAuth();
  const [username, setUsername] = useState(user?.username ?? '');
  const [selectedRole, setSelectedRole] = useState<API.UserRole>(
    user?.role ?? 'user',
  );
  const avatarInput = useRef<HTMLInputElement>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [avatarError, setAvatarError] = useState<string | null>(null);

  useEffect(() => setUsername(user?.username ?? ''), [user?.username]);
  useEffect(() => setSelectedRole(user?.role ?? 'user'), [user?.role]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!user) return;
    const value = normalizeUsername(username);
    const validationError = validateUsername(value);
    if (validationError) {
      setNotice({
        text:
          validationError === 'unsupported_characters'
            ? '用户名仅支持字母、数字、中文以及 _-. 字符。'
            : '用户名长度需要在 2–32 个字符之间。',
      });
      return;
    }
    setSaving(true);
    setNotice(null);
    let usernameSaved = false;
    try {
      let updated = user;
      if (value !== user.username) {
        updated = await updateCurrentUser({ username: value });
        setUser(updated);
        setUsername(updated.username);
        usernameSaved = true;
      }
      if (user.role === 'admin' && selectedRole !== updated.role) {
        const access = await updateUserAccess(
          { user_id: user.id },
          { role: selectedRole },
        );
        updated = {
          ...updated,
          role: access.role,
          updated_at: access.updated_at,
        };
        setUser(updated);
      }
      toast.success('个人资料已更新。');
    } catch (error) {
      setNotice({
        text: usernameSaved
          ? `用户名已保存；账户身份修改失败：${displayError(error)}`
          : displayError(error),
      });
    } finally {
      setSaving(false);
    }
  }

  async function uploadAvatar(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!AVATAR_TYPES.has(file.type)) {
      setAvatarError('请选择 JPEG、PNG 或 WebP 图片。');
      return;
    }
    if (file.size === 0 || file.size > MAX_AVATAR_UPLOAD_BYTES) {
      setAvatarError('头像文件不能超过 4 MB。');
      return;
    }
    setAvatarError(null);
    setAvatarBusy(true);
    try {
      const updated = await uploadCurrentUserAvatar(file);
      setUser(updated);
      toast.success('头像已更新。');
    } catch (error) {
      toast.error(displayError(error));
    } finally {
      setAvatarBusy(false);
    }
  }

  async function deleteAvatar() {
    setAvatarError(null);
    setAvatarBusy(true);
    try {
      const updated = await deleteCurrentUserAvatar();
      setUser(updated);
      toast.success('头像已移除。');
    } catch (error) {
      toast.error(displayError(error));
    } finally {
      setAvatarBusy(false);
    }
  }

  if (loading) {
    return (
      <>
        <PageNavigation fallbackHref="/" />
        <PageHeader
          description="管理用户名与头像；管理员还可调整账户身份。"
          title="个人资料"
        />
        <SplitLayout
          aria-label="正在加载个人资料"
          className={formClassName}
          columns="sidebar-start"
          role="status"
        >
          <div aria-hidden className={summaryClassName}>
            <div className={identityClassName}>
              <Skeleton className="size-10 rounded-full" />
              <Skeleton className="h-6 w-24" />
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-5 w-16" />
            </div>
            <div className="flex flex-col items-center gap-2">
              <Skeleton className="h-8 w-28" />
              <Skeleton className="h-10 w-full" />
            </div>
          </div>
          <div aria-hidden className="flex min-w-0 flex-col gap-6">
            <Skeleton className="h-5 w-16" />
            <div className="flex flex-col gap-6">
              {['username', 'email', 'role'].map((key) => (
                <div className="flex flex-col gap-2" key={key}>
                  <Skeleton className="h-5 w-20" />
                  <Skeleton className="h-8 w-full" />
                  <Skeleton className="h-5 w-4/5" />
                </div>
              ))}
            </div>
            <Skeleton className="mt-3 h-8 w-24" />
          </div>
        </SplitLayout>
      </>
    );
  }

  if (!user) {
    return (
      <PageErrorNotice
        message="登录状态已失效，请重新检查账户状态。"
        onRetry={() => void refreshUser()}
        retryLabel="重新检查"
        title="暂时无法读取个人资料"
      />
    );
  }

  const unchanged =
    normalizeUsername(username) === user.username && selectedRole === user.role;
  const role = user.role === 'admin' ? '管理员' : '普通用户';
  const initials = user.username.trim().slice(0, 2).toUpperCase();

  return (
    <>
      <PageNavigation fallbackHref="/" />
      <PageHeader
        description="管理用户名与头像；管理员还可调整账户身份。"
        title="个人资料"
      />

      <Form className={formClassName} onSubmit={submit}>
        <SplitLayout columns="sidebar-start">
          <section aria-label="头像与账户概览" className={summaryClassName}>
            <div className={identityClassName}>
              <Avatar aria-hidden size="lg">
                <AvatarImage alt="" src={avatarUrl(user)} />
                <AvatarFallback>{initials}</AvatarFallback>
              </Avatar>
              <ItemTitle className="line-clamp-none">
                <h2 className="[overflow-wrap:anywhere]">{user.username}</h2>
              </ItemTitle>
              <ItemDescription className="line-clamp-none [overflow-wrap:anywhere]">
                {user.email}
              </ItemDescription>
              <Badge variant="secondary">{role}</Badge>
            </div>
            <div>
              <Input
                accept="image/jpeg,image/png,image/webp"
                aria-describedby={
                  avatarError ? 'avatar-help avatar-error' : 'avatar-help'
                }
                aria-invalid={avatarError ? true : undefined}
                aria-label="选择头像图片"
                aria-hidden="true"
                className="hidden"
                disabled={avatarBusy}
                id="avatar-image"
                onChange={uploadAvatar}
                ref={avatarInput}
                tabIndex={-1}
                type="file"
              />
              <Field
                className="items-start"
                data-invalid={avatarError ? true : undefined}
              >
                <FieldGroup className="flex-row flex-wrap gap-2">
                  <Button
                    aria-describedby={
                      avatarError ? 'avatar-help avatar-error' : 'avatar-help'
                    }
                    disabled={avatarBusy}
                    onClick={() => avatarInput.current?.click()}
                    type="button"
                    variant="outline"
                  >
                    {avatarBusy ? (
                      <Spinner aria-hidden data-icon="inline-start" />
                    ) : (
                      <UploadSimpleIcon aria-hidden data-icon="inline-start" />
                    )}
                    {avatarBusy ? '正在处理头像' : '上传头像'}
                  </Button>
                  {user.avatar_version ? (
                    <Button
                      disabled={avatarBusy}
                      onClick={() => void deleteAvatar()}
                      type="button"
                      variant="ghost"
                    >
                      <XIcon aria-hidden data-icon="inline-start" />
                      移除头像
                    </Button>
                  ) : null}
                </FieldGroup>
                <FieldDescription aria-live="polite" id="avatar-help">
                  JPEG、PNG 或 WebP，最大 4 MB。上传后自动裁切为方形。
                </FieldDescription>
                {avatarError ? (
                  <FieldError id="avatar-error">{avatarError}</FieldError>
                ) : null}
              </Field>
            </div>
          </section>

          <FieldSet className="min-w-0 gap-6">
            <FieldLegend variant="label">资料字段</FieldLegend>
            <FieldGroup className="gap-6">
              <Field>
                <FieldLabel
                  className="w-full justify-between"
                  htmlFor="username"
                >
                  用户名
                  <span aria-hidden="true" className="tabular-nums">
                    {usernameLength(username)}/32
                  </span>
                </FieldLabel>
                <Input
                  aria-describedby="username-help"
                  id="username"
                  onChange={(event) => {
                    setUsername(event.target.value);
                    setNotice(null);
                  }}
                  required
                  value={username}
                />
                <FieldDescription id="username-help">
                  {USERNAME_HELP} 将显示在导航和任务记录中。
                </FieldDescription>
              </Field>
              <ReadOnlyField
                description="用于登录账户，暂不支持在此修改。"
                id="email"
                label="登录邮箱"
                value={user.email}
              />
              <Field data-disabled={user.role !== 'admin' ? true : undefined}>
                <FieldLabel htmlFor="role">账户身份</FieldLabel>
                <Select
                  disabled={user.role !== 'admin' || saving}
                  onValueChange={(value) => {
                    setSelectedRole(value as API.UserRole);
                    setNotice(null);
                  }}
                  value={selectedRole}
                >
                  <SelectTrigger
                    aria-describedby="role-help"
                    className="w-full"
                    id="role"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value="admin">管理员</SelectItem>
                      <SelectItem value="user">普通用户</SelectItem>
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <FieldDescription id="role-help">
                  {user.role === 'admin'
                    ? '更改为普通用户前，必须保留另一位启用的管理员。'
                    : '仅管理员可以修改账户身份。'}
                </FieldDescription>
              </Field>
            </FieldGroup>
            {notice ? (
              <FeedbackNotice
                presentation="toast"
                description={notice.text}
                title="资料保存失败"
                tone="error"
              />
            ) : null}
            <Button
              className="mt-3 self-start"
              disabled={saving || unchanged}
              type="submit"
            >
              {saving ? (
                <Spinner
                  aria-hidden
                  data-icon="inline-start"
                  role="presentation"
                />
              ) : (
                <FloppyDisk aria-hidden data-icon="inline-start" />
              )}
              {saving ? '正在保存' : '保存资料'}
            </Button>
          </FieldSet>
        </SplitLayout>
      </Form>
    </>
  );
}
