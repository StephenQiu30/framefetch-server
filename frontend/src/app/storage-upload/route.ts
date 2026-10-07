import { request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import { Readable } from 'node:stream';
import type { ReadableStream as NodeReadableStream } from 'node:stream/web';
import type { NextRequest } from 'next/server';

import { internalStorageTarget, resolveTarget } from './target';

const TARGET_HEADER = 'X-Framefetch-Upload-Target';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function PUT(request: NextRequest) {
  const target = resolveTarget(request.headers.get(TARGET_HEADER));
  if (!target) {
    return new Response('Invalid upload target', { status: 400 });
  }
  const upstreamTarget = internalStorageTarget(target);

  const headers = new Headers();
  const contentType = request.headers.get('content-type');
  const contentLength = request.headers.get('content-length');
  if (contentType) headers.set('content-type', contentType);
  if (contentLength) headers.set('content-length', contentLength);
  if (upstreamTarget.origin !== target.origin) headers.set('host', target.host);

  try {
    const upstream =
      upstreamTarget.origin === target.origin
        ? await uploadWithFetch(request, upstreamTarget, headers)
        : await uploadWithNodeRequest(request, upstreamTarget, headers);
    const responseHeaders = new Headers({ 'Cache-Control': 'no-store' });
    const etag = upstream.etag;
    if (etag) responseHeaders.set('ETag', etag);
    return new Response(null, {
      headers: responseHeaders,
      status: upstream.status,
    });
  } catch {
    return new Response('Upload storage unavailable', { status: 502 });
  }
}

async function uploadWithFetch(
  request: NextRequest,
  target: URL,
  headers: Headers,
): Promise<{ etag: string | null; status: number }> {
  const response = await fetch(target, {
    body: request.body,
    cache: 'no-store',
    duplex: 'half',
    headers,
    method: 'PUT',
    redirect: 'error',
    signal: request.signal,
  } as RequestInit & { duplex: 'half' });
  return { etag: response.headers.get('etag'), status: response.status };
}

function uploadWithNodeRequest(
  request: NextRequest,
  target: URL,
  headers: Headers,
): Promise<{ etag: string | null; status: number }> {
  return new Promise((resolve, reject) => {
    const send = target.protocol === 'https:' ? httpsRequest : httpRequest;
    const upstream = send(
      {
        headers: Object.fromEntries(headers),
        hostname: target.hostname,
        method: 'PUT',
        path: `${target.pathname}${target.search}`,
        port: target.port,
        protocol: target.protocol,
      },
      (response) => {
        response.resume();
        response.once('end', () => {
          const etag = response.headers.etag;
          resolve({
            etag: Array.isArray(etag) ? (etag[0] ?? null) : (etag ?? null),
            status: response.statusCode ?? 502,
          });
        });
      },
    );
    const abort = () => upstream.destroy(new Error('upload aborted'));
    request.signal.addEventListener('abort', abort, { once: true });
    upstream.once('close', () =>
      request.signal.removeEventListener('abort', abort),
    );
    upstream.once('error', reject);
    if (request.body) {
      const body = Readable.fromWeb(
        request.body as unknown as NodeReadableStream,
      );
      body.once('error', reject);
      body.pipe(upstream);
    } else upstream.end();
  });
}
