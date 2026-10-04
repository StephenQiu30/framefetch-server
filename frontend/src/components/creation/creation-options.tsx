import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';

export function CreationOptions({
  skillId,
  value,
  onChange,
  disabled,
}: {
  skillId: string;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  disabled: boolean;
}) {
  function change(key: string, next: unknown) {
    onChange({ ...value, [key]: next });
  }
  return (
    <FieldGroup>
      <Field>
        <FieldLabel htmlFor="creation-purpose">任务目的</FieldLabel>
        <Textarea
          id="creation-purpose"
          value={typeof value.purpose === 'string' ? value.purpose : ''}
          onChange={(event) => change('purpose', event.target.value)}
          disabled={disabled}
          maxLength={2000}
          placeholder="说明希望完成什么，以及需要保留的观点和事实。"
        />
      </Field>
      <div className="grid gap-5 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor="creation-audience">受众（选填）</FieldLabel>
          <Input
            id="creation-audience"
            value={typeof value.audience === 'string' ? value.audience : ''}
            onChange={(event) => change('audience', event.target.value)}
            disabled={disabled}
            maxLength={400}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="creation-constraints">
            创作与保留要求（选填）
          </FieldLabel>
          <Input
            id="creation-constraints"
            value={
              typeof value.constraints === 'string' ? value.constraints : ''
            }
            onChange={(event) => change('constraints', event.target.value)}
            disabled={disabled}
            maxLength={2000}
          />
        </Field>
      </div>
      {skillId === 'article-edit' || skillId === 'article-write' ? (
        <Field>
          <FieldLabel htmlFor="creation-operation">处理方式</FieldLabel>
          <Select
            key={skillId}
            disabled={disabled}
            value={
              typeof value.mode === 'string'
                ? value.mode
                : skillId === 'article-edit'
                  ? 'format'
                  : 'draft'
            }
            onValueChange={(mode) => change('mode', mode)}
          >
            <SelectTrigger id="creation-operation">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {skillId === 'article-edit' ? (
                <>
                  <SelectItem value="format">
                    只整理格式，保留正文语义
                  </SelectItem>
                  <SelectItem value="rewrite">润色或结构重组</SelectItem>
                </>
              ) : (
                <>
                  <SelectItem value="outline">先形成提纲</SelectItem>
                  <SelectItem value="draft">形成正文候选</SelectItem>
                </>
              )}
            </SelectContent>
          </Select>
          <FieldDescription>
            改写与写作可能使用已配置模型。格式整理与重新导出不会自动调用模型。
          </FieldDescription>
        </Field>
      ) : null}
      {skillId === 'subtitle-edit' ? (
        <Field>
          <FieldLabel htmlFor="creation-duration">
            源视频时长（毫秒）
          </FieldLabel>
          <Input
            id="creation-duration"
            type="number"
            min={1}
            step={1}
            value={
              typeof value.duration_ms === 'number' ? value.duration_ms : ''
            }
            onChange={(event) =>
              change(
                'duration_ms',
                event.target.value ? Number(event.target.value) : undefined,
              )
            }
            disabled={disabled}
          />
          <FieldDescription>
            选择自己已完成的视频和已有字幕，按源视频时间校验字幕边界。没有真实识别结果不会补造对白。
          </FieldDescription>
        </Field>
      ) : null}
      {skillId === 'xhs-cards' ? (
        <Field>
          <FieldLabel htmlFor="creation-page-source">
            逐页内容（选填）
          </FieldLabel>
          <Textarea
            id="creation-page-source"
            rows={6}
            disabled={disabled}
            value={
              typeof value.page_source === 'string' ? value.page_source : ''
            }
            onChange={(event) => {
              const pageSource = event.target.value;
              const pages = pageSource.trim()
                ? pageSource.split(/\n---\n/u).map((page) => {
                    const [title, ...body] = page.trim().split('\n');
                    return { title: title ?? '', body: body.join('\n') };
                  })
                : undefined;
              onChange({ ...value, page_source: pageSource, pages });
            }}
            placeholder={
              '每页首行是标题，后续是正文。\n以单独一行 --- 分隔不同页。'
            }
          />
          <FieldDescription>
            留空则从确认稿整理。逐页源可以继续修改；实际卡片文件生成成功后才能作为图片交付。
          </FieldDescription>
        </Field>
      ) : null}
    </FieldGroup>
  );
}
