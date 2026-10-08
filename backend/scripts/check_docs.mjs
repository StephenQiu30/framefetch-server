// 文档链接与锚点检查：在仓库根目录执行 node backend/scripts/check_docs.mjs。
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const files = execFileSync('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard'], {
  cwd: root,
  encoding: 'utf8',
}).split('\0').filter(Boolean);
const documents = [...new Set(files)].filter(
  (file) =>
    /\.mdx?$/.test(file) &&
    existsSync(path.join(root, file)) &&
    (file.startsWith('docs/') ||
      /^(AGENTS|PROJECT|CONTRIBUTING|SECURITY|design|BACKLOG|README(\.en)?)\.md$/.test(file) ||
      /^(backend|frontend)\/(README|AGENTS)\.md$/.test(file)),
);

// 与 GitHub、Obsidian 一致的标题锚点。
function anchors(markdown) {
  const seen = new Map();
  const result = new Set();
  let fenced = false;
  for (const line of markdown.split('\n')) {
    if (/^\s*(```|~~~)/.test(line)) fenced = !fenced;
    const heading = !fenced && line.match(/^#{1,6}\s+(.+?)\s*#*\s*$/);
    if (!heading) continue;
    const base = heading[1]
      .replace(/<[^>]+>/g, '')
      .replace(/[`*_~]|\[([^\]]*)\]\([^)]*\)/g, '$1')
      .trim()
      .toLowerCase()
      .replace(/[^\p{L}\p{N}\s_-]/gu, '')
      .replace(/\s/g, '-');
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    result.add(count ? `${base}-${count}` : base);
  }
  return result;
}

const errors = [];
for (const file of documents) {
  const text = readFileSync(path.join(root, file), 'utf8');
  let fenced = false;
  for (const line of text.split('\n')) {
    if (/^\s*(```|~~~)/.test(line)) fenced = !fenced;
    if (fenced) continue;
    for (const [, target] of line.matchAll(/\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g)) {
      if (/^([a-z]+:|\/)/i.test(target)) continue;
      const [rawPath, anchor] = target.split('#');
      const resolved = rawPath ? path.resolve(path.dirname(path.join(root, file)), decodeURI(rawPath)) : path.join(root, file);
      if (!existsSync(resolved)) {
        errors.push(`${file}: 链接目标不存在 ${target}`);
        continue;
      }
      if (anchor && /\.mdx?$/.test(resolved) && statSync(resolved).isFile()) {
        if (!anchors(readFileSync(resolved, 'utf8')).has(decodeURI(anchor).toLowerCase())) {
          errors.push(`${file}: 锚点不存在 ${target}`);
        }
      }
    }
  }
}

for (const error of errors) console.error(`错误：${error}`);
console.log(errors.length ? `文档检查失败：${errors.length} 项` : `文档检查通过：${documents.length} 份`);
process.exitCode = errors.length ? 1 : 0;
