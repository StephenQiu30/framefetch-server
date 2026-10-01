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
              规范化剧本文本、任务指令，以及改写时必要的术语表和有界相邻上下文会发送到所选云端模型处理。受限剧本执行器不能使用文件、Shell、网络、浏览器、插件或其他
              Agent。
            </>
          ) : (
            <>
              完整视频文件会交给本机 Agent；Agent
              必须覆盖全片时间轴并自主复核分镜边界与高光，不以预先抽取的固定帧集替代分析。Agent
              实际查看的画面帧、任务指令和必要上下文会发送到所选云端模型处理；应用不会把原始视频容器直接上传给模型服务。
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
