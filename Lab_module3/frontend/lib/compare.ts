/** "Compare with" options for a migrated file (FRONTEND_PLAN §5). Migration is not 1:1
 * (app.py → main.py, views.py + urls.py → main.py), so the user picks the left side. */
import type { JobView, MigratedFile } from "./schemas";

export interface CompareOption {
  id: string;
  label: string;
  content: string;
}

export function compareOptions(file: MigratedFile, job: JobView): CompareOption[] {
  const options: CompareOption[] = [];
  const sources = new Map(job.source_files.map((s) => [s.path, s.content]));
  const add = (path: string, why: string) => {
    const content = sources.get(path);
    if (content !== undefined && !options.some((o) => o.id === `source:${path}`)) {
      options.push({ id: `source:${path}`, label: `Source ${path} (${why})`, content });
    }
  };

  add(file.path, "same path");
  const step = job.plan?.steps.find((s) => s.id === file.step_id);
  step?.source_files.forEach((path) => add(path, `read by step ${step.id}`));
  if (options.length === 0) job.source_files.forEach((s) => add(s.path, "source"));

  const earlier = (job.history ?? [])
    .filter((v) => v.path === file.path && v.version < file.version)
    .sort((a, b) => b.version - a.version);
  for (const v of earlier) {
    options.push({
      id: `version:${v.version}`,
      label: `Version ${v.version} (step ${v.step_id}${v.hidden ? ", discarded" : ""})`,
      content: v.content,
    });
  }
  return options;
}
