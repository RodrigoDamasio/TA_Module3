import { useEffect, useMemo, useState } from "react";
import { FRAME_MS, replayFrames } from "@/lib/replay";
import type { JobView } from "@/lib/schemas";
import type { LogEntry } from "./useJob";

/** Plays a stored job frame by frame (0 LLM calls). */
export function useReplay(stored: JobView | null) {
  const frames = useMemo(() => (stored ? replayFrames(stored) : []), [stored]);
  const [position, setPosition] = useState({ frames, index: 0 });
  if (position.frames !== frames) setPosition({ frames, index: 0 }); // new sample: restart
  const index = position.frames === frames ? position.index : 0;
  const last = frames.length - 1;

  useEffect(() => {
    if (index >= last) return;
    const timer = setTimeout(() => setPosition({ frames, index: index + 1 }), FRAME_MS);
    return () => clearTimeout(timer);
  }, [frames, index, last]);

  const log: LogEntry[] = frames
    .slice(0, index + 1)
    .map((frame, i) => ({ key: `r${i}`, text: frame.message }));
  return { view: frames[index]?.view ?? null, log, finished: index >= last };
}
