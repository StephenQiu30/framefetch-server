import { type NextRequest, NextResponse } from 'next/server';
import { backendOrigin } from '@/lib/backend-origin';

// 浏览器请求 /api 时转发到帧取 API，保持与 Web 相同的同源 Cookie 与来源校验。
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  let target: URL;
  try {
    target = backendOrigin();
  } catch {
    return NextResponse.json(
      { code: 'service_unavailable', message: 'API routing is unavailable.', data: null },
      { status: 503 },
    );
  }
  target.pathname = pathname.replace(/\/+$/, '');
  target.search = search;
  const headers = new Headers(request.headers);
  headers.set('x-forwarded-host', request.headers.get('host') ?? request.nextUrl.host);
  headers.set(
    'x-forwarded-proto',
    request.headers.get('x-forwarded-proto') === 'https' ? 'https' : request.nextUrl.protocol.slice(0, -1),
  );
  return NextResponse.rewrite(target, { request: { headers } });
}

export const config = { matcher: ['/api/:path*'] };
