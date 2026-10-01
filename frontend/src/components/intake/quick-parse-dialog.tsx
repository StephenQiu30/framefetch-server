'use client';

import {
  BookOpenIcon,
  ChartLineUpIcon,
  ClockCounterClockwiseIcon,
  FileTextIcon,
  FileVideoIcon,
  HardDrivesIcon,
  HouseIcon,
  InfoIcon,
  LinkSimpleIcon,
  ListBulletsIcon,
  MagnifyingGlassIcon,
  PulseIcon,
  RobotIcon,
  SignInIcon,
  StackIcon,
  UserCircleIcon,
  UserPlusIcon,
  UsersThreeIcon,
} from '@phosphor-icons/react';
import { usePathname, useRouter } from 'next/navigation';
import {
  type ClipboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useAuth } from '@/components/auth/auth-provider';
import type { IntakeMode } from '@/components/intake/content-intake-hero';
import { useIntakeDraft } from '@/components/intake/intake-draft-provider';
import {
  hasPublicInput,
  PUBLIC_INPUT_REQUIRED,
} from '@/components/intake/public-input';
import { markNavigationPush } from '@/components/layout/navigation-history';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from '@/components/ui/command';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { FieldError } from '@/components/ui/field';
import { Kbd } from '@/components/ui/kbd';

const publicDestinations = [
  { label: '首页', href: '/', keywords: '工作区', icon: HouseIcon },
  { label: '使用指南', href: '/guide/', keywords: '帮助', icon: BookOpenIcon },
  {
    label: '自托管部署',
    href: '/self-hosting/',
    keywords: '部署',
    icon: HardDrivesIcon,
  },
  { label: '关于', href: '/about/', keywords: 'FrameFetch', icon: InfoIcon },
] as const;

const accountDestinations = [
  {
    label: '下载记录',
    href: '/history',
    keywords: '历史 任务',
    icon: ClockCounterClockwiseIcon,
  },
  {
    label: '我的处理记录',
    href: '/history/activity',
    keywords: '解析历史 分析历史',
    icon: ListBulletsIcon,
  },
  {
    label: '剧本文档',
    href: '/documents',
    keywords: '文档',
    icon: FileTextIcon,
  },
  { label: '平台状态', href: '/providers', keywords: '来源', icon: PulseIcon },
  {
    label: '个人资料',
    href: '/account',
    keywords: '账户',
    icon: UserCircleIcon,
  },
] as const;

const adminDestinations = [
  {
    label: '系统操作日志',
    href: '/admin/operation-logs',
    keywords: '管理员 日志',
    icon: ListBulletsIcon,
  },
  {
    label: 'AI 服务',
    href: '/admin/ai-providers',
    keywords: '管理员 模型',
    icon: RobotIcon,
  },
  {
    label: '使用统计',
    href: '/admin/analytics',
    keywords: '管理员 统计',
    icon: ChartLineUpIcon,
  },
  {
    label: '文件管理',
    href: '/admin/files',
    keywords: '管理员 存储',
    icon: HardDrivesIcon,
  },
  {
    label: '平台目录',
    href: '/admin/providers',
    keywords: '管理员 平台',
    icon: StackIcon,
  },
  {
    label: '用户管理',
    href: '/admin/users',
    keywords: '管理员 用户',
    icon: UsersThreeIcon,
  },
] as const;

function matchesDestination(
  destination: { label: string; href: string; keywords: string },
  query: string,
) {
  return `${destination.label} ${destination.href} ${destination.keywords}`
    .toLocaleLowerCase()
    .includes(query);
}

