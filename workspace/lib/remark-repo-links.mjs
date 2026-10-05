// content/ 之外的相对链接（仓库根文件、源码）改写为 GitHub 地址，站内文档链接交给 Nextra。
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { visit } from 'unist-util-visit';

const repository = 'https://github.com/StephenQiu30/video-server';
const contentDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '../content');
const repoRoot = path.join(contentDir, '../..');

export default function remarkRepoLinks() {
  return (tree, file) => {
    if (!file.path) return;
    const from = path.dirname(path.resolve(file.path));
    visit(tree, (node) => {
      if ((node.type !== 'link' && node.type !== 'image') || !node.url) return;
      if (/^([a-z]+:|#|\/)/i.test(node.url)) return;
      const [target, anchor] = node.url.split('#');
      const absolute = path.resolve(from, decodeURI(target));
      if (absolute.startsWith(contentDir + path.sep)) return;
      const relative = path.relative(repoRoot, absolute).split(path.sep).join('/');
      if (relative.startsWith('..')) return;
      const kind = node.type === 'image' ? 'raw' : path.extname(relative) ? 'blob' : 'tree';
      node.url = `${repository}/${kind}/main/${encodeURI(relative)}${anchor ? `#${anchor}` : ''}`;
    });
  };
}
