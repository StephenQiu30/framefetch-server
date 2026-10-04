import { ShieldCheck } from '@phosphor-icons/react';

import { Button } from '@/components/ui/button';
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemMedia,
} from '@/components/ui/item';
import { Spinner } from '@/components/ui/spinner';

export function AnalysisExecutionNotice({
  busy,
  inputKind,
  onStart,
  resultContract,
}: {
  busy: boolean;
  inputKind: API.AnalysisInputKind;
  onStart: () => void;
  resultContract?: API.AnalysisResultContract;
}) {
  return (
    <Item className="items-start sm:flex-nowrap" size="sm">
      <ItemMedia variant="icon">
        <ShieldCheck aria-hidden />
      </ItemMedia>
      <ItemContent>
        <ItemDescription className="line-clamp-none max-w-3xl">
          {inputKind === 'screenplay' ? (
            <>
              剧本文本和任务要求会发送到所选云端模型处理。改写时还会包含需要统一的术语和相邻场景。
            </>
          ) : (
            <>
              应用会读取视频画面，并按任务复看需要的内容。画面、任务要求和必要上下文会发送到所选云端模型处理；原视频文件不会直接上传给模型服务。
            </>
          )}
        </ItemDescription>
      </ItemContent>
      <ItemActions className="mt-4 w-full sm:mt-0 sm:w-auto">
        <Button
          className="w-full shrink-0 sm:w-auto"
          disabled={busy || !resultContract}
          onClick={onStart}
        >
          {busy ? <Spinner aria-hidden data-icon="inline-start" /> : null}
          {resultContract === 'video-article'
            ? '整理成文章'
            : resultContract === 'screenplay-rewrite'
              ? '开始剧本改写'
              : inputKind === 'screenplay'
                ? '开始剧本分析'
                : '开始 AI 分析'}
        </Button>
      </ItemActions>
    </Item>
  );
}
