// Markdown 链接在“仓库相对路径”与“编辑器可用的绝对地址”之间互换。
// Editor.js 只保留 http(s) 链接，编辑前转为绝对地址，保存时再还原为相对路径。
import * as posix from './posix-path';

export const REPOSITORY = 'https://github.com/StephenQiu30/framefetch-server';
const CONTENT = 'workspace/content';
const LINK = /\]\(([^)\s]+)(\s+"[^"]*")?\)/g;
const FENCE = /^\s*(```|~~~)/;

/** design/14-解析引擎.md → /design/14-解析引擎；index.mdx → / */
export function documentRoute(path: string): string {
  const route = path.replace(/\.mdx?$/, '').replace(/(^|\/)index$/, '');
  return `/${route}`;
}

function mapLinks(markdown: string, map: (target: string) => string): string {
  let fenced = false;
  return markdown
    .split('\n')
    .map((line) => {
      if (FENCE.test(line)) fenced = !fenced;
      if (fenced) return line;
      return line.replace(LINK, (_, target: string, title = '') => `](${map(target)}${title})`);
    })
    .join('\n');
}

const splitAnchor = (target: string) => {
  const index = target.indexOf('#');
  return index < 0 ? [target, ''] : [target.slice(0, index), target.slice(index)];
};

export function linksForEditing(markdown: string, documentPath: string, origin: string): string {
  const directory = posix.dirname(documentPath);
  return mapLinks(markdown, (target) => {
    if (/^[a-z]+:/i.test(target) || target.startsWith('/')) return target;
    const [rawPath, anchor] = splitAnchor(target);
    if (!rawPath) return `${origin}${documentRoute(documentPath)}${anchor}`;
    const resolved = posix.normalize(posix.join(directory, decodeURI(rawPath)));
    if (!resolved.startsWith('..') && /\.mdx?$/.test(resolved)) {
      return `${origin}${encodeURI(documentRoute(resolved))}${anchor}`;
    }
    const repoPath = posix.normalize(posix.join(CONTENT, directory, decodeURI(rawPath)));
    const kind = posix.extname(repoPath) ? 'blob' : 'tree';
    return `${REPOSITORY}/${kind}/main/${encodeURI(repoPath)}${anchor}`;
  });
}

export function linksForSaving(
  markdown: string,
  documentPath: string,
  origin: string,
  documents: readonly string[],
): string {
  const directory = posix.dirname(documentPath);
  const routes = new Map(documents.map((path) => [documentRoute(path), path]));
  const relative = (to: string) => posix.relative(directory, to) || posix.basename(to);
  return mapLinks(markdown, (target) => {
    if (target.startsWith(`${origin}/`)) {
      const url = new URL(target);
      const path = routes.get(decodeURI(url.pathname));
      if (!path) return target;
      if (path === documentPath && url.hash) return url.hash;
      return `${encodeURI(relative(path))}${url.hash}`;
    }
    const repository = target.match(new RegExp(`^${REPOSITORY}/(?:blob|tree)/main/([^#]+)(#.*)?$`));
    if (repository) {
      const repoPath = decodeURI(repository[1]);
      return `${encodeURI(posix.relative(posix.join(CONTENT, directory), repoPath))}${repository[2] ?? ''}`;
    }
    return target;
  });
}
