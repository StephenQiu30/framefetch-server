import { RecentDownloads } from '@/components/downloads/recent-downloads';
import DownloadWorkspace from '@/components/intake/download-workspace';
import { SplitLayout } from '@/components/layout/split-layout';
import { SupportedPlatforms } from '@/components/providers/supported-platforms';

export function WorkspaceHome() {
  return (
    <div className="inner-page flex flex-col gap-12" data-slot="workspace-home">
      <DownloadWorkspace />
      <SplitLayout columns="primary">
        <RecentDownloads />
        <SupportedPlatforms />
      </SplitLayout>
    </div>
  );
}
