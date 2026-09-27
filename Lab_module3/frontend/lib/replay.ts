/** Replays a stored job (a sample's real result) as a timeline of snapshots, so the same
 * components animate through the phases — 0 LLM calls. */
import { PHASE_ANNOUNCEMENTS } from "./phases";
import type { JobView, Step } from "./schemas";

export interface Frame {
  view: JobView;
  message: string;
}

export const FRAME_MS = 600;

export function replayFrames(job: JobView): Frame[] {
  const steps = job.plan?.steps ?? [];
  const blank: JobView = {
    ...job,
    phase: "analysis",
    success: false,
    analysis: null,
    plan: null,
    verification: null,
    migrated_files: [],
    errors: [],
  };
  const withSteps = (status: (s: Step) => Step["status"]): JobView["plan"] =>
    job.plan && { ...job.plan, steps: steps.map((s) => ({ ...s, status: status(s) })) };

  const frames: Frame[] = [
    { view: blank, message: PHASE_ANNOUNCEMENTS.analysis },
    {
      view: { ...blank, phase: "planning", analysis: job.analysis },
      message: PHASE_ANNOUNCEMENTS.planning,
    },
  ];
  const planned = { ...blank, phase: "execution" as const, analysis: job.analysis };
  frames.push({
    view: { ...planned, plan: withSteps(() => "pending") },
    message: `Plan ready: ${steps.length} step${steps.length === 1 ? "" : "s"}.`,
  });
  const done = new Set<number>();
  for (const step of steps) {
    frames.push({
      view: {
        ...planned,
        plan: withSteps((s) =>
          done.has(s.id) ? "completed" : s.id === step.id ? "in_progress" : "pending",
        ),
        migrated_files: job.migrated_files.filter((f) => done.has(f.step_id)),
      },
      message: `Step ${step.id} started: ${step.title}`,
    });
    done.add(step.id);
    frames.push({
      view: {
        ...planned,
        plan: withSteps((s) => (done.has(s.id) ? "completed" : "pending")),
        migrated_files: job.migrated_files.filter((f) => done.has(f.step_id)),
      },
      message: `Step ${step.id} completed: ${step.title}`,
    });
  }
  frames.push({
    view: { ...planned, phase: "verification", plan: job.plan, migrated_files: job.migrated_files },
    message: PHASE_ANNOUNCEMENTS.verification,
  });
  frames.push({ view: job, message: PHASE_ANNOUNCEMENTS[job.phase] });
  return frames;
}
