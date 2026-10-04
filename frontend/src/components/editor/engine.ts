import type { ToolConstructable } from '@editorjs/editorjs';

export async function loadEditorEngine() {
  // Editor.js and its tools access browser globals; never evaluate them during SSR.
  const [core, header, list, quote, code, table, delimiter, inlineCode] =
    await Promise.all([
      import('@editorjs/editorjs'),
      import('@editorjs/header'),
      import('@editorjs/list'),
      import('@editorjs/quote'),
      import('@editorjs/code'),
      import('@editorjs/table'),
      import('@editorjs/delimiter'),
      import('@editorjs/inline-code'),
    ]);
  return {
    EditorJS: core.default,
    tools: {
      header: {
        class: header.default as ToolConstructable,
        inlineToolbar: true,
        config: {
          levels: [1, 2, 3, 4, 5, 6],
          defaultLevel: 2,
          placeholder: '标题',
        },
      },
      list: {
        class: list.default as ToolConstructable,
        inlineToolbar: true,
        config: { defaultStyle: 'unordered' },
      },
      quote: {
        class: quote.default as ToolConstructable,
        inlineToolbar: true,
        config: {
          quotePlaceholder: '引用正文',
          captionPlaceholder: '引用署名（可选）',
        },
      },
      code: code.default as ToolConstructable,
      table: { class: table.default as ToolConstructable, inlineToolbar: true },
      delimiter: delimiter.default as ToolConstructable,
      inlineCode: inlineCode.default as ToolConstructable,
    },
  };
}
