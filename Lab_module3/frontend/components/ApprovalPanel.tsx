"use client";

import { useState } from "react";
import { formatDuration, useCountdown } from "@/hooks/useCountdown";
import type { JobView } from "@/lib/schemas";

export const APPROVAL_TIMEOUT_MS = 30 * 60 * 1000;
const MAX_REPLANS = 1;
const MAX_FEEDBACK = 2000;

interface Props {
  job: JobView;
  busy: boolean;
  onApprove: () => void;
  onReject: (feedback: string | null) => void;
}

export default function ApprovalPanel({ job, busy, onApprove, onReject }: Props) {
  const [feedback, setFeedback] = useState("");
  const requested = job.meta.approval_requested_at;
  const deadline = requested ? Date.parse(requested) + APPROVAL_TIMEOUT_MS : null;
  const left = useCountdown(deadline);
  const replansLeft = Math.max(0, MAX_REPLANS - job.meta.replans);

  return (
    <section
      aria-labelledby="approval-title"
      className="space-y-3 rounded-lg border-2 border-blue-700 bg-blue-50 p-4 dark:bg-blue-950"
    >
      <h2 id="approval-title" className="text-lg font-semibold">
        Your approval is needed
      </h2>
      <p className="text-sm">
        Review the plan below. Approve to run it, or reject it.{" "}
        {deadline !== null && <span>The request expires in {formatDuration(left)}.</span>}
      </p>
      <label className="block text-sm">
        <span className="font-medium">Feedback for a new plan (optional)</span>
        <textarea
          value={feedback}
          maxLength={MAX_FEEDBACK}
          rows={3}
          disabled={replansLeft === 0}
          onChange={(e) => setFeedback(e.target.value)}
          placeholder={replansLeft ? "e.g. Put the models in their own step." : "No replans left"}
          className="mt-1 block w-full rounded-md border border-zinc-300 bg-white p-2 dark:border-zinc-600 dark:bg-zinc-900"
        />
      </label>
      <p className="text-xs text-zinc-700 dark:text-zinc-300">
        {replansLeft
          ? `Rejecting with feedback makes a new plan (${replansLeft} replan left); without feedback it cancels the migration.`
          : "No replans left: rejecting cancels the migration."}{" "}
        {feedback.length}/{MAX_FEEDBACK}
      </p>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={busy}
          onClick={onApprove}
          className="rounded-md bg-green-700 px-4 py-2 font-medium text-white hover:bg-green-800 disabled:bg-zinc-400"
        >
          Approve plan
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onReject(replansLeft ? feedback.trim() || null : null)}
          className="rounded-md border border-red-700 px-4 py-2 font-medium text-red-800 hover:bg-red-50 disabled:opacity-50 dark:text-red-300 dark:hover:bg-red-950"
        >
          {feedback.trim() && replansLeft ? "Reject and replan" : "Reject and cancel"}
        </button>
      </div>
    </section>
  );
}
