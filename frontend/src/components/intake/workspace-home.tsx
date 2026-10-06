import { RecentDownloads } from '@/components/downloads/recent-downloads';
import DownloadWorkspace from '@/components/intake/download-workspace';

export function WorkspaceHome() {
  return (
    <div className="inner-page flex flex-col gap-12" data-slot="workspace-home">
      <DownloadWorkspace />
      <RecentDownloads />
    </div>
  );
}
