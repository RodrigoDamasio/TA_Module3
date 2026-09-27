import { SEVERITY_STYLES, TERMINAL } from "@/lib/phases";
import type { JobView } from "@/lib/schemas";

const CHECK_LABELS: Record<string, string> = {
  compiles: "Parses and compiles",
  lint: "No blocking lint errors",
  imports_resolve: "Imports between files resolve",
  framework_migrated: "No source-framework code left",
  routes_preserved: "Every route preserved",
  files_generated: "Files generated",
};

export default function VerificationPanel({ job }: { job: JobView }) {
  const v = job.verification;
  const ended = TERMINAL.has(job.phase);
  if (!v && job.errors.length === 0 && !ended) return null;
  const banner = job.success
    ? {
        style: "bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-100",
        text: "Migration verified",
      }
    : {
        style: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-100",
        text:
          job.phase === "cancelled"
            ? "Migration cancelled"
            : job.phase === "rolled_back"
              ? "Migration rolled back"
              : "Migration not verified",
      };

  return (
    <section aria-labelledby="verification-title" className="space-y-3">
      <h2 id="verification-title" className="text-lg font-semibold">
        4. Verification
      </h2>
      {ended && (
        <p className={`rounded-md px-3 py-2 font-medium ${banner.style}`}>
          {job.success ? "✓ " : "✗ "}
          {banner.text}
          {v && ` · confidence ${v.confidence}/10`}
        </p>
      )}
      {job.errors.length > 0 && (
        <ul className="space-y-1 text-sm text-red-800 dark:text-red-300">
          {job.errors.map((e, i) => (
            <li key={i} className="break-words">
              {e}
            </li>
          ))}
        </ul>
      )}
      {v && (
        <>
          <ul className="space-y-1 text-sm">
            {v.checks.map((c, i) => (
              <li key={`${c.name}-${i}`} className="flex gap-2">
                <span
                  aria-hidden
                  className={
                    c.passed
                      ? "text-green-700 dark:text-green-400"
                      : "text-red-700 dark:text-red-400"
                  }
                >
                  {c.passed ? "✓" : "✗"}
                </span>
                <span className="min-w-0 break-words">
                  <span className="font-medium">{CHECK_LABELS[c.name] ?? c.name}</span>
                  <span className="sr-only">{c.passed ? " (passed)" : " (failed)"}</span>
                  <span className="text-zinc-600 dark:text-zinc-400"> — {c.detail}</span>
                </span>
              </li>
            ))}
          </ul>
          {v.issues.length > 0 && (
            <div className="space-y-2">
              <h3 className="font-medium">Reviewer issues</h3>
              <ul className="space-y-2 text-sm">
                {v.issues.map((issue, i) => (
                  <li key={i} className="flex flex-wrap items-start gap-2">
                    <span
                      className={`rounded px-1.5 py-0.5 text-xs font-semibold uppercase ${SEVERITY_STYLES[issue.severity] ?? SEVERITY_STYLES.info}`}
                    >
                      {issue.severity}
                    </span>
                    <span className="font-mono text-xs">
                      {issue.file}
                      {issue.line ? `:${issue.line}` : ""}
                    </span>
                    <span className="min-w-0 basis-full break-words">{issue.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}
