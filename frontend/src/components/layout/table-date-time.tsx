const dateFormatter = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' });
const timeFormatter = new Intl.DateTimeFormat('zh-CN', { timeStyle: 'short' });
const preciseTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeStyle: 'medium',
});

/** Keep the date and clock readable without forcing a wide timestamp column. */
export function TableDateTime({
  value,
  seconds = false,
}: {
  value: string;
  seconds?: boolean;
}) {
  const date = new Date(value);
  return (
    <time
      dateTime={value}
      className="inline-flex flex-col whitespace-nowrap tabular-nums"
    >
      <span>{dateFormatter.format(date)}</span>{' '}
      <span>
        {(seconds ? preciseTimeFormatter : timeFormatter).format(date)}
      </span>
    </time>
  );
}
