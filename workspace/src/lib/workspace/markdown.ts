// Editor.js 文档序列化为 GFM Markdown；与 frontend 的 markdownToEditorDocument 配对使用。
import { parseDocument } from 'htmlparser2';
import type { EditorDocument, ListItem } from '@/components/editor/document';

type Node = ReturnType<typeof parseDocument>['children'][number];
type Block = EditorDocument['blocks'][number];

const escapeText = (text: string) => text.replace(/([\\`*[\]<>])/g, '\\$1');

function codeSpan(text: string): string {
  const longest = Math.max(0, ...[...text.matchAll(/`+/g)].map((m) => m[0].length));
  const fence = '`'.repeat(longest + 1);
  const pad = text.startsWith('`') || text.endsWith('`') ? ' ' : '';
  return `${fence}${pad}${text}${pad}${fence}`;
}

function plain(nodes: Node[]): string {
  return nodes
    .map((node) => (node.type === 'text' ? node.data : 'children' in node ? plain(node.children as Node[]) : ''))
    .join('');
}

function inline(nodes: Node[], lineBreak: string): string {
  return nodes
    .map((node) => {
      if (node.type === 'text') return escapeText(node.data);
      if (node.type !== 'tag') return '';
      const children = node.children as Node[];
      const content = () => inline(children, lineBreak);
      switch (node.name) {
        case 'b':
        case 'strong':
          return `**${content()}**`;
        case 'i':
        case 'em':
          return `*${content()}*`;
        case 's':
        case 'del':
        case 'strike':
          return `~~${content()}~~`;
        case 'code':
          return codeSpan(plain(children));
        case 'a':
          return `[${content()}](${node.attribs.href ?? ''})`;
        case 'br':
          return lineBreak;
        case 'p':
          return `${content()}\n\n`;
        default:
          return content();
      }
    })
    .join('');
}

/** Inline HTML from Editor.js → Markdown; paragraphs inside a block become blank-line separated. */
export function htmlToMarkdown(html: string, lineBreak = '\\\n'): string {
  return inline(parseDocument(html, { decodeEntities: true }).children as Node[], lineBreak)
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function list(items: ListItem[], style: string, start: number, depth: string): string[] {
  return items.flatMap((item, index) => {
    const marker =
      style === 'ordered'
        ? `${start + index}. `
        : style === 'checklist'
          ? `- [${item.meta?.checked ? 'x' : ' '}] `
          : '- ';
    const indent = `${depth}${' '.repeat(marker.length)}`;
    const [first = '', ...rest] = htmlToMarkdown(item.content).split('\n');
    const lines = [`${depth}${marker}${first}`, ...rest.map((line) => (line ? `${indent}${line}` : ''))];
    const nested = item.items?.length ? list(item.items, style, 1, indent) : [];
    return [...lines, ...nested];
  });
}

function tableCell(html: string): string {
  return htmlToMarkdown(html, '<br>').replace(/\n+/g, '<br>').replace(/\|/g, '\\|');
}

function block(block: Block): string {
  const data = block.data as Record<string, any>;
  switch (block.type) {
    case 'header':
      return `${'#'.repeat(Math.min(6, Math.max(1, Number(data.level) || 2)))} ${htmlToMarkdown(data.text ?? '')}`;
    case 'paragraph':
      return htmlToMarkdown(data.text ?? '');
    case 'list':
      return list(data.items ?? [], data.style, Number(data.meta?.start) || 1, '').join('\n');
    case 'code': {
      const code = String(data.code ?? '').replace(/\n$/, '');
      const fence = '`'.repeat(Math.max(3, ...[...code.matchAll(/^`{3,}/gm)].map((m) => m[0].length + 1)));
      return `${fence}${data.language ?? ''}\n${code}\n${fence}`;
    }
    case 'quote':
      return htmlToMarkdown(data.text ?? '')
        .split('\n')
        .map((line) => (line ? `> ${line}` : '>'))
        .join('\n');
    case 'delimiter':
      return '---';
    case 'table': {
      const rows: string[][] = data.content ?? [];
      if (!rows.length) return '';
      const width = Math.max(...rows.map((row) => row.length));
      const line = (cells: string[]) =>
        `| ${Array.from({ length: width }, (_, i) => tableCell(cells[i] ?? '')).join(' | ')} |`;
      const [head, ...body] = data.withHeadings ? rows : [Array(width).fill(''), ...rows];
      return [line(head), `| ${Array(width).fill('---').join(' | ')} |`, ...body.map(line)].join('\n');
    }
    default:
      throw new Error(`不支持保存的内容块：${block.type}`);
  }
}

export function editorDocumentToMarkdown(document: EditorDocument): string {
  return `${document.blocks.map(block).filter(Boolean).join('\n\n')}\n`;
}
