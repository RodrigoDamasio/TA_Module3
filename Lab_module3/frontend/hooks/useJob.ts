/** A live migration job: the JobView is the source of truth; SSE events update the view
 * at once and trigger a (debounced) refetch. If the stream is lost, poll instead. */
import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/api";
import { subscribe } from "@/lib/events";
import { PHASE_ANNOUNCEMENTS, TERMINAL } from "@/lib/phases";
import type { JobEvent, JobView } from "@/lib/schemas";

export const REFETCH_DEBOUNCE_MS = 300;
export const POLL_MS = 3000;

export type LiveState = "connecting" | "live" | "polling" | "ended";

export interface LogEntry {
  key: string;
  text: string;
}

export function describeEvent(event: JobEvent): string | null {
  switch (event.type) {
    case "phase":
      return PHASE_ANNOUNCEMENTS[event.data.phase];
    case "analysis":
      return `Analysis: ${event.data.summary}`;
    case "plan":
      return `Plan revision ${event.data.revision}: ${event.data.steps.length} step(s).`;
    case "step": {
      const d = event.data;
      const status = d.status.replace("_", " ");
      return `Step ${d.id} (${d.title}): ${status}${d.error ? ` — ${d.error}` : ""}`;
    }
    case "verification":
      return `Verification: ${event.data.passed ? "passed" : "not passed"}, confidence ${event.data.confidence}/10.`;
    case "error":
      return `Error: ${event.data.message}`;
    case "done":
      return null; // the final phase event already says it
  }
}

/** Applies an event to the view so the UI moves before the refetch arrives. */
export function applyEvent(job: JobView, event: JobEvent): JobView {
  switch (event.type) {
    case "phase":
    case "done":
      return { ...job, phase: event.data.phase };
    case "analysis":
      return { ...job, analysis: event.data };
    case "plan":
      return { ...job, plan: event.data };
    case "step": {
      if (!job.plan) return job;
      const step = event.data; // a Step (+ the files it wrote)
      const steps = job.plan.steps.map((s) => (s.id === step.id ? step : s));
      return { ...job, plan: { ...job.plan, steps } };
    }
    case "verification":
      return { ...job, verification: event.data };
    case "error":
      return { ...job, errors: [...job.errors, event.data.message] };
  }
}

export function useJob(jobId: string | null) {
  const [job, setJob] = useState<JobView | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [live, setLive] = useState<LiveState>("connecting");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [trackedId, setTrackedId] = useState(jobId);
  if (trackedId !== jobId) {
    // Another job: reset during render (not in the effect) — React's pattern for this.
    setTrackedId(jobId);
    setJob(null);
    setLog([]);
    setError(null);
    setLive("connecting");
  }

  const refetch = useCallback(async (id: string) => {
    try {
      const view = await api.getJob(id);
      setJob(view);
      return view;
    } catch (err) {
      if (err instanceof ApiError) setError(err);
      return null;
    }
  }, []);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let subscription: { close: () => void } | null = null;
    let poll: ReturnType<typeof setInterval> | null = null;

    const startPolling = () => {
      setLive("polling");
      poll = setInterval(async () => {
        const view = await refetch(jobId);
        if (!view || TERMINAL.has(view.phase)) {
          if (poll) clearInterval(poll);
          setLive("ended");
        }
      }, POLL_MS);
    };

    (async () => {
      const view = await refetch(jobId);
      if (cancelled || !view) return;
      if (TERMINAL.has(view.phase)) {
        setLive("ended");
        return;
      }
      subscription = subscribe(api.eventsUrl(jobId), {
        onEvent: (event) => {
          setLive(event.type === "done" ? "ended" : "live");
          setJob((current) => (current ? applyEvent(current, event) : current));
          const text = describeEvent(event);
          if (text) setLog((entries) => [...entries, { key: `${event.id}`, text }]);
          if (refetchTimer.current) clearTimeout(refetchTimer.current);
          refetchTimer.current = setTimeout(() => refetch(jobId), REFETCH_DEBOUNCE_MS);
        },
        onLost: () => {
          if (!cancelled) startPolling();
        },
        onInvalid: () =>
          setError(new ApiError("invalid_response", "Unexpected update from the server.")),
      });
    })();

    return () => {
      cancelled = true;
      subscription?.close();
      if (poll) clearInterval(poll);
      if (refetchTimer.current) clearTimeout(refetchTimer.current);
    };
  }, [jobId, refetch]);

  const act = useCallback(
    async (action: (id: string) => Promise<JobView>) => {
      if (!jobId) return;
      setBusy(true);
      setError(null);
      try {
        const view = await action(jobId);
        setJob((current) => ({ ...view, history: view.history ?? current?.history }));
        await refetch(jobId); // brings the history (include_history) and the latest events' effects
      } catch (err) {
        if (err instanceof ApiError) {
          setError(err);
          if (err.kind === "conflict") await refetch(jobId);
        }
      } finally {
        setBusy(false);
      }
    },
    [jobId, refetch],
  );

  return {
    job,
    log,
    live,
    error,
    busy,
    approve: () => act(api.approve),
    reject: (feedback: string | null) => act((id) => api.reject(id, feedback)),
    rollback: () => act(api.rollback),
  };
}
