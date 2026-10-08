import { parseDocument } from 'htmlparser2';

const allowedTags = new Set([
  'b',
  'strong',
  'i',
  'em',
  's',
  'del',
  'strike',
  'code',
  'br',
  'p',
  'ul',
  'ol',
  'li',
  'pre',
  'blockquote',
]);

export function safeWebUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return;
  try {
    const url = new URL(value);
    if (url.protocol === 'https:' || url.protocol === 'http:') return url.href;
  } catch {
    return;
  }
}

function escapeText(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Strip active markup before passing rich text to third-party block tools. */
export function sanitizeRichText(text: string, links = true): string {
  function serialize(
    nodes: ReturnType<typeof parseDocument>['children'],
  ): string {
    return nodes
      .map((node) => {
        if (node.type === 'text') return escapeText(node.data);
        if (node.type !== 'tag') return '';
        const children = serialize(node.children);
        if (node.name === 'a') {
          const href = links ? safeWebUrl(node.attribs.href) : undefined;
          return href
            ? `<a href="${escapeText(href)}">${children}</a>`
            : children;
        }
        if (!allowedTags.has(node.name)) return children;
        return node.name === 'br'
          ? '<br>'
          : `<${node.name}>${children}</${node.name}>`;
      })
      .join('');
  }
  return serialize(parseDocument(text).children);
}

export function richTextToPlainText(text: string): string {
  function read(nodes: ReturnType<typeof parseDocument>['children']): string {
    return nodes
      .map((node) =>
        node.type === 'text'
          ? node.data
          : node.type === 'tag'
            ? read(node.children)
            : '',
      )
      .join('');
  }
  return read(parseDocument(text).children);
}
