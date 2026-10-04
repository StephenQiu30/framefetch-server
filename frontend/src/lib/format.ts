export function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remaining = String(Math.floor(seconds % 60)).padStart(2, '0');
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${remaining}`
    : `${minutes}:${remaining}`;
}

export function formatMilliseconds(milliseconds: number): string {
  return formatDuration(Math.floor(milliseconds / 1000));
}

export function formatMillisecondRange(start: number, end: number): string {
  const first = formatMilliseconds(start);
  return start === end ? first : `${first}–${formatMilliseconds(end)}`;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits: value >= 100 ? 0 : 1,
  }).format(value)} ${units[unit]}`;
}
