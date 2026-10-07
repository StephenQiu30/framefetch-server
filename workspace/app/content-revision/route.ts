import { NextResponse } from 'next/server';
import { contentRevision } from '@/lib/workspace/content';

export const dynamic = 'force-dynamic';

export async function GET() {
  return NextResponse.json(
    { revision: await contentRevision() },
    { headers: { 'Cache-Control': 'no-store' } },
  );
}