export function QuickParseDialog() {
  const { user } = useAuth();
  const { input, requestQuickParse, setMode } = useIntakeDraft();
  const pathname = usePathname() ?? '/';
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const returnFocus = useRef<HTMLElement | null>(null);
  const [value, setValue] = useState('');
  const [invalid, setInvalid] = useState(false);
  const query = value.trim().toLocaleLowerCase();
  const isShareText = /https?:\/\//iu.test(value);
  const publicMatches = publicDestinations.filter((item) =>
    matchesDestination(item, query),
  );
  const accountMatches = user
    ? accountDestinations.filter((item) => matchesDestination(item, query))
    : [];
  const adminMatches =
    user?.role === 'admin'
      ? adminDestinations.filter((item) => matchesDestination(item, query))
      : [];
  const navigationMatches =
    publicMatches.length + accountMatches.length + adminMatches.length;
  const showNavigation = !isShareText;
  const showVideoUpload = Boolean(
    user && (!query || (!navigationMatches && '上传本地视频'.includes(query))),
  );
  const showScreenplayUpload = Boolean(
    user && (!query || (!navigationMatches && '上传剧本文档'.includes(query))),
  );
  const showParse = Boolean(
    user &&
      (!query ||
        isShareText ||
        (!navigationMatches && !showVideoUpload && !showScreenplayUpload)),
  );
  const showLogin = Boolean(
    !user && (!query || isShareText || '登录后使用'.includes(query)),
  );
  const showRegister = Boolean(!user && (!query || '注册账户'.includes(query)));

  const openDialog = useCallback(() => {
    returnFocus.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setValue(input);
    setInvalid(false);
    setOpen(true);
  }, [input]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        event.key.toLowerCase() !== 'k' ||
        (!event.metaKey && !event.ctrlKey) ||
        event.altKey ||
        event.shiftKey ||
        event.repeat ||
        event.isComposing
      )
        return;
      event.preventDefault();
      if (open) setOpen(false);
      else openDialog();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, openDialog]);

  function submit() {
    if (!hasPublicInput(value)) {
      setInvalid(true);
      return;
    }
    requestQuickParse(value);
    setOpen(false);
    if (pathname !== '/') {
      markNavigationPush('/');
      router.push('/');
    }
  }

  function selectUpload(mode: Extract<IntakeMode, 'video' | 'screenplay'>) {
    setMode(mode);
    setOpen(false);
    if (pathname !== '/') {
      markNavigationPush('/');
      router.push('/');
    }
  }

  function navigate(href: string) {
    setOpen(false);
    if (pathname !== href) {
      markNavigationPush(href);
      router.push(href);
    }
  }

  function selectSearchResult() {
    const destination = [
      ...publicMatches,
      ...accountMatches,
      ...adminMatches,
    ][0];
    if (destination) return navigate(destination.href);
    if (showVideoUpload) return selectUpload('video');
    if (showScreenplayUpload) return selectUpload('screenplay');
    if (showLogin) return navigate('/user/login?redirect=%2F');
    if (showRegister) return navigate('/user/register');
    if (showParse) submit();
  }

  function pasteShareText(event: ClipboardEvent<HTMLInputElement>) {
    const pasted = event.clipboardData.getData('text');
    if (!/[\r\n]/.test(pasted)) return;
    event.preventDefault();
    const target = event.currentTarget;
    const start = target.selectionStart ?? value.length;
    const end = target.selectionEnd ?? start;
    setValue(
      `${value.slice(0, start)}${pasted.replace(/\s+/g, ' ')}${value.slice(end)}`.slice(
        0,
        4096,
      ),
    );
    setInvalid(false);
  }

  return (
    <>
      <Button
        aria-haspopup="dialog"
        aria-keyshortcuts="Meta+K Control+K"
        aria-label="快捷操作"
        onClick={openDialog}
        variant="ghost"
      >
        <MagnifyingGlassIcon aria-hidden data-icon="inline-start" />
        快捷操作
        <Kbd className="hidden sm:inline-flex">⌘ / Ctrl K</Kbd>
      </Button>
      <Dialog onOpenChange={setOpen} open={open}>
        <DialogContent
          className="max-h-svh overflow-y-auto overscroll-contain sm:max-w-2xl"
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            if (returnFocus.current?.isConnected)
              returnFocus.current.focus({ preventScroll: true });
          }}
        >
          <DialogHeader>
            <DialogTitle>快捷操作</DialogTitle>
            <DialogDescription>
              {user
                ? '搜索页面、解析公开链接，或上传本地视频与剧本文档。'
                : '搜索页面；登录后可解析链接、上传视频与剧本文档。'}
            </DialogDescription>
          </DialogHeader>
          <Command label="链接或页面" shouldFilter={false}>
            <CommandInput
              aria-describedby={invalid ? 'quick-parse-error' : undefined}
              aria-invalid={invalid ? true : undefined}
              aria-label="链接或页面"
              maxLength={4096}
              onKeyDown={(event) => {
                if (
                  event.key !== 'Enter' ||
                  event.nativeEvent.isComposing ||
                  !query ||
                  isShareText
                )
                  return;
                event.preventDefault();
                event.stopPropagation();
                selectSearchResult();
              }}
              onPaste={pasteShareText}
              onValueChange={(nextValue) => {
                setValue(nextValue);
                setInvalid(false);
              }}
              placeholder="搜索页面，或粘贴媒体链接…"
              value={value}
            />
            <CommandList>
              {user &&
              (showParse || showVideoUpload || showScreenplayUpload) ? (
                <CommandGroup heading="选择操作">
                  {showParse ? (
                    <CommandItem onSelect={submit} value="解析链接">
                      <LinkSimpleIcon aria-hidden />
                      解析链接
                      <CommandShortcut>↵</CommandShortcut>
                    </CommandItem>
                  ) : null}
                  {showVideoUpload ? (
                    <CommandItem
                      onSelect={() => selectUpload('video')}
                      value="上传本地视频"
                    >
                      <FileVideoIcon aria-hidden />
                      上传本地视频
                    </CommandItem>
                  ) : null}
                  {showScreenplayUpload ? (
                    <CommandItem
                      onSelect={() => selectUpload('screenplay')}
                      value="上传剧本文档"
                    >
                      <FileTextIcon aria-hidden />
                      上传剧本文档
                    </CommandItem>
                  ) : null}
                </CommandGroup>
              ) : null}
              {showLogin || showRegister ? (
                <CommandGroup heading="开始使用">
                  {showLogin ? (
                    <CommandItem
                      onSelect={() => navigate('/user/login?redirect=%2F')}
                      value="登录后使用"
                    >
                      <SignInIcon aria-hidden />
                      登录后使用
                    </CommandItem>
                  ) : null}
                  {showRegister ? (
                    <CommandItem
                      onSelect={() => navigate('/user/register')}
                      value="注册账户"
                    >
                      <UserPlusIcon aria-hidden />
                      注册账户
                    </CommandItem>
                  ) : null}
                </CommandGroup>
              ) : null}
              {showNavigation && publicMatches.length ? (
                <CommandGroup heading="页面">
                  {publicMatches.map(({ label, href, icon: Icon }) => (
                    <CommandItem
                      key={href}
                      onSelect={() => navigate(href)}
                      value={label}
                    >
                      <Icon aria-hidden />
                      {label}
                    </CommandItem>
                  ))}
                </CommandGroup>
              ) : null}
              {showNavigation && accountMatches.length ? (
                <CommandGroup heading="工作区">
                  {accountMatches.map(({ label, href, icon: Icon }) => (
                    <CommandItem
                      key={href}
                      onSelect={() => navigate(href)}
                      value={label}
                    >
                      <Icon aria-hidden />
                      {label}
                    </CommandItem>
                  ))}
                </CommandGroup>
              ) : null}
              {showNavigation && adminMatches.length ? (
                <CommandGroup heading="管理">
                  {adminMatches.map(({ label, href, icon: Icon }) => (
                    <CommandItem
                      key={href}
                      onSelect={() => navigate(href)}
                      value={label}
                    >
                      <Icon aria-hidden />
                      {label}
                    </CommandItem>
                  ))}
                </CommandGroup>
              ) : null}
              {!user &&
              query &&
              !navigationMatches &&
              !showLogin &&
              !showRegister ? (
                <p className="px-2 py-6 text-center text-sm text-muted-foreground">
                  没有匹配的页面
                </p>
              ) : null}
            </CommandList>
            {invalid ? (
              <FieldError id="quick-parse-error">
                {PUBLIC_INPUT_REQUIRED}
              </FieldError>
            ) : null}
          </Command>
        </DialogContent>
      </Dialog>
    </>
  );
}
