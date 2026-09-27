"use client";

import { useEffect, useMemo, useState } from "react";
import { useCountdown } from "@/hooks/useCountdown";
import { useJob } from "@/hooks/useJob";
import { useReplay } from "@/hooks/useReplay";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/api";
import { checkProject, type DraftFile, draftFile, normalizePath } from "@/lib/files";
import type { Framework, JobView, Sample } from "@/lib/schemas";
import ActivityLog from "./ActivityLog";
import ApprovalPanel from "./ApprovalPanel";
import ErrorBanner from "./ErrorBanner";
import FilesPanel from "./FilesPanel";
import MetaBar from "./MetaBar";
import PhaseStepper from "./PhaseStepper";
import PlanViewer from "./PlanViewer";
import ProjectInput from "./ProjectInput";
import VerificationPanel from "./VerificationPanel";

function setJobParam(id: string | null) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("job", id);
  else url.searchParams.delete("job");
  window.history.replaceState(null, "", url);
}

function RollbackControl({ busy, onConfirm }: { busy: boolean; onConfirm: () => void }) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <button
        type="button"
        onClick={() => setAsking(true)}
        className="rounded-md border border-zinc-400 px-3 py-1.5 text-sm"
      >
        Roll back
      </button>
    );
  }
  return (
    <div
      role="group"
      aria-label="Confirm rollback"
      className="flex flex-wrap items-center gap-2 text-sm"
    >
      <span>Hide all generated files? The history is kept.</span>
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          setAsking(false);
          onConfirm();
        }}
        className="rounded-md bg-red-700 px-3 py-1.5 font-medium text-white disabled:bg-zinc-400"
      >
        Confirm rollback
      </button>
      <button type="button" onClick={() => setAsking(false)} className="px-2 py-1.5 underline">
        Cancel
      </button>
    </div>
  );
}

export default function MigrationApp({ initialJobId = null }: { initialJobId?: string | null }) {
  const [frameworks, setFrameworks] = useState<Framework[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [pair, setPair] = useState<Framework | null>(null);
  const [files, setFiles] = useState<DraftFile[]>(() => [draftFile()]);
  const [requireApproval, setRequireApproval] = useState(true);
  const [jobId, setJobId] = useState<string | null>(initialJobId); // ?job= resumes a job
  const [stored, setStored] = useState<JobView | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [retryAt, setRetryAt] = useState<number | null>(null);
  const cooldown = useCountdown(retryAt);

  const live = useJob(jobId);
  const replay = useReplay(stored);
  const view = stored ? replay.view : live.job;
  const log = stored ? replay.log : live.log;
  const check = useMemo(() => checkProject(files, pair?.source_extensions ?? []), [files, pair]);

  const fail = (err: unknown) => {
    if (!(err instanceof ApiError)) throw err;
    setError(err);
    setRetryAt(err.retryAfter ? Date.now() + err.retryAfter * 1000 : null);
  };

  useEffect(() => {
    Promise.all([api.listFrameworks(), api.listSamples()])
      .then(([pairs, sampleList]) => {
        setFrameworks(pairs);
        setPair((current) => current ?? pairs[0] ?? null);
        setSamples(sampleList);
      })
      .catch((err) => {
        if (err instanceof ApiError) setError(err);
      });
  }, []);

  // A resumed job shows its own pair and files (read-only).
  const shownPair = view ? (frameworks.find((f) => f.id === view.pair) ?? pair) : pair;

  const submit = async () => {
    if (!pair || check.problem) return;
    setSubmitting(true);
    setError(null);
    try {
      const accepted = await api.migrate({
        files: files.map((f) => ({ path: normalizePath(f.path), content: f.content })),
        source_framework: pair.source,
        target_framework: pair.target,
        require_approval: requireApproval,
      });
      setStored(null);
      setJobId(accepted.job_id);
      setJobParam(accepted.job_id);
    } catch (err) {
      fail(err);
    } finally {
      setSubmitting(false);
    }
  };

  const loadSample = async (id: string) => {
    setError(null);
    try {
      const sample = await api.getSample(id);
      const samplePair = frameworks.find(
        (f) => f.source === sample.source_framework && f.target === sample.target_framework,
      );
      if (samplePair) setPair(samplePair);
      setFiles(sample.files.map((f) => draftFile(f.path, f.content)));
      setJobId(null);
      setJobParam(null);
      setStored(sample.result);
    } catch (err) {
      fail(err);
    }
  };

  const startNew = () => {
    if (view && !stored) setFiles(view.source_files.map((f) => draftFile(f.path, f.content)));
    setJobId(null);
    setStored(null);
    setJobParam(null);
    setError(null);
  };

  const runForReal = () => {
    setStored(null);
    void submit();
  };

  const locked = !!jobId || !!stored;
  const shownFiles =
    view && !stored ? view.source_files.map((f, i) => ({ key: `v${i}`, ...f })) : files;
  const jobError = live.error;
  const canRollback = !stored && view && (view.phase === "completed" || view.phase === "failed");

  return (
    <div className="space-y-10">
      <div className="grid gap-8 lg:grid-cols-2">
        <ProjectInput
          frameworks={frameworks}
          samples={samples}
          pair={shownPair}
          onPair={setPair}
          files={shownFiles}
          onFiles={setFiles}
          requireApproval={view && !stored ? view.require_approval : requireApproval}
          onRequireApproval={setRequireApproval}
          check={locked ? { ...check, fileErrors: {} } : check}
          locked={locked}
          submitting={submitting}
          cooldown={cooldown}
          onSubmit={submit}
          onSample={loadSample}
          onNew={startNew}
        />

        <div className="min-w-0 space-y-4">
          {error && <ErrorBanner error={error} cooldown={cooldown} />}
          {jobError && (
            <ErrorBanner
              error={jobError}
              cooldown={0}
              action={
                jobError.kind === "not_found"
                  ? { label: "New migration", onClick: startNew }
                  : undefined
              }
            />
          )}
          {view ? (
            <>
              <PhaseStepper job={view} announcement={log.at(-1)?.text ?? ""} replay={!!stored} />
              {live.live === "polling" && !stored && (
                <p role="status" className="text-sm text-amber-900 dark:text-amber-200">
                  Live updates interrupted — refreshing every few seconds.
                </p>
              )}
              <ActivityLog entries={log} />
              {!stored && view.phase === "awaiting_approval" && (
                <ApprovalPanel
                  job={view}
                  busy={live.busy}
                  onApprove={live.approve}
                  onReject={live.reject}
                />
              )}
              <MetaBar job={view} />
              {canRollback && <RollbackControl busy={live.busy} onConfirm={live.rollback} />}
              {stored && replay.finished && (
                <button
                  type="button"
                  onClick={runForReal}
                  disabled={!!check.problem || cooldown > 0}
                  className="rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 disabled:bg-zinc-400"
                >
                  Run it for real
                </button>
              )}
            </>
          ) : (
            !jobError && (
              <p className="rounded-lg border border-dashed border-zinc-300 p-6 text-sm text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
                Progress, the plan and the migrated files appear here. Add your files and press
                Migrate, or try a sample to replay a stored real migration (free).
              </p>
            )
          )}
        </div>
      </div>

      {view?.plan && <PlanViewer plan={view.plan} />}
      {view && <VerificationPanel job={view} />}
      {view && <FilesPanel job={view} />}
    </div>
  );
}
