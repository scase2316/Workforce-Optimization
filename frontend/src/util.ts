import { useEffect, useState } from "react";

let baseYear = new Date().getFullYear();
export const setBaseYear = (iso: string) => { baseYear = Number(iso.slice(0, 4)); };

export function fmt(iso: string | null | undefined): string {
  if (!iso) return "none";
  const d = new Date(iso + "T00:00:00");
  const o: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  if (d.getFullYear() !== baseYear) o.year = "numeric";
  return d.toLocaleDateString("en-US", o);
}

export function addDays(iso: string, n: number): string {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

export const plural = (n: number, one: string, many = one + "s") => `${n} ${n === 1 ? one : many}`;

export const STATUS_LABEL: Record<string, string> = {
  complete: "Ready", expiring: "Expiring", gap: "Open", overdue: "Overdue",
};

export function useWidth<T extends HTMLElement>() {
  const [el, setEl] = useState<T | null>(null);      // callback ref: works even if the element mounts late
  const [w, setW] = useState(900);
  useEffect(() => {
    if (!el) return;
    const measure = (width: number) => setW(Math.max(480, Math.floor(width)));
    measure(el.getBoundingClientRect().width);
    const ro = new ResizeObserver(([e]) => measure(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [setEl, w] as const;
}

export const MONTH = 30.4375;
/** "548 days" -> "about 18 months (548 days)". Short spans stay in days. */
export function span(days: number): string {
  if (days % 365 === 0 && days >= 365) return plural(days / 365, "year");
  const m = days / MONTH;
  if (days >= 60) return `${Number.isInteger(Math.round(m * 10) / 10) ? Math.round(m) : m.toFixed(1)} months (${days} days)`;
  return plural(days, "day");
}
