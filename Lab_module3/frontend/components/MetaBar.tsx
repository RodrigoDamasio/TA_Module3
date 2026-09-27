import { download } from "@/lib/download";
import type { JobView } from "@/lib/schemas";

function seconds(from: string, to: string | null): number | null {
  if (!to) return null;
  return Math.max(0, Math.round((Date.parse(to) - Date.parse(from)) / 1000));
}

/** The lab's JSON contract: success, migrated files, executed plan, verification, errors. */
export function resultJson(job: JobView): string {
  return JSON.stringify(
    {
      job_id: job.job_id,
      success: job.success,
      migrated_files: job.migrated_files,
      plan: job.plan,
      verification: job.verification,
      errors: job.errors,
      meta: job.meta,
    },
    null,
    2,
  );
}

export default function MetaBar({ job }: { job: JobView }) {
  const m = job.meta;
  const duration = seconds(m.started_at, m.finished_at);
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-600 dark:text-zinc-400">
      <span>Model {m.model}</span>
      <span>Prompts v{m.prompt_version}</span>
      <span>
        LLM calls {m.llm_calls}
        {m.cached_calls ? ` (+${m.cached_calls} cached)` : ""}
      </span>
      <span>
        Tokens {m.tokens.input.toLocaleString("en")} in / {m.tokens.output.toLocaleString("en")} out
      </span>
      {duration !== null && <span>Duration {duration} s</span>}
      <button
        type="button"
        onClick={() => download(`${job.job_id}.json`, resultJson(job), "application/json")}
        className="rounded-md border border-zinc-300 px-2 py-1 text-zinc-800 dark:border-zinc-600 dark:text-zinc-200"
      >
        Download result JSON
      </button>
    </div>
  );
}
