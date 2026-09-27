"use client";

import { useEffect, useRef } from "react";
import type { LogEntry } from "@/hooks/useJob";

export default function ActivityLog({ entries }: { entries: LogEntry[] }) {
  const list = useRef<HTMLOListElement>(null);
  useEffect(() => {
    list.current?.lastElementChild?.scrollIntoView?.({ block: "nearest" });
  }, [entries.length]);
  return (
    <details open className="rounded-lg border border-zinc-200 dark:border-zinc-700">
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
        Activity ({entries.length})
      </summary>
      <ol
        ref={list}
        aria-label="Activity"
        tabIndex={0}
        className="max-h-48 space-y-1 overflow-y-auto border-t border-zinc-200 px-3 py-2 text-sm dark:border-zinc-700"
      >
        {entries.length === 0 && <li className="text-zinc-600 dark:text-zinc-400">Waiting…</li>}
        {entries.map((entry) => (
          <li key={entry.key} className="break-words">
            {entry.text}
          </li>
        ))}
      </ol>
    </details>
  );
}
