'use client';

import { useMDXComponents } from 'nextra-theme-docs';
import { useEffect, useState } from 'react';
import { getCurrentUser } from '@/api/auth';

const Anchor = useMDXComponents().a;

/** 只有管理员看到编辑入口；会话由帧取 Web 登录建立，同一主机名下共享。 */
export function EditLink({ path }: { path: string }) {
  const [admin, setAdmin] = useState(false);
  useEffect(() => {
    let active = true;
    getCurrentUser({ skipErrorHandler: true })
      .then((user) => active && setAdmin(user.role === 'admin'))
      .catch(() => active && setAdmin(false));
    return () => {
      active = false;
    };
  }, []);
  if (!admin) return null;
  return (
    <div className="x:mb-4 x:flex x:justify-end">
      <Anchor href={`/edit?path=${encodeURIComponent(path)}`}>编辑此页</Anchor>
    </div>
  );
}
