import type { ToolConstructable } from '@editorjs/editorjs';

type CodeToolOptions = { data?: { code?: string; language?: string } };
type CodeToolInstance = { save(element: HTMLElement): { code: string } };

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
  // The official code tool saves only `code`; keep the fenced language (e.g. mermaid).
  const OfficialCode = code.default as unknown as new (
    options: CodeToolOptions,
  ) => CodeToolInstance;
  class LanguageCode extends OfficialCode {
    private readonly language?: string;
    constructor(options: CodeToolOptions) {
      super(options);
      this.language = options.data?.language;
    }
    save(element: HTMLElement) {
      const data = super.save(element);
      return this.language ? { ...data, language: this.language } : data;
    }
  }
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
      code: LanguageCode as unknown as ToolConstructable,
      table: { class: table.default as ToolConstructable, inlineToolbar: true },
      delimiter: delimiter.default as ToolConstructable,
      inlineCode: inlineCode.default as ToolConstructable,
    },
  };
}
