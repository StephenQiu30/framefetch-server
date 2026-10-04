import { Button } from '@/components/ui/button';
import { Field, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';

const sections = [
  { key: 'pages', title: '逐页卡片', fields: ['title', 'body'] },
  { key: 'cues', title: '字幕与时轴', fields: ['start_ms', 'end_ms', 'text'] },
  {
    key: 'shots',
    title: '镜头与笔记',
    fields: ['start_ms', 'end_ms', 'description', 'note'],
  },
  {
    key: 'assets',
    title: '配图与图注',
    fields: ['alt', 'caption', 'placement'],
  },
] as const;

export function isCreationObject(
  value: unknown,
): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

export function CreationStructuredEditor({
  data,
  onChange,
  disabled,
  images = [],
}: {
  data: Record<string, unknown>;
  onChange: (data: Record<string, unknown>) => void;
  disabled: boolean;
  images?: API.CreationMaterialResponse[];
}) {
  function update(key: string, index: number, field: string, value: unknown) {
    const rows = data[key];
    if (!Array.isArray(rows)) return;
    onChange({
      ...data,
      [key]: rows.map((item, position) =>
        position === index && isCreationObject(item)
          ? { ...item, [field]: value }
          : item,
      ),
    });
  }
  function move(key: string, index: number, direction: -1 | 1) {
    const rows = data[key];
    if (!Array.isArray(rows)) return;
    const next = [...rows];
    const target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onChange({ ...data, [key]: next });
  }
  return (
    <div className="grid gap-8">
      {sections.map((section) => {
        const rows = data[section.key];
        if (!Array.isArray(rows) || rows.length === 0) return null;
        return (
          <section
            key={section.key}
            aria-label={section.title}
            className="grid gap-5"
          >
            <h3 className="font-medium">{section.title}</h3>
            {rows.map((row, index) => {
              if (!isCreationObject(row)) return null;
              const identity =
                typeof row.id === 'string' ? row.id : `${section.key}-${index}`;
              return (
                <div key={identity} className="grid min-w-0 gap-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <p>第 {index + 1} 项</p>
                    {section.key === 'pages' ? (
                      <>
                        <Button
                          type="button"
                          variant="outline"
                          disabled={disabled || index === 0}
                          onClick={() => move(section.key, index, -1)}
                          aria-label={`将第 ${index + 1} 项上移`}
                        >
                          上移
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          disabled={disabled || index === rows.length - 1}
                          onClick={() => move(section.key, index, 1)}
                          aria-label={`将第 ${index + 1} 项下移`}
                        >
                          下移
                        </Button>
                      </>
                    ) : null}
                  </div>
                  <div className="grid min-w-0 gap-4 sm:grid-cols-2">
                    {section.fields.map((field) => {
                      const current = row[field];
                      if (
                        current !== undefined &&
                        typeof current !== 'string' &&
                        typeof current !== 'number'
                      )
                        return null;
                      const number = field.endsWith('_ms');
                      const label = labels[field] ?? field;
                      const id = `creation-${section.key}-${index}-${field}`;
                      return (
                        <Field
                          key={field}
                          className={number ? '' : 'sm:col-span-2'}
                        >
                          <FieldLabel htmlFor={id}>
                            {label} · 第 {index + 1} 项
                          </FieldLabel>
                          {number ? (
                            <Input
                              id={id}
                              type="number"
                              min={0}
                              step={1}
                              value={typeof current === 'number' ? current : ''}
                              disabled={disabled}
                              onChange={(event) =>
                                update(
                                  section.key,
                                  index,
                                  field,
                                  Number(event.target.value),
                                )
                              }
                            />
                          ) : (
                            <Textarea
                              id={id}
                              disabled={disabled}
                              value={typeof current === 'string' ? current : ''}
                              onChange={(event) =>
                                update(
                                  section.key,
                                  index,
                                  field,
                                  event.target.value,
                                )
                              }
                            />
                          )}
                        </Field>
                      );
                    })}
                    {section.key === 'pages' ? (
                      <Field className="sm:col-span-2">
                        <FieldLabel htmlFor={`creation-page-image-${index}`}>
                          授权配图 · 第 {index + 1} 项
                        </FieldLabel>
                        <Select
                          value={
                            typeof row.image_material_id === 'string'
                              ? row.image_material_id
                              : 'none'
                          }
                          disabled={disabled}
                          onValueChange={(value) =>
                            update(
                              section.key,
                              index,
                              'image_material_id',
                              value === 'none' ? null : value,
                            )
                          }
                        >
                          <SelectTrigger id={`creation-page-image-${index}`}>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="none">不使用配图</SelectItem>
                            {images.map((image) => (
                              <SelectItem key={image.id} value={image.id}>
                                {image.title}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <p className="text-sm text-muted-foreground">
                          只使用本次任务已选择并确认的原图。新配图请先导入确认，再创建包含该图片的任务。
                        </p>
                      </Field>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </section>
        );
      })}
    </div>
  );
}

const labels: Record<string, string> = {
  title: '标题',
  body: '正文',
  text: '对白',
  description: '画面观察',
  note: '人工注释',
  start_ms: '源起点（毫秒）',
  end_ms: '源终点（毫秒）',
  alt: '替代文本',
  caption: '图注',
  placement: '使用位置',
};
