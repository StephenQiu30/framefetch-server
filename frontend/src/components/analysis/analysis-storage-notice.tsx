import { ItemDescription } from '@/components/ui/item';
export default function AnalysisStorageNotice() {
  return (
    <ItemDescription className="line-clamp-none">
      原始文件持久保存；管理员清理前可基于同一输入重新分析。
    </ItemDescription>
  );
}
