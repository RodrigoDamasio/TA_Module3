import { STEP_LABELS, STEP_STYLES } from "@/lib/phases";
import { dependencyText, waves } from "@/lib/plan";
import type { Plan } from "@/lib/schemas";

export default function PlanViewer({ plan }: { plan: Plan }) {
  const groups = waves(plan.steps);
  return (
    <section aria-labelledby="plan-title" className="space-y-3">
      <h2 id="plan-title" className="text-lg font-semibold">
        3. Migration plan
        {plan.revision > 1 && (
          <span className="ml-2 text-sm font-normal text-zinc-600 dark:text-zinc-400">
            Plan revision {plan.revision}
          </span>
        )}
      </h2>
      <ol className="space-y-4">
        {groups.map((wave, w) => (
          <li key={w}>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-600 dark:text-zinc-400">
              Wave {w + 1}
              {wave.length > 1 ? ` · ${wave.length} steps can run in parallel` : ""}
            </p>
            <ul className="grid gap-3 md:grid-cols-2">
              {wave.map((step) => (
                <li
                  key={step.id}
                  className="space-y-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-700"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <h3 className="font-medium">
                      {step.id}. {step.title}
                    </h3>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${STEP_STYLES[step.status]}`}
                    >
                      {step.status === "in_progress" && (
                        <span aria-hidden className="mr-1 inline-block animate-spin">
                          ◌
                        </span>
                      )}
                      {STEP_LABELS[step.status]}
                    </span>
                  </div>
                  <p className="text-sm text-zinc-700 dark:text-zinc-300">{step.description}</p>
                  <p className="break-words font-mono text-xs">
                    {step.source_files.join(", ") || "—"} → {step.target_files.join(", ")}
                  </p>
                  <p className="flex flex-wrap gap-x-3 text-xs text-zinc-600 dark:text-zinc-400">
                    <span>Complexity: {step.complexity}</span>
                    {dependencyText(step, wave).map((text) => (
                      <span key={text}>{text}</span>
                    ))}
                    {step.attempts > 1 && <span>retried {step.attempts - 1}×</span>}
                  </p>
                  {step.error && (
                    <p className="break-words text-sm text-red-800 dark:text-red-300">
                      {step.error}
                    </p>
                  )}
                  {step.notes && (
                    <p className="text-sm text-zinc-700 dark:text-zinc-300">Notes: {step.notes}</p>
                  )}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
    </section>
  );
}
