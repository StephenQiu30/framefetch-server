import { RecentDownloads } from '@/components/downloads/recent-downloads';
import DownloadWorkspace from '@/components/intake/download-workspace';
import { SupportedPlatforms } from '@/components/providers/supported-platforms';

export function WorkspaceHome() {
  return (
    <div className="inner-page flex flex-col gap-12" data-slot="workspace-home">
      <div className="flex flex-col gap-3">
        <DownloadWorkspace />
        <SupportedPlatforms />
      </div>
      <RecentDownloads />
    </div>
  );
}
