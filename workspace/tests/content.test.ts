import {
  mkdtemp,
  mkdir,
  rename,
  rm,
  symlink,
  writeFile,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('server-only', () => ({}));

let directory: string;
let original: string;
let content: typeof import('@/lib/workspace/content');

beforeAll(async () => {
  directory = await mkdtemp(path.join(tmpdir(), 'framefetch-content-'));
  original = process.cwd();
  await mkdir(path.join(directory, 'content', 'design'), { recursive: true });
  process.chdir(directory);
  content = await import('@/lib/workspace/content');
});
afterAll(async () => {
  process.chdir(original);
  await rm(directory, { recursive: true, force: true });
});

describe('运行时文档内容', () => {
  it('原子替换、新增和删除立即影响正文、导航与搜索', async () => {
    const file = path.join(directory, 'content', 'design', 'guide.md');
    await writeFile(file, '# 旧标题\n\n旧关键词');
    const before = await content.contentRevision();
    expect(await content.searchContent('旧关键词')).toHaveLength(1);
    await writeFile(`${file}.tmp`, '# 新标题\n\n更新后的独有词');
    await rename(`${file}.tmp`, file);
    expect(await content.contentRevision()).not.toBe(before);
    expect(
      (await content.readContentFile(['design', 'guide']))?.source,
    ).toContain('新标题');
    expect(await content.searchContent('旧关键词')).toHaveLength(0);
    expect(await content.searchContent('更新后的独有词')).toMatchObject([
      { title: '新标题', url: '/design/guide' },
    ]);
    expect(JSON.stringify(await content.contentPageMap())).toContain('新标题');
    expect(await content.readContentFile(['design', 'new'])).toBeNull();
    await writeFile(
      path.join(directory, 'content', 'design', 'new.md'),
      '# 新文档\n\n新增关键词',
    );
    expect(JSON.stringify(await content.contentPageMap())).toContain(
      '/design/new',
    );
    expect(await content.searchContent('新增关键词')).toHaveLength(1);
    await rm(file);
    expect(await content.readContentFile(['design', 'guide'])).toBeNull();
    expect(JSON.stringify(await content.contentPageMap())).not.toContain(
      '/design/guide',
    );
    expect(await content.searchContent('更新后的独有词')).toHaveLength(0);
  });

  it('中文文档导航使用与浏览器一致的编码路径', async () => {
    await writeFile(
      path.join(directory, 'content', 'design', '中文标题.md'),
      '# 中文标题',
    );
    expect(JSON.stringify(await content.contentPageMap())).toContain(
      '/design/%E4%B8%AD%E6%96%87%E6%A0%87%E9%A2%98',
    );
  });

  it('导航数据原子替换后不受模块缓存影响', async () => {
    const meta = path.join(directory, 'content', '_meta.js');
    await writeFile(meta, "export default { design: '设计' };\n");
    expect(JSON.stringify(await content.contentPageMap())).toContain('设计');
    await writeFile(`${meta}.tmp`, "export default { design: '系统设计' };\n");
    await rename(`${meta}.tmp`, meta);
    expect(JSON.stringify(await content.contentPageMap())).toContain(
      '系统设计',
    );
  });

  it('拒绝路径越界与指向内容目录外的符号链接', async () => {
    await writeFile(path.join(directory, 'private.md'), '不应暴露的内容');
    await symlink(
      path.join(directory, 'private.md'),
      path.join(directory, 'content', 'secret.md'),
    );
    expect(await content.readContentFile(['..', 'private'])).toBeNull();
    expect(await content.readContentFile(['%2e%2e', 'private'])).toBeNull();
    expect(await content.readContentFile(['secret'])).toBeNull();
    expect(await content.searchContent('不应暴露')).toHaveLength(0);
  });
});
