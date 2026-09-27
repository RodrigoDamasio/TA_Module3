import type { Step } from "./schemas";

/** Groups steps into "waves": every step of a wave depends only on earlier waves, so the
 * backend's scheduler may run a wave's steps in parallel. */
export function waves(steps: Step[]): Step[][] {
  const level = new Map<number, number>();
  const byId = new Map(steps.map((s) => [s.id, s]));
  const visit = (step: Step, trail: Set<number>): number => {
    const known = level.get(step.id);
    if (known !== undefined) return known;
    if (trail.has(step.id)) return 0; // cycles are rejected by the backend; never loop here
    trail.add(step.id);
    const deps = step.depends_on.map((id) => byId.get(id)).filter((s): s is Step => !!s);
    const value = deps.length ? Math.max(...deps.map((d) => visit(d, trail))) + 1 : 0;
    level.set(step.id, value);
    return value;
  };
  steps.forEach((s) => visit(s, new Set()));
  const result: Step[][] = [];
  for (const step of steps) {
    const index = level.get(step.id) ?? 0;
    (result[index] ??= []).push(step);
  }
  return result.filter(Boolean);
}

/** "after 1, 2" / "runs in parallel with 3" — the DAG in words. */
export function dependencyText(step: Step, wave: Step[]): string[] {
  const parts: string[] = [];
  if (step.depends_on.length) parts.push(`after ${step.depends_on.join(", ")}`);
  const siblings = wave.filter((s) => s.id !== step.id).map((s) => s.id);
  if (siblings.length) parts.push(`runs in parallel with ${siblings.join(", ")}`);
  return parts;
}
