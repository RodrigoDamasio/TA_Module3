import type { JobView, Phase, StepStatus } from "./schemas";

export const TERMINAL: ReadonlySet<Phase> = new Set([
  "completed",
  "failed",
  "cancelled",
  "rolled_back",
]);

export const PHASE_LABELS: Record<Phase, string> = {
  analysis: "Analysis",
  planning: "Planning",
  awaiting_approval: "Awaiting approval",
  execution: "Execution",
  verification: "Verification",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  rolled_back: "Rolled back",
};

/** One sentence per phase change, for the aria-live region and the activity log. */
export const PHASE_ANNOUNCEMENTS: Record<Phase, string> = {
  analysis: "Analyzing the project.",
  planning: "Analysis finished — planning the migration.",
  awaiting_approval: "Plan ready — waiting for your approval.",
  execution: "Executing the plan.",
  verification: "All steps done — verifying the migration.",
  completed: "Migration completed.",
  failed: "Migration failed.",
  cancelled: "Migration cancelled.",
  rolled_back: "Migration rolled back — generated files hidden.",
};

export type StageState = "done" | "current" | "upcoming" | "failed" | "skipped";

export interface Stage {
  phase: Phase;
  label: string;
  state: StageState;
}

const WORK: Phase[] = ["analysis", "planning", "awaiting_approval", "execution", "verification"];

/** Where a job that ended early stopped (JobView has no "failed at" field). */
export function stoppedAt(
  job: Pick<JobView, "analysis" | "plan" | "verification" | "phase">,
): Phase {
  if (job.phase === "cancelled") return "awaiting_approval";
  if (!job.analysis) return "analysis";
  if (!job.plan) return "planning";
  if (!job.verification && job.plan.steps.some((s) => s.status !== "completed")) return "execution";
  return "verification";
}

export function stages(
  job: Pick<JobView, "analysis" | "plan" | "verification" | "phase" | "require_approval">,
): Stage[] {
  const phases = WORK.filter((p) => p !== "awaiting_approval" || job.require_approval);
  const ending: Phase = TERMINAL.has(job.phase) ? job.phase : "completed";
  const all = [...phases, ending];
  const early = job.phase === "failed" || job.phase === "cancelled";
  const stop = early ? stoppedAt(job) : job.phase;
  const stopIndex = all.indexOf(stop);
  return all.map((phase, i) => {
    let state: StageState;
    if (phase === ending && TERMINAL.has(job.phase)) {
      state = early ? "failed" : "done";
    } else if (early) {
      state = i < stopIndex ? "done" : i === stopIndex ? "failed" : "skipped";
    } else if (TERMINAL.has(job.phase)) {
      state = "done";
    } else {
      state = i < stopIndex ? "done" : i === stopIndex ? "current" : "upcoming";
    }
    return { phase, label: PHASE_LABELS[phase], state };
  });
}

export const STEP_LABELS: Record<StepStatus, string> = {
  pending: "Pending",
  in_progress: "In progress",
  completed: "Completed",
  failed: "Failed",
  skipped: "Skipped",
  rolled_back: "Rolled back",
};

// Text is always shown with the color; colors pass WCAG AA on their backgrounds.
export const STEP_STYLES: Record<StepStatus, string> = {
  pending: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  in_progress: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-200",
  completed: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-200",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200",
  skipped: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  rolled_back: "bg-zinc-200 text-zinc-800 line-through dark:bg-zinc-700 dark:text-zinc-200",
};

export const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-red-700 text-white",
  high: "bg-orange-700 text-white",
  medium: "bg-amber-200 text-amber-950",
  low: "bg-blue-100 text-blue-900",
  info: "bg-zinc-200 text-zinc-800",
};
