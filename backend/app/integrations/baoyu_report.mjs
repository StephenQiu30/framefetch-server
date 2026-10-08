// Adapter only. The imported implementation and themes are pinned originals.
import { renderMarkdownDocument } from '../services/analysis/skills/upstream/baoyu/packages/baoyu-md/dist/index.js';
let source = '';
for await (const chunk of process.stdin) {
  source += chunk;
  if (Buffer.byteLength(source) > 1024 * 1024) throw new Error('Markdown exceeds limit');
}
const { html } = await renderMarkdownDocument(source, { theme: 'default', keepTitle: true, citeStatus: false });
process.stdout.write(html);
