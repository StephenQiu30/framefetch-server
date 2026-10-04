import type { OutputData } from '@editorjs/editorjs';
import { Marked, type Token, type Tokens } from 'marked';

export type EditorDocument = OutputData;
export type EditorContent = EditorDocument | string;
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
            data: { code: `${code.text}\n`, language: code.lang ?? '' },
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
        return [
          {
            type: 'list',
            data: {
              style: list.items.some((item) => item.task)
                ? 'checklist'
                : list.ordered
                  ? 'ordered'
                  : 'unordered',
              meta: list.ordered
                ? { start: list.start, counterType: 'numeric' }
                : {},
              items: listItems(markdown, list.items),
            },
          },
        ];
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

export function toEditorDocument(
  content: EditorContent,
  htmlPolicy: HtmlPolicy = 'omit',
): EditorDocument {
  if (typeof content !== 'string') return content;
  const markdown = createMarkdown(htmlPolicy);
  return { blocks: blocksFromTokens(markdown, markdown.lexer(content)) };
}

export function documentKey(document: EditorDocument) {
  return JSON.stringify(document.blocks);
}

/** Only registered tools cross the editable boundary. */
export function assertEditableDocument(document: EditorDocument) {
  const types = new Set([
    'paragraph',
    'header',
    'list',
    'quote',
    'code',
    'table',
    'delimiter',
  ]);
  if (document.blocks.some((block) => !types.has(block.type))) {
    throw new Error('文档包含编辑器尚未支持的内容块');
  }
}
