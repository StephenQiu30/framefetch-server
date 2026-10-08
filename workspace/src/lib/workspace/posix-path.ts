// 浏览器与服务端共用的 POSIX 路径运算，只处理相对路径。
function segments(path: string): string[] {
  const result: string[] = [];
  for (const part of path.split('/')) {
    if (!part || part === '.') continue;
    if (part === '..' && result.length && result.at(-1) !== '..') result.pop();
    else result.push(part);
  }
  return result;
}

export const normalize = (path: string) => segments(path).join('/') || '.';
export const join = (...parts: string[]) => normalize(parts.filter(Boolean).join('/'));
export const dirname = (path: string) => {
  const parts = segments(path);
  return parts.length > 1 ? parts.slice(0, -1).join('/') : '.';
};
export const basename = (path: string) => segments(path).at(-1) ?? '';
export const extname = (path: string) => /\.[^./]+$/.exec(basename(path))?.[0] ?? '';

export function relative(from: string, to: string): string {
  const source = segments(from === '.' ? '' : from);
  const target = segments(to);
  let shared = 0;
  while (shared < source.length && source[shared] === target[shared]) shared += 1;
  return [...source.slice(shared).map(() => '..'), ...target.slice(shared)].join('/');
}
