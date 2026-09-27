import { useEffect, useState } from "react";

/** Seconds left until `deadline` (ms since epoch), ticking every second; 0 when passed. */
export function useCountdown(deadline: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (deadline === null) return;
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0); // measure from the moment the deadline was set
    const timer = setInterval(() => {
      tick();
      if (Date.now() >= deadline) clearInterval(timer);
    }, 1000);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [deadline]);
  return deadline === null ? 0 : Math.max(0, Math.ceil((deadline - now) / 1000));
}

export function formatDuration(seconds: number): string {
  if (seconds >= 3600) return `about ${Math.round(seconds / 3600)} h`;
  if (seconds >= 60) return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
  return `${seconds} s`;
}
