import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { Marked } from 'marked';
import { describe, expect, it } from 'vitest';
import { markdownToEditorDocument, sanitizeEditorDocument } from '@/components/editor/document';
import { linksForEditing, linksForSaving } from '@/lib/workspace/links';
import { editorDocumentToMarkdown } from '@/lib/workspace/markdown';

const ORIGIN = 'http://127.0.0.1:8130';
const CONTENT = join(__dirname, '../content');

function markdownFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    if (name.startsWith('.')) return [];
    const path = join(directory, name);
    if (statSync(path).isDirectory()) return markdownFiles(path);
    return name.endsWith('.md') ? [relative(CONTENT, path).split('\\').join('/')] : [];
  });
}

const documents = markdownFiles(CONTENT);
const render = (markdown: string) =>
  new Marked({ gfm: true }).parse(markdown, { async: false }).replace(/\s+/g, ' ').trim();

function roundTrip(markdown: string, path: string): string {
  const editable = linksForEditing(markdown, path, ORIGIN);
  const document = sanitizeEditorDocument(markdownToEditorDocument(editable));
  return linksForSaving(editorDocumentToMarkdown(document), path, ORIGIN, documents);
}

describe('Editor.js 保存往返', () => {
  it('覆盖全部工作区文档', () => {
    expect(documents.length).toBeGreaterThan(10);
  });

  it.each(documents)('%s 的渲染结果不变且二次往返稳定', (path) => {
    const original = readFileSync(join(CONTENT, path), 'utf8');
    const saved = roundTrip(original, path);
    expect(render(saved)).toBe(render(original));
    expect(roundTrip(saved, path)).toBe(saved);
  });
});
