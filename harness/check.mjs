// 规范检查：禁止路径、规范文档链接与锚点、spec-map 完整性。
// 用法：node harness/check.mjs [--changed]；--changed 只检查工作区改动的文件路径。
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const specMap = JSON.parse(readFileSync(path.join(root, 'harness/spec-map.json'), 'utf8'));

const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8' });
const lines = (text) => text.split('\n').filter(Boolean);
const matches = (pattern, file) => new RegExp(pattern).test(file);

export const toRepoPath = (file) => {
  const relative = path.relative(root, path.resolve(root, file)).split(path.sep).join('/');
  return relative.startsWith('..') ? null : relative;
};

export const areasFor = (file) => specMap.areas.filter((area) => area.paths.some((p) => matches(p, file)));
export const protectedRule = (file) => specMap.protected.find((rule) => matches(rule.pattern, file));
export const forbiddenRule = (file) => specMap.forbidden.find((rule) => matches(rule.pattern, file));

export function changedFiles() {
  const tracked = lines(git('diff', '--name-only', 'HEAD'));
  const untracked = lines(git('ls-files', '--others', '--exclude-standard'));
  return [...new Set([...tracked, ...untracked])];
}

const allFiles = () => [...new Set([...lines(git('ls-files')), ...lines(git('ls-files', '--others', '--exclude-standard'))])];

// 与 GitHub、Nextra 一致的标题锚点。
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

const specDocuments = () =>
  allFiles().filter(
    (file) =>
      /\.mdx?$/.test(file) &&
      existsSync(path.join(root, file)) &&
      (file.startsWith('workspace/content/') ||
        /^(AGENTS|PROJECT|CONTRIBUTING|SECURITY|design|BACKLOG|README(\.en)?)\.md$/.test(file) ||
        /^(backend|frontend)\/(README|AGENTS)\.md$/.test(file)),
  );

function linkProblems(file) {
  const problems = [];
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
        problems.push(`${file}: 链接目标不存在 ${target}`);
        continue;
      }
      if (anchor && resolved.endsWith('.md') && statSync(resolved).isFile()) {
        if (!anchors(readFileSync(resolved, 'utf8')).has(decodeURI(anchor).toLowerCase())) {
          problems.push(`${file}: 锚点不存在 ${target}`);
        }
      }
    }
  }
  return problems;
}

export function check({ changedOnly = false } = {}) {
  const errors = [];
  const warnings = [];
  const files = changedOnly ? changedFiles() : allFiles();

  for (const file of files) {
    const rule = forbiddenRule(file);
    if (rule && existsSync(path.join(root, file))) errors.push(`${file}: ${rule.reason}`);
  }
  for (const area of specMap.areas) {
    for (const doc of area.docs) {
      if (!existsSync(path.join(root, doc))) errors.push(`harness/spec-map.json: ${area.id} 引用的 ${doc} 不存在`);
    }
  }
  for (const doc of specDocuments()) errors.push(...linkProblems(doc));

  if (changedOnly) {
    const contract = files.some((f) => /^backend\/app\/(api|schemas)\//.test(f));
    const generated = files.some((f) => f.startsWith('frontend/src/api/'));
    if (contract && !generated) {
      warnings.push('改动了 backend/app/api 或 schemas：若影响接口契约，需在 frontend 执行 pnpm openapi 并提交生成结果。');
    }
    if (files.some((f) => f === 'backend/sql/schema.sql') && !files.some((f) => f.startsWith('backend/app/models/'))) {
      warnings.push('改动了 schema.sql：确认 ORM 模型与测试已同步。');
    }
  }
  return { errors, warnings };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const { errors, warnings } = check({ changedOnly: process.argv.includes('--changed') });
  for (const warning of warnings) console.log(`提示：${warning}`);
  for (const error of errors) console.error(`错误：${error}`);
  console.log(errors.length ? `规范检查失败：${errors.length} 项` : '规范检查通过');
  process.exitCode = errors.length ? 1 : 0;
}
