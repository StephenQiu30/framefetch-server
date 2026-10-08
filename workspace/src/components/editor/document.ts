import type { OutputData } from '@editorjs/editorjs';
import { Marked, type Token, type Tokens } from 'marked';
import { sanitizeRichText } from './rich-text';

export type EditorDocument = OutputData;
export type ListItem = {
  content: string;
  meta: { checked?: boolean };
  items: ListItem[];
};

export type HtmlPolicy = 'omit' | 'text';

function createMarkdown(htmlPolicy: HtmlPolicy) {
  return new Marked({
    gfm: true,
    renderer: {
      html: ({ text }) =>
        htmlPolicy === 'text'
          ? text
              .replace(/&/g, '&amp;')
              .replace(/</g, '&lt;')
              .replace(/>/g, '&gt;')
          : '',
    },
  });
}

function inline(markdown: Marked, tokens: Token[]) {
  return markdown.Parser.parseInline(tokens, markdown.defaults);
}

function listItems(markdown: Marked, items: Tokens.ListItem[]): ListItem[] {
  return items.map((item) => ({
    content: item.tokens
      .filter((token) => token.type !== 'list')
      .map((token) => markdown.parser([token]))
      .join(''),
    meta: item.task ? { checked: item.checked } : {},
    items: item.tokens.flatMap((token) =>
      token.type === 'list'
        ? listItems(markdown, (token as Tokens.List).items)
        : [],
    ),
  }));
}

function blocksFromTokens(
  markdown: Marked,
  tokens: Token[],
): EditorDocument['blocks'] {
  return tokens.flatMap((token): EditorDocument['blocks'] => {
    switch (token.type) {
      case 'space':
        return [];
      case 'html': {
        const text = markdown.parser([token]);
        return text ? [{ type: 'paragraph', data: { text } }] : [];
      }
      case 'heading': {
        const heading = token as Tokens.Heading;
        return [
          {
            type: 'header',
            data: {
              text: inline(markdown, heading.tokens),
              level: heading.depth,
            },
          },
        ];
      }
      case 'code': {
        const code = token as Tokens.Code;
        return [
          {
            type: 'code',
            data: code.lang
              ? { code: `${code.text}\n`, language: code.lang }
              : { code: `${code.text}\n` },
          },
        ];
      }
      case 'hr':
        return [{ type: 'delimiter', data: {} }];
      case 'blockquote':
        return [
          {
            type: 'quote',
            data: {
              text: markdown.parser((token as Tokens.Blockquote).tokens),
              caption: '',
              alignment: 'left',
            },
          },
        ];
      case 'list': {
        const list = token as Tokens.List;
        // GFM can place ordinary items and task items in the same loose list.
        // Official list blocks have one style, so import each consecutive style separately.
        const groups: {
          task: boolean;
          start: number;
          items: Tokens.ListItem[];
        }[] = [];
        list.items.forEach((item, index) => {
          const task = Boolean(item.task);
          const previous = groups.at(-1);
          if (previous?.task === task) previous.items.push(item);
          else
            groups.push({
              task,
              start: (Number(list.start) || 1) + index,
              items: [item],
            });
        });
        return groups.map((group) => ({
          type: 'list',
          data: {
            style: group.task
              ? 'checklist'
              : list.ordered
                ? 'ordered'
                : 'unordered',
            meta:
              list.ordered && !group.task
                ? { start: group.start, counterType: 'numeric' }
                : {},
            items: listItems(markdown, group.items),
          },
        }));
      }
      case 'table': {
        const table = token as Tokens.Table;
        return [
          {
            type: 'table',
            data: {
              withHeadings: true,
              content: [table.header, ...table.rows].map((row) =>
                row.map((cell) => inline(markdown, cell.tokens)),
              ),
            },
          },
        ];
      }
      default:
        return [
          {
            type: 'paragraph',
            data: {
              text:
                'tokens' in token
                  ? inline(markdown, token.tokens as Token[])
                  : markdown.parseInline(
                      'text' in token ? String(token.text) : token.raw,
                    ),
            },
          },
        ];
    }
  });
}

/** Import the supported Markdown subset at the API boundary; this is not a lossless serializer. */
export function markdownToEditorDocument(
  content: string,
  htmlPolicy: HtmlPolicy = 'omit',
): EditorDocument {
  const markdown = createMarkdown(htmlPolicy);
  return { blocks: blocksFromTokens(markdown, markdown.lexer(content)) };
}

export function documentKey(document: EditorDocument) {
  return JSON.stringify(document.blocks);
}

/** Sanitize rich HTML before official tools insert it into the document. Unknown tools stay inert in the official Stub. */
export function sanitizeEditorDocument(
  document: EditorDocument,
  links = true,
): EditorDocument {
  if (!document || !Array.isArray(document.blocks))
    throw new Error('文档必须包含有效的内容块');
  const cleanItems = (items: ListItem[]): ListItem[] =>
    items.map((item) => ({
      ...item,
      content: sanitizeRichText(item.content, links),
      items: cleanItems(item.items ?? []),
    }));
  return {
    ...document,
    blocks: document.blocks.map((block) => {
      const data = { ...block.data };
      switch (block.type) {
        case 'paragraph':
        case 'header':
        case 'quote':
          data.text = sanitizeRichText(String(data.text ?? ''), links);
          if (typeof data.caption === 'string')
            data.caption = sanitizeRichText(data.caption, links);
          break;
        case 'list':
          data.items = cleanItems(data.items ?? []);
          break;
        case 'table':
          data.content = (data.content ?? []).map((row: string[]) =>
            row.map((cell) => sanitizeRichText(cell, links)),
          );
          break;
      }
      return { ...block, data };
    }),
  };
}
