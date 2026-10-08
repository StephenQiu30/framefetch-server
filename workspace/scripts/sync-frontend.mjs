// 从 frontend 同步工作区复用的主题、品牌、编辑器与生成接口；frontend 是唯一来源。
// 用法：pnpm sync 更新快照；pnpm sync:check 校验快照未被改动且与 frontend 一致。
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const workspace = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const frontend = path.resolve(workspace, '../frontend');
const manifestPath = path.join(workspace, 'frontend-sync.json');

// 入口文件；其 `@/` 与相对导入会被递归纳入。
const entries = [
  'src/app/globals.css',
  'src/components/editor/index.ts',
  'src/components/ui/button.tsx',
  'src/components/ui/sonner.tsx',
  'src/lib/backend-origin.ts',
  'src/api/auth.ts',
  'src/api/workspace.ts',
  'src/api/typings.d.ts',
  'public/logo.svg',
  'public/logo.png',
  'public/favicon.ico',
  'components.json',
];

// 工作区的 Next 应用目录在根目录 app/，主题样式放在 src/styles/。
const targets = { 'src/app/globals.css': 'src/styles/globals.css' };
const targetOf = (file) => targets[file] ?? file;

const digest = (data) => createHash('sha256').update(data).digest('hex');

function resolveImport(from, specifier) {
  const base = specifier.startsWith('@/')
    ? path.join('src', specifier.slice(2))
    : path.join(path.dirname(from), specifier);
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, path.join(base, 'index.ts')]) {
    const file = path.join(frontend, candidate);
    if (existsSync(file) && statSync(file).isFile()) return candidate.split(path.sep).join('/');
  }
  throw new Error(`无法解析 ${from} 中的 ${specifier}`);
}

function closure() {
  const files = new Set();
  const queue = [...entries];
  while (queue.length) {
    const file = queue.pop();
    if (files.has(file)) continue;
    files.add(file);
    if (!/\.(ts|tsx)$/.test(file)) continue;
    const source = readFileSync(path.join(frontend, file), 'utf8');
    for (const [, specifier] of source.matchAll(/(?:from|import)\s*\(?\s*['"]([^'"]+)['"]/g)) {
      if (specifier.startsWith('@/') || specifier.startsWith('.')) queue.push(resolveImport(file, specifier));
    }
  }
  return [...files].sort();
}

function sync() {
  const files = closure().map((file) => {
    const data = readFileSync(path.join(frontend, file));
    const target = targetOf(file);
    mkdirSync(path.dirname(path.join(workspace, target)), { recursive: true });
    writeFileSync(path.join(workspace, target), data);
    return { path: file, target, sha256: digest(data) };
  });
  writeFileSync(manifestPath, `${JSON.stringify({ source: 'frontend', files }, null, 2)}\n`);
  console.log(`已从 frontend 同步 ${files.length} 个文件`);
}

function check() {
  const { files } = JSON.parse(readFileSync(manifestPath, 'utf8'));
  const errors = [];
  for (const { path: file, target, sha256 } of files) {
    const local = path.join(workspace, target);
    if (!existsSync(local) || digest(readFileSync(local)) !== sha256) errors.push(`${file}: 本地副本被修改，请改 frontend 后执行 pnpm sync`);
    const upstream = path.join(frontend, file);
    if (existsSync(frontend) && (!existsSync(upstream) || digest(readFileSync(upstream)) !== sha256)) {
      errors.push(`${file}: frontend 已变化，请执行 pnpm sync`);
    }
  }
  if (existsSync(frontend)) {
    const expected = closure().join('\n');
    if (expected !== files.map((f) => f.path).join('\n')) errors.push('同步文件集合与 frontend 依赖闭包不一致，请执行 pnpm sync');
  }
  for (const error of errors) console.error(`错误：${error}`);
  console.log(errors.length ? `同步检查失败：${errors.length} 项` : `同步检查通过：${files.length} 个文件`);
  process.exitCode = errors.length ? 1 : 0;
}

process.argv.includes('--check') ? check() : sync();
