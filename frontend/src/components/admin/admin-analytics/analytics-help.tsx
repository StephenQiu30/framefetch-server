'use client';
import { InfoIcon } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from '@/components/ui/popover';

export function AnalyticsHelp({ kind }: { kind: 'downloads' | 'analysis' }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button aria-label="统计说明" size="icon" variant="ghost">
          <InfoIcon aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" aria-label="统计说明">
        <PopoverHeader>
          <PopoverTitle>统计说明</PopoverTitle>
        </PopoverHeader>
        <PopoverDescription>
          聚焦图表后用左右方向键读数，点击表格图标展开明细。
        </PopoverDescription>
        {kind === 'analysis' ? (
          <>
            <PopoverDescription>
              按创建日期（UTC）统计分析执行记录，重试和重新执行分别计数，不代表模型请求次数、Token
              或费用。
            </PopoverDescription>
            <PopoverDescription>
              成功率 = 成功 ÷（成功 +
              失败）。平均完成耗时仅包含起止时间有效的终态记录，无样本显示「—」。
            </PopoverDescription>
          </>
        ) : (
          <>
            <PopoverDescription>
              按创建日期（UTC）统计；成功率 = 成功 ÷
              全部任务。无任务的日期留空。来源按任务量展示前五名，明细包含全部来源。
            </PopoverDescription>
            <PopoverDescription>
              独立用户为周期内创建下载的用户；下载数据量为累计下载字节数。
            </PopoverDescription>
          </>
        )}
      </PopoverContent>
    </Popover>
  );
}
