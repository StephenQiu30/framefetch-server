import 'server-only';
import { createHash } from 'node:crypto';
import { readdir, readFile, realpath } from 'node:fs/promises';
import path from 'node:path';
import { runInNewContext } from 'node:vm';
import { parseDocument } from 'htmlparser2';
import { Marked } from 'marked';
import type { PageMapItem } from 'nextra';
import { normalizePageMap } from 'nextra/page-map';
const documentRoute = (file: string) =>
  `/${file.replace(/\.mdx?$/, '').replace(/(^|\/)index$/, '')}`;

// 运行时直接读取 content/，网页保存或 Obsidian 修改后无需重建即可渲染。
export const contentRoot = path.join(process.cwd(), 'content');

export type ContentFile = { path: string; source: string };

const missing = (error: unknown) =>
  ['ENOENT', 'ENOTDIR'].includes((error as NodeJS.ErrnoException).code ?? '');

export async function readContentFile(
  segments: string[] = [],
): Promise<ContentFile | null> {
  let route: string;
  try {
    route = segments.map((segment) => decodeURIComponent(segment)).join('/');
  } catch {
    return null;
  }
  const candidates = route
    ? [`${route}.md`, `${route}.mdx`, `${route}/index.mdx`]
    : ['index.mdx'];
  for (const candidate of candidates) {
    const file = path.resolve(contentRoot, candidate);
    if (!file.startsWith(`${contentRoot}${path.sep}`)) return null;
    try {
      const resolved = await realpath(file);
      if (!resolved.startsWith(`${await realpath(contentRoot)}${path.sep}`))
        return null;
      return { path: candidate, source: await readFile(resolved, 'utf8') };
    } catch (error) {
      if (!missing(error)) throw error;
    }
  }
  return null;
}

async function scanContentFiles(
  directory = contentRoot,
): Promise<ContentFile[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map(async (entry): Promise<ContentFile[]> => {
      if (entry.name.startsWith('.') || entry.isSymbolicLink()) return [];
      const file = path.join(directory, entry.name);
      try {
        if (entry.isDirectory()) return await scanContentFiles(file);
        if (
          !entry.isFile() ||
          (!/\.mdx?$/.test(entry.name) && entry.name !== '_meta.js')
        )
          return [];
        return [
          {
            path: path.relative(contentRoot, file).split(path.sep).join('/'),
            source: await readFile(file, 'utf8'),
          },
        ];
      } catch (error) {
        // 编辑器可能在列目录后原子替换或删除文件；下一次请求会读取新目录。
        if (missing(error)) return [];
        throw error;
      }
    }),
  );
  return nested.flat().sort((a, b) => a.path.localeCompare(b.path));
}

export async function listContentFiles(): Promise<ContentFile[]> {
  return (await scanContentFiles()).filter((file) => /\.mdx?$/.test(file.path));
}

export async function contentRevision(): Promise<string> {
  const hash = createHash('sha256');
  for (const file of await scanContentFiles())
    hash.update(JSON.stringify([file.path, file.source]));
  return hash.digest('hex');
}

const markdown = new Marked({ gfm: true });
type HtmlNode = ReturnType<typeof parseDocument>['children'][number];
const plain = (nodes: HtmlNode[]): string =>
  nodes
    .map((node): string =>
      node.type === 'text'
        ? node.data
        : 'children' in node
          ? plain(node.children as HtmlNode[])
          : '',
    )
    .join(' ');
export const contentText = (source: string) =>
  plain(parseDocument(markdown.parse(source, { async: false })).children)
    .replace(/\s+/g, ' ')
    .trim();
export const contentTitle = (file: ContentFile) => {
  const heading = markdown
    .lexer(file.source)
    .find((token) => token.type === 'heading' && token.depth === 1);
  return heading && 'text' in heading
    ? contentText(heading.text)
    : path.basename(file.path, path.extname(file.path));
};

export async function contentPageMap(): Promise<PageMapItem[]> {
  const files = await listContentFiles();
  async function folder(prefix: string): Promise<PageMapItem[]> {
    const children: PageMapItem[] = [];
    const directories = new Set<string>();
    for (const file of files.filter((file) => file.path.startsWith(prefix))) {
      const relative = file.path.slice(prefix.length);
      if (relative.includes('/')) directories.add(relative.split('/')[0]);
      else
        children.push({
          name: relative.replace(/\.mdx?$/, ''),
          route: encodeURI(documentRoute(file.path)),
          frontMatter: { title: contentTitle(file) },
        });
    }
    for (const name of directories) {
      children.push({
        name,
        route: encodeURI(`/${prefix}${name}`),
        children: await folder(`${prefix}${name}/`),
      });
    }
    try {
      // _meta.js 是仓库维护的纯数据对象；每次读取，不依赖 Node 模块缓存。
      const source = await readFile(
        path.join(contentRoot, prefix, '_meta.js'),
        'utf8',
      );
      const data = JSON.parse(
        JSON.stringify(
          runInNewContext(
            `(${source
              .trim()
              .replace(/^export\s+default\s+/, '')
              .replace(/;\s*$/, '')})`,
            {},
            { timeout: 100 },
          ),
        ),
      );
      children.unshift({ data });
    } catch (error) {
      if (!missing(error)) throw error;
    }
    return children;
  }
  return normalizePageMap([
    ...await folder(''),
  ]) as PageMapItem[];
}

export type ContentSearchResult = {
  url: string;
  title: string;
  excerpt: string;
};
export async function searchContent(
  query: string,
): Promise<ContentSearchResult[]> {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return [];
  return (await listContentFiles())
    .flatMap((file) => {
      const title = contentTitle(file);
      const text = contentText(file.source);
      const searchable = `${title} ${text}`.toLocaleLowerCase();
      if (!terms.every((term) => searchable.includes(term))) return [];
      const offset = Math.max(
        0,
        text.toLocaleLowerCase().indexOf(terms[0]) - 45,
      );
      return [
        {
          url: documentRoute(file.path),
          title,
          excerpt: `${offset ? '…' : ''}${text.slice(offset, offset + 180)}${text.length > offset + 180 ? '…' : ''}`,
        },
      ];
    })
    .slice(0, 20);
}
