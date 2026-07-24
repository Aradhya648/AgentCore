// Small date formatters for list rows + message timestamps (人际消息 / 对话列表).

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** "HH:MM" clock for a message timestamp. */
export function clock(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Compact relative label for a list row's last-activity time: clock today, 昨天
 *  yesterday, M月D日 within the year, else YYYY/M/D. */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const startOfDay = (x: Date) =>
    new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOfDay(now) - startOfDay(d)) / 86_400_000);
  if (days <= 0) return clock(iso);
  if (days === 1) return "昨天";
  if (d.getFullYear() === now.getFullYear())
    return `${d.getMonth() + 1}月${d.getDate()}日`;
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
}
