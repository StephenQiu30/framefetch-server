import { type NextRequest, NextResponse } from 'next/server';
import { searchContent } from '@/lib/workspace/content';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const query = request.nextUrl.searchParams.get('q') ?? '';
  if (query.length > 200)
    return NextResponse.json({ error: 'invalid_query' }, { status: 400 });
  return NextResponse.json(await searchContent(query), {
    headers: { 'Cache-Control': 'no-store' },
  });
}
