"use client";

import { useEffect, useState } from "react";
import { type Stage, stages } from "@/lib/phases";
import type { JobView } from "@/lib/schemas";

const MARK: Record<Stage["state"], string> = {
  done: "✓",
  current: "●",
  upcoming: "○",
  failed: "✗",
  skipped: "–",
};

const STYLE: Record<Stage["state"], string> = {
  done: "border-green-700 bg-green-700 text-white",
  current: "border-blue-700 bg-white text-blue-800 dark:bg-zinc-900 dark:text-blue-300",
  upcoming: "border-zinc-400 bg-white text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400",
  failed: "border-red-700 bg-red-700 text-white",
  skipped: "border-zinc-300 bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
};

const STATE_TEXT: Record<Stage["state"], string> = {
  done: "done",
  current: "in progress",
  upcoming: "upcoming",
  failed: "stopped here",
  skipped: "not reached",
};

function Elapsed({ phase }: { phase: string }) {
  const [seconds, setSeconds] = useState(0);
  const [shown, setShown] = useState(phase);
  if (shown !== phase) {
    setShown(phase); // new phase: restart the timer
    setSeconds(0);
  }
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, [phase]);
  return <span className="text-xs text-zinc-600 dark:text-zinc-400">{seconds} s</span>;
}

interface Props {
  job: JobView;
  announcement: string; // latest progress sentence, read by screen readers
  replay?: boolean;
}

export default function PhaseStepper({ job, announcement, replay }: Props) {
  const list = stages(job);
  return (
    <section aria-labelledby="progress-title" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="progress-title" className="text-lg font-semibold">
          2. Progress
        </h2>
        {replay && (
          <span className="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-900 dark:bg-violet-950 dark:text-violet-200">
            Stored result — replay (0 LLM calls)
          </span>
        )}
      </div>
      <ol className="flex flex-wrap gap-x-2 gap-y-3">
        {list.map((stage, i) => (
          <li
            key={stage.phase}
            aria-current={stage.state === "current" ? "step" : undefined}
            className="flex items-center gap-2"
          >
            <span
              aria-hidden
              className={`flex h-7 w-7 items-center justify-center rounded-full border-2 text-sm font-bold ${STYLE[stage.state]} ${stage.state === "current" ? "animate-pulse" : ""}`}
            >
              {MARK[stage.state]}
            </span>
            <span className="flex flex-col leading-tight">
              <span className={`text-sm ${stage.state === "current" ? "font-semibold" : ""}`}>
                {stage.label}
              </span>
              <span className="sr-only">({STATE_TEXT[stage.state]})</span>
              {stage.state === "current" && <Elapsed phase={stage.phase} />}
            </span>
            {i < list.length - 1 && (
              <span aria-hidden className="text-zinc-400">
                →
              </span>
            )}
          </li>
        ))}
      </ol>
      <p aria-live="polite" className="sr-only">
        {announcement}
      </p>
    </section>
  );
}
